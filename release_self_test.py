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
        from parallel_guide import run_guide_self_test
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as guide_directory:
            checks["parallel_guide"] = run_guide_self_test(root, Path(guide_directory))
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
            live.tabs.select(live.market_page)
            live._tab_changed()
            from market_data import parse_snapshot, HistoryPoint
            market = live.market_workspace
            fixture_time = datetime.now(timezone.utc).isoformat()
            market.apply_snapshot(parse_snapshot({
                "items": [{"itemId": 5229, "price": 6000, "quantity": 5, "listings": 3, "at": fixture_time}],
                "pokemonQueries": [{"familyId": 92, "query": "any", "price": 1200, "quantity": 10,
                                    "listings": 10, "at": fixture_time}],
                "updatedAt": fixture_time, "sourceUpdatedAt": fixture_time,
            }))
            if [market.tabs.tab(tab, "text") for tab in market.tabs.tabs()] != ["道具市场", "宝可梦市场"]:
                raise RuntimeError("Packaged native market tabs are missing")
            item_values = market.pages["items"].tree.item("item:5229", "values")
            if item_values[0] != "不变之石" or item_values[2] != "6,000":
                raise RuntimeError("Packaged market catalogue or quotes did not render")
            market.show_history((HistoryPoint(now - 3600, 5000, 2), HistoryPoint(now, 6000, 3)))
            market.chart_kind.set("K线")
            market.redraw_chart()
            if not market.chart.find_all() or len(market.pages["pokemon"].rows) != 1:
                raise RuntimeError("Packaged native market history or Pokemon list did not render")
            checks["native_market"] = {"items": len(market.catalog["items"]), "species": len(market.catalog["monsters"]),
                                       "tabs": ["items", "pokemon"], "line_and_candles": True,
                                       "offline_fixture": True, "isolated_cache": True}
            live.auto_var.set(False)
            if live.automatic_kinds(live.cave_due_at, time.monotonic()) != ["cave"]:
                raise RuntimeError("Packaged cave schedule depends on Alpha auto-refresh")
            checks["live_information"] = {"pages": ["alpha", "cave", "market"], "offline_fixture": True,
                                           "isolated_cache": True, "default_interval_seconds": live.interval,
                                           "cave_schedule_beijing": [2, 8, 14, 20], "market_native": True}
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

    from route_view import BreedingRouteView, held_item
    from app import UI_COLORS
    text_root = tk.Tk()
    text_root.attributes("-alpha", 0)
    try:
        view = BreedingRouteView(text_root, colors=UI_COLORS, font_family="Microsoft YaHei",
                                 on_step_activate=lambda _number: None)
        view.pack(fill="both", expand=True)
        text_root.geometry("620x600")
        view.set_root(route)
        view.set_mode("text")
        text_root.update()
        view.text._draw()
        if len(view.text.steps) != len(plan.steps) or not view.text.canvas.find_withtag("text-sprite"):
            raise RuntimeError("Packaged text route or Pokemon sprites failed")
        node = view.text.steps[0].node
        if node.species_name != plan.steps[0].child.species or [held_item(parent) for parent in node.children] != [
            plan.steps[0].item_a or "无需道具", plan.steps[0].item_b or "无需道具"
        ]:
            raise RuntimeError("Packaged text route parent items or species names failed")
        view.set_mode("map")
        if view.map.node_count != 3:
            raise RuntimeError("Packaged route presentation switch failed")
        checks["route_presentations"] = {"modes": ["map", "text"], "sprites": True,
                                          "parent_items": True, "original_step_numbers": True}
    finally:
        text_root.destroy()

    from chain_planner import ChainState, SpeciesProfile, _forced_child
    parent = ChainState("伊布", "M", ("陆上",), 7, False, "", False, frozenset({"male"}), 0, 0, 0, 0)
    ditto = ChainState("百变怪", "N", (), 3, False, "", False, frozenset({"ditto"}), 0, 0, 0, 0)
    profile = SpeciesProfile("伊布", "伊布", ("陆上",), False, ("F", "M"))
    if _forced_child(parent, ditto, profile, "F", brace_a=2) is not None:
        raise RuntimeError("Packaged planner allowed 3V male + 2V Ditto gender conversion")
    from chain_planner import _maternal_conversion_candidates
    nature_parent = ChainState("伊布", "M", ("陆上",), 3, True, "固执", False,
                               frozenset({"nature-source"}), 0, 0, 0, 0)
    higher_ditto = ChainState("百变怪", "N", (), 7, False, "", False, frozenset({"higher-ditto"}), 0, 0, 0, 0)
    upgraded = _forced_child(nature_parent, higher_ditto, profile, "F", brace_b=2, everstone_a=True)
    if upgraded is None or upgraded.mask != 7 or not upgraded.has_nature or upgraded.gender != "F":
        raise RuntimeError("Packaged planner rejected a valid natured 2V + 3V Ditto maternal upgrade")
    converted = _maternal_conversion_candidates([nature_parent], [ditto], profile, 7, preserve_nature=True)
    if not converted or any(not state.has_nature or state.action.item_a != "不变之石" for state in converted):
        raise RuntimeError("Packaged maternal bootstrap did not preserve its target nature")
    upgraded = _maternal_conversion_candidates([nature_parent], [higher_ditto], profile, 7, preserve_nature=True)
    if not upgraded or any(state.mask != 7 or not state.has_nature for state in upgraded):
        raise RuntimeError("Packaged maternal bootstrap omitted a valid higher-tier Ditto upgrade")
    milotic_parent = ChainState("丑丑鱼", "M", ("水中1", "龙"), 40, False, "爽朗", True,
                               frozenset({"selftest-milotic"}), 0, 0, 0, 0)
    milotic_ditto = ChainState("百变怪", "N", (), 41, False, "认真", True,
                              frozenset({"selftest-milotic-ditto"}), 0, 0, 0, 0)
    milotic_profile = SpeciesProfile("丑丑鱼", "丑丑鱼", ("水中1", "龙"), False, ("F", "M"))
    if (_forced_child(milotic_parent, milotic_ditto, milotic_profile, "F", brace_b=0) is not None
            or _maternal_conversion_candidates([milotic_parent], [milotic_ditto], milotic_profile, 61)):
        raise RuntimeError("Packaged planner allowed random-nature 2V Milotic + 3V Ditto conversion")
    sample = []
    for key, name, gender, mask, nature in (
        ("selftest-adamant-ambipom", "双尾怪手", "M", 6, "固执"),
        ("selftest-ditto2", "百变怪", "N", 6, ""),
        ("selftest-ditto3", "百变怪", "N", 7, ""),
        ("selftest-donor3", "伊布", "M", 7, ""),
        ("selftest-donor4", "伊布", "M", 23, ""),
        ("selftest-donor5", "伊布", "M", 55, ""),
        ("selftest-weak-female", "长尾怪手", "F", 33, ""),
    ):
        sample.append(Monster(id=key, species=name, gender=gender, nature=nature, is_alpha=True,
                              ivs=[31 if mask & (1 << i) else 1 for i in range(6)]))
    report, routes = make_report_with_candidates(sample, "长尾怪手", "", "固执", "31/31/31/x/31/31", ["陆上"],
        target_alpha=True, allow_ditto=False, nature_strategy="chain", convert_maternal_with_ditto=True)
    if not routes:
        raise RuntimeError("Packaged natured maternal chain has no route: " + report)
    plan = build_execution_plan(routes[0])
    conversion = next((step for step in plan.steps if "selftest-ditto3" in (step.parent_a_id, step.parent_b_id)), None)
    if (conversion is None or conversion.child.nature != "固执" or conversion.child.gender != "F"
            or conversion.child.species != "长尾怪手" or conversion.child.ivs.count(31) != 3
            or routes[0].root.breeds != 3 or plan.steps[-1].child.nature != "固执"):
        raise RuntimeError("Packaged planner did not use the natured evolved inventory as its maternal seed")
    checks["ditto_conversion"] = {"lower_tier_conversion_rejected": True, "higher_tier_nature_upgrade": True,
                                  "random_nature_higher_tier_conversion_rejected": True,
                                  "maternal_everstone": True,
                                  "evolved_nature_seed": True, "synthetic_data": True}

    protected_sample = [
        Monster(id="selftest-attack-gengar", species="耿鬼", gender="M", nature="慎重",
                ivs=[31, 31, 13, 4, 18, 6]),
        Monster(id="selftest-attack-ditto", species="百变怪", gender="N", nature="爽朗",
                ivs=[19, 31, 0, 9, 3, 31]),
    ]
    before = [list(monster.ivs) for monster in protected_sample]
    report, routes = make_report_with_candidates(protected_sample, "耿鬼", "", "内敛",
        "31/x/31/31/31/31", [], allow_ditto=False, convert_maternal_with_ditto=True)
    protected_ids = {monster.id for monster in protected_sample}
    if not routes or any(route.root.used_ids & protected_ids for route in routes) or "完整素材保护" not in report:
        raise RuntimeError("Packaged planner consumed inventory perfect IVs on a target X stat")
    if before != [monster.ivs for monster in protected_sample]:
        raise RuntimeError("Packaged material protection changed inventory IVs")
    report, attack_routes = make_report_with_candidates(protected_sample, "耿鬼", "", "",
        "31/31/x/x/x/31", [], allow_ditto=False, convert_maternal_with_ditto=True)
    if not attack_routes or attack_routes[0].root.used_ids != frozenset(protected_ids):
        raise RuntimeError("Packaged planner could not reuse protected materials for an attack target")
    checks["iv_material_protection"] = {"perfect_ivs_on_x_stats_excluded": True,
                                        "inventory_preserved": True, "later_attack_target": True,
                                        "synthetic_data": True}

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
    from breeding_cost import PriceBook, material_record
    from cost_views import CostDialog
    with tempfile.TemporaryDirectory() as cost_directory:
        mother = Monster(id="cost-mother", species="鲤鱼王", gender="F",
                         ivs=[31, 1, 1, 1, 1, 1], egg_groups=["水中2", "龙"])
        father = Monster(id="cost-father", species="鲤鱼王", gender="M",
                         ivs=[1, 31, 1, 1, 1, 1], egg_groups=["水中2", "龙"])
        book = PriceBook()
        for material in (mother, father):
            book.prices[material_record(material)["key"]] = 3000
        _text, cost_candidates = make_report_with_candidates(
            [mother, father], "鲤鱼王", "", "", "31/31/x/x/x/x", ["水中2", "龙"],
            strategy="cost", allow_ditto=False, cost_pricing=book,
        )
        if not cost_candidates or cost_candidates[0].cost_report().total_known != 26000:
            raise RuntimeError("Packaged breeding cost accounting failed")
        from planner_worker import PlannerJob
        request = ([mother, father], "鲤鱼王", "", "", "31/31/x/x/x/x", ["水中2", "龙"],
                   False, False, "cost", "late", False, frozenset(), "smart", False, (), False, frozenset(), book)
        job = PlannerJob(request)
        try:
            deadline = time.monotonic() + 15
            result = job.poll()
            while result is None and time.monotonic() < deadline:
                time.sleep(.02)
                result = job.poll()
            if result is None or result[2] or not result[1] or result[1][0].cost_report().total_known != 26000:
                raise RuntimeError("Packaged independent planner process failed")
            checks["planner_process"] = {"roundtrip": True, "total": 26000, "isolated_data": True}
        finally:
            job.release(cancel=True)
        from breeding_cost import load_price_book
        cash_book = load_price_book(Path(cost_directory) / "new-prices.json")
        if cash_book.include_inventory_value:
            raise RuntimeError("New pricing settings must exclude owned inventory")
        cash_request = (*request[:-1], cash_book, 1)
        job = PlannerJob(cash_request)
        try:
            deadline = time.monotonic() + 15
            cash_result = job.poll()
            while cash_result is None and time.monotonic() < deadline:
                time.sleep(.02)
                cash_result = job.poll()
            if cash_result is None or cash_result[2] or cash_result[1][0].cost_report().total_known != 20000:
                raise RuntimeError("Packaged cash-only planning or purchase limit IPC failed")
            checks["cash_planning"] = {"total": 20000, "inventory_valued": False, "purchase_limit": 1}
        finally:
            job.release(cancel=True)
        for name, identifier in (("催眠'超",96), ("扭拉冰恶",215), ("玛狂拉恶冰",461), ("蜈蛤王虫毒",545), ("娱王毒虫",545), ("玛拉冰恶",461)):
            repaired, confident, _score = species.resolve_ocr_name(name)
            if repaired is None or repaired.id != identifier or not confident:
                raise RuntimeError("Packaged reviewed species OCR correction failed")
        checks["reviewed_ocr_names"] = {"species": 4}
        cost_root = tk.Tk()
        cost_root.withdraw()
        try:
            dialog = CostDialog(cost_root, book=book, path=Path(cost_directory) / "prices.json",
                                inventory=[mother, father], candidates=cost_candidates)
            cost_root.update_idletasks()
            if "总消耗价值" not in dialog.summary_var.get() or len(dialog.tabs.tabs()) != 3:
                raise RuntimeError("Packaged cost interface failed")
            dialog.save()
            if str(dialog.total_label.cget("foreground")) != "#1d4ed8" or dialog.total_var.get() != "26,000":
                raise RuntimeError("Packaged cost amount emphasis failed")
            dialog.close()
            from market_data import parse_snapshot
            alpha_material = Monster(id="cost-alpha", species="美纳斯", gender="F", is_alpha=True,
                                     ivs=[31, 1, 31, 1, 1, 1], nature="内敛", egg_groups=["水中1", "龙"])
            fixture_at = datetime.now(timezone.utc).isoformat()
            quote_book = PriceBook(snapshot=parse_snapshot(dict(items=[], pokemonQueries=[
                dict(familyId=349, query="alpha", price=50000, at=fixture_at),
                dict(familyId=0, query="egg:12:iv_hp:female", price=4000, at=fixture_at),
            ])))
            if quote_book.material_quote(material_record(alpha_material))[0] != 50000 or quote_book.material_quote(material_record(mother))[0] != 4000:
                raise RuntimeError("Packaged automatic material valuation failed")
            checks["breeding_cost"] = {"total": 26000, "cash": 20000, "native_ui": True,
                                       "automatic_alpha_2v": True, "automatic_egg_1v": True, "isolated_data": True}
        finally:
            cost_root.destroy()
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
