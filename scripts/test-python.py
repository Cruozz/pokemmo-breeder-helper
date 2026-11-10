"""Run every test, isolating Tcl/Tk GUI cases in fresh processes on Windows.

Tk's process-global interpreter/environment state can survive root.destroy().
Several GUI suites also temporarily replace environment variables. Process
isolation prevents that state from leaking across otherwise independent modules.
No failures are retried or ignored by this runner.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    paths = sorted((ROOT / "tests").glob("test_*.py"))
    gui = [p for p in paths if re.search(r"(?:import tkinter|from tkinter)", p.read_text(encoding="utf-8"))]
    shared = [p for p in paths if p not in gui]
    groups = [("shared", [str(p.relative_to(ROOT)) for p in shared])]
    report_dir = ROOT / ".runtime" / "test-results"
    report_dir.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "vendor") + os.pathsep + environment.get("PYTHONPATH", "")
    environment["PYTHONIOENCODING"] = "utf-8"
    collection = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q",
        *[str(p.relative_to(ROOT)) for p in gui]], cwd=ROOT, env=environment,
        text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if collection.returncode:
        print(collection.stdout)
        return collection.returncode
    nodes = [line.strip() for line in collection.stdout.splitlines() if line.startswith("tests/") and "::" in line]
    if not nodes:
        raise RuntimeError("GUI test collection unexpectedly returned no cases")
    groups.extend(("gui-" + str(i).zfill(3), [node]) for i, node in enumerate(nodes, 1))
    results = []
    for name, files in groups:
        command = [sys.executable, "-m", "pytest", *files,
                   "-q", "--tb=short", "--junitxml=" + str(report_dir / (name + ".xml"))]
        completed = subprocess.run(command, cwd=ROOT, env=environment, text=True, encoding="utf-8",
                                   errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = completed.stdout
        (report_dir / (name + ".log")).write_text(output, encoding="utf-8")
        summary = next((line for line in reversed(output.splitlines()) if re.search(r"\d+ (?:passed|failed|skipped|error)", line)), "No test summary")
        print(name + ": " + summary, flush=True)
        if completed.returncode:
            print(output, flush=True)
        passed = sum(int(n) for n in re.findall(r"(\d+) passed", summary))
        skipped = sum(int(n) for n in re.findall(r"(\d+) skipped", summary))
        subtests = sum(int(n) for n in re.findall(r"(\d+) subtests passed", summary))
        results.append(dict(group=name, cases=files, exit_code=completed.returncode, passed=passed, skipped=skipped, subtests=subtests))
    report = dict(groups=results, passed=sum(r["passed"] for r in results),
                  skipped=sum(r["skipped"] for r in results), subtests=sum(r["subtests"] for r in results),
                  ok=all(r["exit_code"] == 0 for r in results))
    (report_dir / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("FULL SUITE: " + json.dumps({k: v for k, v in report.items() if k != "groups"}), flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
