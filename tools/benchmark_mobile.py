"""Deterministic, synthetic workloads; never reads or writes a user's box."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
parser.add_argument("--count", type=int, default=0)
parser.add_argument("--profile", action="store_true")
parser.add_argument("--lucario", action="store_true")
parser.add_argument("--chain-source", type=Path, help="Optional baseline chain_planner.py for comparisons")
args = parser.parse_args()
sys.path.insert(0, str(args.source))
from models import Monster
if args.chain_source:
    core_spec = importlib.util.spec_from_file_location("chain_planner", args.chain_source)
    core = importlib.util.module_from_spec(core_spec)
    sys.modules["chain_planner"] = core
    core_spec.loader.exec_module(core)

spec = importlib.util.spec_from_file_location("mobile_benchmark", args.source / "android-app/app/src/main/python/mobile_bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
inventory = []
for index in range(args.count):
    stats = [None] * 6
    stats[index % 6] = 31
    if index % 3:
        stats[(index // 6 + index + 1) % 6] = 31
    species = ("索罗亚", "长毛狗", "晃晃斑", "小拉达", "咕咕", "百变怪")[index % 6]
    if args.lucario and index % 6 == 0:
        species = "路卡利欧"
    inventory.append(Monster(id=f"benchmark-{index}", species=species, gender="N" if species == "百变怪" else "F" if index % 4 < 2 else "M", ivs=stats).to_dict())
request = dict(species="索罗亚克", nature="天真", ivs=["31", "31", "31", "X", "31", "31"], allow_ditto=True, strategy="inventory")
if args.lucario:
    request.update(species="路卡利欧", nature="固执")
if args.profile:
    import cProfile
    profiler = cProfile.Profile()
    profiler.enable()
started = time.perf_counter()
result = json.loads(bridge.generate_plan(json.dumps(inventory), json.dumps(request)))
elapsed = time.perf_counter() - started
if args.profile:
    profiler.disable()
print(json.dumps(dict(count=args.count, seconds=round(elapsed, 3), ok=result["ok"],
                      steps=len((result.get("plan") or {}).get("steps", [])),
                      report_sha256=hashlib.sha256(result.get("report", "").encode()).hexdigest()), ensure_ascii=False), flush=True)
if args.profile:
    import pstats
    pstats.Stats(profiler).sort_stats("cumtime").print_stats(20)
