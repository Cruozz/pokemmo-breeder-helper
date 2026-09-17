import queue
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from storage import load_active_plan, load_inventory, save_active_plan, save_inventory, consume_parents_and_add_child
from test_execution_consistency import app_fixture


def reset_fixture():
    app = app_fixture()
    app.root = Mock()
    app.plan_request_id = 7
    app.plan_result_queue = queue.Queue()
    app.current_candidates = [object()]
    app.plan_candidate_cache = {"old": object()}
    app.expanded_completed_sources = {("active", 1)}
    app.auto_replan_reason = "旧路线"
    app.auto_replan_progress_keys = {("a", "b")}
    app.auto_replan_preferred_material_ids = {"a"}
    app.plan_excluded_ids = {"protected"}
    app.plan_exclusion_history = ["protected"]
    app.plan_exclusion_scope_id = 123
    for name in ("plan_summary_var", "plan_purchase_var", "plan_purchase_label", "plan_view_label",
                 "_update_plan_exclusion_ui", "_set_planner_details_collapsed", "_set_planner_busy"):
        setattr(app, name, Mock())
    app.plan_map = Mock()
    app.detached_plan_map = Mock()
    app.detached_plan_map.winfo_exists.return_value = True
    return app


class PlanningResetTests(unittest.TestCase):
    def test_abandon_partial_plan_clears_saved_route_but_keeps_real_inventory_and_history(self):
        with tempfile.TemporaryDirectory() as directory, patch("storage.data_dir", return_value=Path(directory)):
            app = reset_fixture()
            save_inventory(app.inventory)
            first = app.active_plan.steps[0]
            consume_parents_and_add_child((first.parent_a_id, first.parent_b_id), first.child,
                                         app.active_plan.id, first.number, plan_snapshot=app.active_plan.to_dict())
            first.completed = True
            save_active_plan(app.active_plan.to_dict())
            before = [monster.to_dict() for monster in load_inventory()]
            with patch("app.messagebox.askyesno", return_value=True):
                app.clear_current_plan()
            self.assertIsNone(load_active_plan())
            self.assertEqual(before, [monster.to_dict() for monster in load_inventory()])
            import sqlite3
            with closing(sqlite3.connect(Path(directory) / "inventory.db")) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM consumption_history").fetchone()[0], 1)
            self.assertIsNone(app.active_plan)
            self.assertIsNone(app.proposed_plan)
            self.assertEqual(app.current_candidates, [])
            self.assertEqual(app.plan_candidate_cache, {})
            self.assertEqual(app.plan_excluded_ids, set())
            self.assertEqual(app.auto_replan_progress_keys, set())
            self.assertIsNone(app.displayed_plan_id)
            self.assertIsNone(app.plan_map.set_root.call_args.args[0])
            self.assertIsNone(app.detached_plan_map.set_root.call_args.args[0])

    def test_cancel_preserves_route(self):
        app = reset_fixture()
        plan = app.active_plan
        with patch("app.messagebox.askyesno", return_value=False), patch("app.save_active_plan") as save:
            app.clear_current_plan()
        save.assert_not_called()
        self.assertIs(app.active_plan, plan)
        app.plan_map.set_root.assert_not_called()

    def test_storage_failure_preserves_memory_and_route(self):
        app = reset_fixture()
        plan = app.active_plan
        with patch("app.messagebox.askyesno", return_value=True), \
             patch("app.save_active_plan", side_effect=OSError("read only")), \
             patch("app.messagebox.showerror") as error:
            app.clear_current_plan()
        self.assertIs(app.active_plan, plan)
        app.plan_map.set_root.assert_not_called()
        error.assert_called_once()

    def test_late_worker_result_cannot_restore_cleared_route_or_consume_new_result(self):
        app = reset_fixture()
        old_queue = app.plan_result_queue
        app.plan_worker_busy = True
        with patch("app.messagebox.askyesno", return_value=True), patch("app.save_active_plan"):
            app.clear_current_plan()
        old_queue.put(("old", [], ""))
        app.plan_result_queue.put(("new", [], ""))
        app._poll_plan_result(7)
        self.assertIsNone(app.active_plan)
        self.assertIsNone(app.proposed_plan)
        self.assertEqual(app.plan_result_queue.qsize(), 1)
        app.root.after.assert_not_called()


if __name__ == "__main__":
    unittest.main()
