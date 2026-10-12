import copy
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from breeding_cost import PriceBook, material_record
from models import Monster
import planner_worker
from planner_worker import PlannerJob, calculate, decode_result, encode_request, _prices_current


def sample_request():
    mother = Monster(id="worker-mother", species="鲤鱼王", gender="F",
                     ivs=[31, 1, 1, 1, 1, 1], egg_groups=["水中2", "龙"])
    father = Monster(id="worker-father", species="鲤鱼王", gender="M",
                     ivs=[1, 31, 1, 1, 1, 1], egg_groups=["水中2", "龙"])
    book = PriceBook()
    for monster in (mother, father):
        book.prices[material_record(monster)["key"]] = 3000
    return ([mother, father], "鲤鱼王", "", "", "31/31/x/x/x/x", ["水中2", "龙"],
            False, False, "cost", "late", False, frozenset(), "smart", False, (), False, frozenset(), book)


class PlannerWorkerTests(unittest.TestCase):
    def setUp(self):
        self.previous = planner_worker._recent_result
        planner_worker._recent_result = None

    def tearDown(self):
        planner_worker._recent_result = self.previous

    def await_result(self, job):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            result = job.poll()
            if result is not None:
                return result
            time.sleep(.02)
        self.fail("Local planning worker timed out")

    def test_real_process_preserves_route_cost_and_reuses_identical_result(self):
        request = sample_request()
        job = PlannerJob(request)
        self.assertIsNotNone(job.process)
        folder = Path(job.directory.name)
        try:
            report, candidates, error = self.await_result(job)
            self.assertFalse(error, error)
            self.assertTrue(report)
            self.assertTrue(candidates)
            self.assertEqual(candidates[0].cost_report().total_known, 26000)
            self.assertEqual(candidates[0].cost_report().cash_known, 20000)
            self.assertEqual(candidates[0].root.used_ids, frozenset({"worker-mother", "worker-father"}))
            cached = PlannerJob(request)
            self.assertIsNone(cached.process)
            self.assertEqual(cached.poll()[1][0].root.to_dict(), candidates[0].root.to_dict())
            cached.release()
            changed = list(request)
            changed[-1] = PriceBook(request[-1].to_dict())
            changed[-1].brace = 12000
            modified = PlannerJob(changed)
            try:
                self.assertIsNotNone(modified.process)
                self.assertEqual(self.await_result(modified)[1][0].cost_report().total_known, 30000)
            finally:
                modified.release(cancel=True)
        finally:
            job.release(cancel=True)
        deadline = time.monotonic() + 5
        while folder.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertFalse(folder.exists(), "Worker temporary inventory must be removed")

    def test_cancel_terminates_only_owned_process_without_waiting_in_ui(self):
        popen = subprocess.Popen
        def slow_process(*args, **kwargs):
            return popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        with patch("planner_worker.subprocess.Popen", side_effect=slow_process):
            job = PlannerJob(sample_request())
        started = time.monotonic()
        job.release(cancel=True)
        self.assertLess(time.monotonic() - started, .5)
        self.assertIsNotNone(job.process.wait(timeout=5))
        job.release(cancel=True)  # Closing again is harmless.

    def test_quote_age_blocks_cached_auto_prices_and_input_is_unchanged(self):
        payload = encode_request(sample_request())
        original = copy.deepcopy(payload)
        value = calculate(payload)
        self.assertEqual(payload, original)
        self.assertFalse(decode_result(value)[2])
        self.assertTrue(_prices_current(value))
        value["candidates"][0]["cost_pricing"]["auto_materials"] = {
            "old": dict(at=time.time() - 86401, price=3000, source="行情")}
        self.assertFalse(_prices_current(value))

    def test_tk_events_continue_while_planning_process_is_busy(self):
        import tkinter as tk
        from app import App
        popen = subprocess.Popen
        def busy_process(*args, **kwargs):
            return popen([sys.executable, "-c", "import time; end=time.monotonic()+30\nwhile time.monotonic()<end: pass"], **kwargs)
        with patch("planner_worker.subprocess.Popen", side_effect=busy_process):
            job = PlannerJob(sample_request())
        root = tk.Tk()
        root.withdraw()
        instance = App.__new__(App)
        instance.root, instance.plan_job = root, job
        instance.plan_request_id, instance.plan_worker_busy = 1, True
        instance.plan_status_var = tk.StringVar(root)
        ticks = []
        def heartbeat():
            ticks.append(time.monotonic())
            root.after(20, heartbeat)
        try:
            heartbeat()
            instance._poll_plan_result(1)
            deadline = time.monotonic() + .35
            while time.monotonic() < deadline:
                root.update()
                time.sleep(.005)
            self.assertGreaterEqual(len(ticks), 8)
            self.assertIn("正在计算规划", instance.plan_status_var.get())
            self.assertIsNone(job.process.poll())
        finally:
            job.release(cancel=True)
            for callback in root.tk.call("after", "info"):
                root.after_cancel(callback)
            root.destroy()
