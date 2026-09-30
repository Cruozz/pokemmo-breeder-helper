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

    for name in ("app-icon.png", "pokemon_atlas.png", "pokemon_shiny_atlas.png", "item_atlas.png"):
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
        from guide_data import SEASONS, STAT_LABELS, ev_values, get_guide_database
        from guide_views import PAGE_TITLES, QueryPage
        guide = get_guide_database()
        if len(guide.species) != 649 or len(guide.hordes) < 4000:
            raise RuntimeError("Bundled offline guide is incomplete")
        for mode in PAGE_TITLES:
            page = QueryPage(root, guide, mode, lambda *_args: None)
            root.update_idletasks()
            if not page.table.rows:
                raise RuntimeError(f"Native query page has no results: {mode}")
            if mode == "hordes":
                ids = [record.species_id for record, _values in page.table.rows]
                if len(ids) != len(set(ids)) or sum(len(record.encounters) for record, _values in page.table.rows) != len(guide.hordes):
                    raise RuntimeError("Packaged horde grouping lost or duplicated encounters")
                checks["grouped_hordes"] = {"species": len(ids), "encounters": len(guide.hordes)}
            if mode == "effort":
                pools = {}
                for row in guide.hordes:
                    for season in SEASONS[1:] if row.season == "任意" else (row.season,):
                        for period, _ in row.chances:
                            pools.setdefault((row.point_key, season, period), set()).add(row.species_id)
                counts = {}
                for stat, label in STAT_LABELS.items():
                    page.variables["stat"].set(label)
                    page.refresh()
                    ids = [group.species_id for group, _values in page.table.rows]
                    if not ids or len(ids) != len(set(ids)):
                        raise RuntimeError("Packaged effort guide repeats species")
                    for group, values in page.table.rows:
                        yields = ev_values(guide.by_id[group.species_id])
                        if values[1] != "纯点" or not yields[stat] or sum(value > 0 for value in yields.values()) != 1:
                            raise RuntimeError("Packaged effort guide contains mixed EV yields or lacks pure labels")
                        for row in group.encounters:
                            for season in SEASONS[1:] if row.season == "任意" else (row.season,):
                                for period, _ in row.chances:
                                    members = pools[row.point_key, season, period]
                                    if {key for identifier in members for key, value in ev_values(guide.by_id[identifier]).items() if value} != {stat}:
                                        raise RuntimeError("Packaged effort guide contains a mixed EV point")
                        page.show_details(group)
                        if "纯点" not in page.detail_title.get() or "整群基础值：" not in page.details["base"].get("1.0", "end"):
                            raise RuntimeError("Packaged effort guide omits grouped location yields")
                    counts[label] = len(ids)
                checks["pure_effort_spots"] = {"species_per_stat": counts, "season_time_pools_checked": True}
            if mode == "pokedex":
                if len(page.table.tree.get_children()) != 649 or page.table.next_button.winfo_manager():
                    raise RuntimeError("Packaged Pokedex still paginates species")
                checks["pokedex_all_rows"] = 649
                page.show_details(guide.by_id[25])
                portrait = page.portrait
                normal = portrait.photo
                portrait.button.invoke()
                if not portrait.shiny or portrait.photo is None or portrait.photo is normal or portrait.error:
                    raise RuntimeError("Packaged shiny portrait toggle failed")
                portrait.button.invoke()
                if portrait.shiny or portrait.photo is not normal:
                    raise RuntimeError("Packaged normal portrait toggle failed")
                for species_id in range(1, 650):
                    portrait.atlas.crop(species_id)
                    portrait.atlas.crop(species_id, True)
                checks["pokedex_portraits"] = {"species": 649, "variants": 2, "toggle": "normal-shiny-normal"}
            page.destroy()
        checks["native_guide"] = {"species": len(guide.species), "hordes": len(guide.hordes), "pages": list(PAGE_TITLES)}
        import tempfile
        from datetime import datetime, timezone
        from live_data import AlphaReport, CaveRotation
        from live_views import LiveWorkspace
        with tempfile.TemporaryDirectory() as live_directory:
            live = LiveWorkspace(root, cache_path=Path(live_directory) / "live.json", autostart=False)
            now = time.time()
            date = datetime.now(timezone.utc)
            alpha = AlphaReport("Salamence", 373, "Hoenn", "Sky Pillar", now - 60, now + 4400)
            cave = CaveRotation(date.strftime("%Y%m%d") + "-" + str(date.hour // 6), "Bug",
                                ("Venomoth", "Ferroseed", "Duosion", "Parasect", "Staryu"),
                                ("Ninjask", "Larvesta"), ("Shellos", "Pinsir"))
            live._apply_result("alpha", alpha, None)
            live._apply_result("cave", cave, None)
            root.update_idletasks()
            if live.alpha_name.get() != species.get_by_id(373).display_name or live.gem_type.get() != "宝石属性：虫":
                raise RuntimeError("Packaged live information failed to render")
            if not live.alpha_portrait.photo or len(live.cave_slots["singles"]) != 5:
                raise RuntimeError("Packaged live portraits or encounter slots are missing")
            if live.market_page.winfo_children():
                raise RuntimeError("Packaged market placeholder should be empty")
            live.auto_var.set(False)
            if live.automatic_kinds(live.cave_due_at, time.monotonic()) != ["cave"]:
                raise RuntimeError("Packaged cave schedule depends on Alpha auto-refresh")
            checks["live_information"] = {"pages": ["alpha", "cave", "market"], "offline_fixture": True,
                                           "isolated_cache": True, "default_interval_seconds": live.interval,
                                           "cave_schedule_beijing": [2, 8, 14, 20], "market_empty": True}
            live.destroy()
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
    if set(roles.values()) != {"maternal", "iv"}:
        raise RuntimeError("Packaged route classification failed")
    route = execution_map(plan, inventory, set(), species)
    if route.route_role != "maternal" or route.route_moves != ("祈愿",) or not any(child.route_moves for child in route.children):
        raise RuntimeError("Packaged execution route colors failed")
    checks["route_colors"] = "candidate and execution roles agree"

    from chain_planner import ChainState, SpeciesProfile, _forced_child
    parent = ChainState("伊布", "M", ("陆上",), 7, False, "", False, frozenset({"male"}), 0, 0, 0, 0)
    ditto = ChainState("百变怪", "N", (), 3, False, "", False, frozenset({"ditto"}), 0, 0, 0, 0)
    profile = SpeciesProfile("伊布", "伊布", ("陆上",), False, ("F", "M"))
    if _forced_child(parent, ditto, profile, "F", brace_a=2) is not None:
        raise RuntimeError("Packaged planner allowed 3V male + 2V Ditto gender conversion")
    checks["ditto_conversion"] = "lower-tier gender conversion rejected"

    from account_order_dialog import AccountOrderDialog
    from inventory_order import inventory_in_display_order, sorted_inventory_ids
    display_inventory = [
        Monster(id="two9", account="TwoBit", page="1", slot="9"),
        Monster(id="one10", account="OneBit", page="1", slot="10"),
        Monster(id="one9", account="OneBit", page="1", slot="9"),
    ]
    original_ids = [item.id for item in display_inventory]
    display_ids = sorted_inventory_ids(display_inventory, ["OneBit", "TwoBit"])
    if display_ids != ["one9", "one10", "two9"] or [item.id for item in display_inventory] != original_ids:
        raise RuntimeError("Packaged inventory sort changed account grouping or planner input")
    display_inventory.append(Monster(id="new", account="OneBit", page="1", slot="1"))
    if [item.id for item in inventory_in_display_order(display_inventory, display_ids)] != [*display_ids, "new"]:
        raise RuntimeError("Packaged manual sort automatically repositioned a new record")
    checks["inventory_order"] = {"account_grouping": "ok", "new_records_append": True, "dialog": AccountOrderDialog.__name__}

    image = Image.new("RGB", (700, 160), "white")
    ImageDraw.Draw(image).text((24, 45), "POKEMMO 12345", fill="black", font=ImageFont.load_default(size=48))
    items = OCRProcessor(performance_profile="low").recognize(image)
    recognized = " ".join(item.text for item in items)
    if "12345" not in recognized:
        raise RuntimeError("OCR inference did not recognize the synthetic test number: " + recognized)
    checks["ocr"] = {"text": recognized, "synthetic_image": True}
    import os
    import tempfile
    from unittest.mock import patch
    from app import App
    from storage import delete_accounts_and_inventory, load_accounts, load_inventory, save_accounts, save_inventory, undo_last_inventory_deletion

    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": directory}):
        sample = [Monster(id="delete-test-a", account="DeleteTest", species="皮卡丘"),
                  Monster(id="delete-test-b", account="KeepTest", species="伊布")]
        save_accounts(["DeleteTest", "KeepTest", "EmptyTest"])
        save_inventory(sample)
        delete_accounts_and_inventory(["DeleteTest", "EmptyTest"], ["KeepTest"], {"delete-test-a"})
        if load_accounts() != ["KeepTest"] or [record.id for record in load_inventory()] != ["delete-test-b"]:
            raise RuntimeError("Packaged account deletion failed")
        undo_last_inventory_deletion()
        if "EmptyTest" not in load_accounts() or len(load_inventory()) != 2:
            raise RuntimeError("Packaged account undo failed")
        root = tk.Tk()
        root.withdraw()
        try:
            app = App(root)
            app.target_species_var.set("皮卡丘")
            app.target_nature_var.set("固执")
            for variable in app.target_iv_vars:
                variable.set("31")
            app._clear_plan_state(reset_targets=True)
            if app.target_species_var.get() or app.target_nature_var.get() or any(variable.get() != "X" for variable in app.target_iv_vars):
                raise RuntimeError("Packaged target reset failed")
        finally:
            for callback in root.tk.call("after", "info"):
                root.after_cancel(callback)
            root.destroy()
        from window_memory import WindowMemory
        window_path = Path(directory) / "window-test.json"
        root = tk.Tk()
        try:
            memory = WindowMemory(root, window_path)
            root.geometry("800x650+100+70")
            root.update()
            memory.save()
        finally:
            root.destroy()
        root = tk.Tk()
        try:
            WindowMemory(root, window_path)
            root.update()
            if root.geometry() != "800x650+100+70":
                raise RuntimeError("Packaged main window did not restore its position and size")
            checks["window_memory"] = {"reopen_geometry": root.geometry(), "isolated_settings": True}
        finally:
            root.destroy()
    checks["reset_account_delete"] = {"target_reset": True, "delete_and_undo": True, "isolated_data": True}
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
