"""Local, cancellable planning process. Input and output never leave this PC."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

MAX_MESSAGE = 64 * 1024 * 1024
_recent_result = None


def encode_request(request):
    values = list(request)
    values[0] = [monster.to_dict() for monster in values[0]]
    values[11] = sorted(values[11])
    values[14] = list(values[14])
    values[16] = sorted(values[16])
    book = values[17]
    values[17] = book.to_dict()
    return {"schema": 1, "args": values, "market": book.snapshot.payload if book.snapshot else None}


def calculate(payload):
    from models import Monster
    from breeding_cost import PriceBook
    from market_data import parse_snapshot
    from planner import make_report_with_candidates
    if payload.get("schema") != 1 or len(payload.get("args", [])) not in {18, 19}:
        raise ValueError("规划输入格式无效。")
    values = list(payload["args"])
    values[0] = [Monster.from_dict(row) for row in values[0]]
    values[11], values[16] = frozenset(values[11]), frozenset(values[16])
    values[17] = PriceBook(values[17], parse_snapshot(payload["market"]) if payload.get("market") else None)
    report, candidates = make_report_with_candidates(*values)
    return {"schema": 1, "report": report, "candidates": [candidate.to_dict() for candidate in candidates],
            "materials": candidates[0].cost_materials if candidates else [], "error": ""}


def decode_result(value):
    from chain_planner import ChainCandidate
    if value.get("schema") != 1:
        raise ValueError("规划结果格式无效。")
    candidates = [ChainCandidate.from_dict(row) for row in value.get("candidates", [])]
    for candidate in candidates:
        candidate.cost_materials = value.get("materials", [])
    return value.get("report", ""), candidates, value.get("error", "")


def read_message(path):
    if path.stat().st_size > MAX_MESSAGE:
        raise ValueError("规划数据过大。")
    return json.loads(path.read_text(encoding="utf-8"))


def run_worker(input_path, output_path):
    try:
        result = calculate(read_message(Path(input_path)))
    except Exception as error:
        result = {"schema": 1, "error": str(error), "candidates": [], "report": ""}
    output = Path(output_path)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(output)
    return 0


class PlannerJob:
    def __init__(self, request):
        self.started_at = time.monotonic()
        text = json.dumps(encode_request(request), ensure_ascii=False, sort_keys=True, allow_nan=False)
        self.key = hashlib.sha256(text.encode()).hexdigest()
        self.process = None
        self.directory = None
        self.released = False
        self.raw_result = None
        recent = _recent_result
        if recent and recent[0] == self.key and time.monotonic() - recent[1] <= 60 and _prices_current(recent[2]):
            self.raw_result = copy.deepcopy(recent[2])
            return
        self.directory = tempfile.TemporaryDirectory(prefix="pokemmo-plan-")
        folder = Path(self.directory.name)
        self.output_path = folder / "result.json"
        input_path = folder / "input.json"
        input_path.write_text(text, encoding="utf-8")
        command = ([sys.executable, "--plan-worker"] if getattr(sys, "frozen", False)
                   else [sys.executable, str(Path(__file__).resolve())])
        try:
            self.process = subprocess.Popen(command + [str(input_path), str(self.output_path)],
                                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0)
                                                           | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)))
        except Exception:
            self.directory.cleanup()
            raise

    def poll(self):
        global _recent_result
        if self.raw_result is not None:
            return decode_result(self.raw_result)
        if self.output_path.exists():
            self.raw_result = read_message(self.output_path)
            if not self.raw_result.get("error"):
                _recent_result = (self.key, time.monotonic(), copy.deepcopy(self.raw_result))
            return decode_result(self.raw_result)
        code = self.process.poll()
        if code is not None:
            return "", [], f"规划进程提前退出（{code}），请重新计算。"
        return None

    def release(self, *, cancel=False):
        if self.released:
            return
        self.released = True
        process, directory = self.process, self.directory
        if process is None:
            return
        if cancel and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
        def cleanup():
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                    process.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            finally:
                try:
                    directory.cleanup()
                except OSError:
                    pass
        # A short-lived reaper keeps only local temporary files; it must finish
        # even when the main window closes immediately after cancellation.
        threading.Thread(target=cleanup, name="planner-cleanup", daemon=False).start()


def _prices_current(result):
    now = time.time()
    for candidate in result.get("candidates", []):
        prices = candidate.get("cost_pricing", {})
        quotes = list(prices.get("auto_materials", {}).values())
        if prices.get("auto_everstone"):
            quotes.append(prices["auto_everstone"])
        if any(now - quote["at"] > 86400 for quote in quotes):
            return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    args = parser.parse_args()
    return run_worker(args.input, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
