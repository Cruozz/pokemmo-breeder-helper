"""Checks run inside the shipped EXE, without game access or inventory writes."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time
import traceback


def run_checks() -> dict[str, object]:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
    import tkinter as tk
    from tkinter import ttk

    from execution import build_execution_plan
    from models import Monster
    from ocr_engine import OCRProcessor
    from planner import make_report_with_candidates
    from reference_data import get_reference_database
    from species_data import get_species_database, resource_path

    checks: dict[str, object] = {}
    species = get_species_database()
    reference = get_reference_database()
    if len(species.records) != 649:
        raise RuntimeError("Bundled species database is incomplete")
    route_count = sum(len(routes) for moves in reference.egg_moves_by_species.values() for routes in moves.values())
    if route_count != 11145:
        raise RuntimeError("Bundled egg-move database is incomplete")
    checks["data"] = {"species": len(species.records), "egg_move_routes": route_count}

    for name in ("app-icon.png", "pokemon_atlas.png", "item_atlas.png"):
        with Image.open(resource_path("assets", name)) as image:
            image.verify()
    root = tk.Tk()
    root.withdraw()
    try:
        ttk.Label(root, text="runtime check")
        with Image.open(resource_path("assets", "app-icon.png")) as image:
            icon = ImageTk.PhotoImage(image, master=root)
        root.iconphoto(True, icon)
        root.update_idletasks()
        checks["tkinter"] = {"version": str(root.tk.call("info", "patchlevel")), "assets": "ok"}
    finally:
        root.destroy()

    inventory = [
        Monster(id="self-test-mother", species="伊布", gender="F", ivs=[31, 1, 1, 1, 1, 1]),
        Monster(id="self-test-father", species="图图犬", gender="M", ivs=[31, 1, 1, 1, 1, 1], moves=["祈愿"]),
    ]
    report, candidates = make_report_with_candidates(
        inventory, "伊布", "F", "", "31/x/x/x/x/x", [], allow_ditto=False, target_moves=["祈愿"],
    )
    if not candidates or candidates[0].root.purchases != 0 or candidates[0].root.breeds != 1:
        raise RuntimeError("Packaged egg-move planner failed: " + report)
    plan = build_execution_plan(candidates[0])
    if len(plan.steps) != 1 or plan.steps[0].child.moves != ["祈愿"]:
        raise RuntimeError("Packaged execution planner lost the inherited move")
    checks["egg_moves"] = {"breeds": 1, "purchases": 0, "moves": ["祈愿"]}

    from execution_view import execution_map
    from route_roles import candidate_route_roles
    roles = candidate_route_roles(candidates[0])
    if set(roles.values()) != {"maternal", "egg_move"}:
        raise RuntimeError("Packaged route classification failed")
    route = execution_map(plan, inventory, set(), species)
    if route.route_role != "maternal" or "egg_move" not in {child.route_role for child in route.children}:
        raise RuntimeError("Packaged execution route colors failed")
    checks["route_colors"] = "candidate and execution roles agree"

    from chain_planner import ChainState, SpeciesProfile, _forced_child
    parent = ChainState("伊布", "M", ("陆上",), 7, False, "", False, frozenset({"male"}), 0, 0, 0, 0)
    ditto = ChainState("百变怪", "N", (), 3, False, "", False, frozenset({"ditto"}), 0, 0, 0, 0)
    profile = SpeciesProfile("伊布", "伊布", ("陆上",), False, ("F", "M"))
    if _forced_child(parent, ditto, profile, "F", brace_a=2) is not None:
        raise RuntimeError("Packaged planner allowed 3V male + 2V Ditto gender conversion")
    checks["ditto_conversion"] = "lower-tier gender conversion rejected"

    image = Image.new("RGB", (700, 160), "white")
    ImageDraw.Draw(image).text((24, 45), "POKEMMO 12345", fill="black", font=ImageFont.load_default(size=48))
    items = OCRProcessor(performance_profile="low").recognize(image)
    recognized = " ".join(item.text for item in items)
    if "12345" not in recognized:
        raise RuntimeError("OCR inference did not recognize the synthetic test number: " + recognized)
    checks["ocr"] = {"text": recognized, "synthetic_image": True}
    return checks


def run_self_test(report_path: str, version: str) -> int:
    started = time.perf_counter()
    result: dict[str, object] = {
        "ok": False, "version": version, "frozen": bool(getattr(sys, "frozen", False)),
        "python": ".".join(str(value) for value in sys.version_info[:3]),
    }
    try:
        result["checks"] = run_checks()
        result["ok"] = True
    except Exception:
        # Failures are local diagnostics, never successful release evidence.
        result["error"] = traceback.format_exc()
    result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    destination = Path(report_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result["ok"] else 1
