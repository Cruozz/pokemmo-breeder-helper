from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import APP_TITLE, BATCH_CHANGE_DIFFERENCE, BATCH_NEXT_COUNTDOWN_SECONDS, App
from chain_planner import ChainCandidate, ChainState
from execution import ExecutionPlan, ExecutionStep
from mind_map import MindMapNode
from models import Monster, normalize_gender
from PIL import Image
from species_data import get_species_database


class StubVariable:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def set(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value


class StubButton:
    def __init__(self) -> None:
        self.options: dict[str, str] = {}

    def configure(self, **kwargs) -> None:
        self.options.update(kwargs)


class StubRoot:
    def __init__(self) -> None:
        self.after_calls: list[tuple[int, object]] = []
        self.cancelled: list[object] = []
        self.focused = False

    def after(self, delay: int, callback):
        self.after_calls.append((delay, callback))
        return f"after-{len(self.after_calls)}"

    def after_cancel(self, after_id) -> None:
        self.cancelled.append(after_id)

    def lift(self) -> None:
        self.focused = True

    def focus_force(self) -> None:
        self.focused = True


class StubPopup:
    def __init__(self) -> None:
        self.bindings: dict[str, object] = {}
        self.destroyed = False

    def bind(self, sequence: str, callback) -> None:
        self.bindings[sequence] = callback

    def winfo_exists(self) -> bool:
        return not self.destroyed

    def destroy(self) -> None:
        self.destroyed = True


class StubGridWidget:
    def __init__(self) -> None:
        self.grid_options: dict[str, object] | None = None
        self.forgotten = False

    def grid_forget(self) -> None:
        self.forgotten = True
        self.grid_options = None

    def grid(self, **kwargs) -> None:
        self.forgotten = False
        self.grid_options = kwargs


class StubGridFrame:
    def __init__(self) -> None:
        self.column_weights: dict[int, int] = {}

    def columnconfigure(self, column: int, *, weight: int) -> None:
        self.column_weights[column] = weight


class StubPackWidget:
    def __init__(self, packed: bool = True) -> None:
        self.packed = packed
        self.options: dict[str, object] = {}

    def pack(self, **kwargs) -> None:
        self.packed = True
        self.options.update(kwargs)

    def pack_forget(self) -> None:
        self.packed = False

    def winfo_manager(self) -> str:
        return "pack" if self.packed else ""

    def configure(self, **kwargs) -> None:
        self.options.update(kwargs)


class AppInventoryFlowTests(unittest.TestCase):
    @staticmethod
    def _stage_candidate(phase: str) -> ChainCandidate:
        root = ChainState(
            species="陆上组素材",
            gender="F" if phase == "gamble_lower" else "M",
            egg_groups=("怪兽", "植物"),
            mask=0b00111,
            has_nature=False,
            nature="",
            is_alpha=False,
            used_ids=frozenset(),
            generation=0,
            breeds=0,
            braces=0,
            everstones=0,
        )
        return ChainCandidate(
            root=root,
            target_ivs=[31, 31, 31, None, 31, 31],
            target_nature="固执",
            target_gender="",
            target_species="暴雪王",
            offspring_species="雪笠怪",
            nature_strategy="late",
            nature_phase=phase,
            nature_attempt_level=3 if phase == "gamble_lower" else 4,
            nature_target_key="abomasnow-adamant-5v",
        )

    @staticmethod
    def _failed_stage_monster(
        identifier: str,
        role: str,
        level: int,
        gender: str,
        ivs: list[int | None],
    ) -> Monster:
        return Monster(
            id=identifier,
            species="雪笠怪" if role == "maternal" else "同组素材",
            gender=gender,
            nature="淘气",
            ivs=ivs,
            egg_groups=["怪兽", "植物"],
            breeding_target_key="abomasnow-adamant-5v",
            breeding_role=role,
            nature_attempt_level=level,
            nature_attempt_result="miss",
        )

    def test_gamble_upper_map_keeps_failed_five_v_mother_beside_current_route(self) -> None:
        app = App.__new__(App)
        app.inventory = [
            self._failed_stage_monster(
                "body-5v",
                "maternal",
                5,
                "F",
                [31, 31, 31, 7, 31, 31],
            )
        ]
        current = MindMapNode(key="current-4v", title="主动赌4V性格手")

        wrapped = App._wrap_staged_nature_context(
            app,
            self._stage_candidate("gamble_upper"),
            current,
            map_key_prefix="plan",
            species_sprite_id=lambda _species: 1,
        )

        self.assertIn("5V 固执", wrapped.title)
        self.assertEqual(wrapped.children[1], current)
        self.assertIn("已保留5V母体", wrapped.children[0].title)
        self.assertEqual(wrapped.children[0].nature_text, "爆性格：否")

    def test_gamble_lower_map_nests_failed_four_v_hand_and_failed_five_v_mother(self) -> None:
        app = App.__new__(App)
        app.inventory = [
            self._failed_stage_monster(
                "body-5v",
                "maternal",
                5,
                "F",
                [31, 31, 31, 7, 31, 31],
            ),
            self._failed_stage_monster(
                "hand-4v",
                "nature_hand",
                4,
                "M",
                [31, 31, 31, 9, 31, 12],
            ),
        ]
        current = MindMapNode(key="current-3v", title="主动赌3V性格手")

        wrapped = App._wrap_staged_nature_context(
            app,
            self._stage_candidate("gamble_lower"),
            current,
            map_key_prefix="plan",
            species_sprite_id=lambda _species: 1,
        )

        self.assertIn("5V 固执", wrapped.title)
        upper_preview = wrapped.children[1]
        self.assertIn("4V 固执", upper_preview.title)
        self.assertIn("已保留4V性格手", upper_preview.children[0].title)
        self.assertEqual(upper_preview.children[1], current)

    def test_target_details_button_can_collapse_and_expand_the_same_panel(self) -> None:
        app = App.__new__(App)
        app.planner_form = StubPackWidget()
        app.plan_status_label = StubPackWidget()
        app.plan_route_summary = StubPackWidget()
        app.planner_collapsed_bar = StubPackWidget()
        app.planner_actions = StubPackWidget()
        app.plan_map = StubPackWidget()
        app.planner_details_toggle_button = StubPackWidget()
        app.planner_details_collapsed = False

        App._set_planner_details_collapsed(app, True)

        self.assertFalse(app.planner_form.packed)
        self.assertFalse(app.plan_status_label.packed)
        self.assertFalse(app.plan_route_summary.packed)
        self.assertTrue(app.planner_collapsed_bar.packed)
        self.assertEqual(
            app.planner_details_toggle_button.options["text"],
            "修改目标与查看说明",
        )

        App._toggle_planner_details(app)

        self.assertTrue(app.planner_form.packed)
        self.assertTrue(app.plan_status_label.packed)
        self.assertTrue(app.plan_route_summary.packed)
        self.assertEqual(
            app.planner_details_toggle_button.options["text"],
            "收起目标与说明",
        )

    def test_undo_last_plan_exclusion_restores_only_most_recent_material(self) -> None:
        first = Monster(id="first", species="长毛狗")
        second = Monster(id="second", species="晃晃斑")
        app = App.__new__(App)
        app.plan_worker_busy = False
        app.inventory = [first, second]
        app.plan_excluded_ids = {first.id, second.id}
        app.plan_exclusion_history = [first.id, second.id]
        app.proposed_plan = object()
        app.plan_status_var = StubVariable()
        updated: list[bool] = []
        generated: list[bool] = []
        app._update_plan_exclusion_ui = lambda: updated.append(True)
        app.generate_plan = lambda: generated.append(True)

        App.undo_last_plan_exclusion(app)

        self.assertEqual(app.plan_excluded_ids, {first.id})
        self.assertEqual(app.plan_exclusion_history, [first.id])
        self.assertIsNone(app.proposed_plan)
        self.assertIn("晃晃斑", app.plan_status_var.get())
        self.assertEqual(updated, [True])
        self.assertEqual(generated, [True])

    def test_purchase_step_can_be_activated_without_ocr_import(self) -> None:
        step = ExecutionStep(
            number=1,
            parent_a_id="buy:1:拉鲁拉丝:F:0:plain",
            parent_b_id="buy:2:人型组兼容雄性:M:1:plain",
            parent_a_label="交易行母体",
            parent_b_label="交易行父本",
            child=Monster(id="child", species="拉鲁拉丝", gender="F"),
        )
        plan = ExecutionPlan(id="purchase-plan", target_species="拉鲁拉丝", steps=[step])
        app = App.__new__(App)
        app.active_plan = plan
        app.proposed_plan = plan
        app.selected_plan_step_number = None
        completed: list[int] = []
        app.complete_next_step = lambda selected: completed.append(selected.number)

        with patch("app.messagebox.showwarning") as warning:
            result = App._activate_plan_step_number(app, 1)

        self.assertEqual(result, "break")
        self.assertEqual(completed, [1])
        warning.assert_not_called()

    def test_terminal_product_is_consumed_without_being_added_to_material_inventory(self) -> None:
        step = ExecutionStep(
            number=1,
            parent_a_id="mother",
            parent_b_id="father",
            parent_a_label="库存母体",
            parent_b_label="库存父本",
            child=Monster(id="finished", species="雪笠怪", gender="F", ivs=[31, 31, 31, None, 31, 31]),
            planned_gender="F",
        )
        plan = ExecutionPlan(id="finished-plan", target_species="暴雪王", steps=[step])
        app = App.__new__(App)
        app.active_plan = plan
        app.plan_candidate_cache = {}
        app.species_db = SimpleNamespace(get=lambda *_args, **_kwargs: None)
        app.selected_plan_step_number = None
        app.status_var = StubVariable()
        app.inventory = []
        app.refresh_inventory_tree = lambda: None
        app.refresh_plan_status = lambda: None

        with (
            patch("app.messagebox.askyesno", return_value=True),
            patch("app.messagebox.showinfo") as showinfo,
            patch("app.consume_parents_and_add_child") as consume,
            patch("app.save_active_plan"),
            patch("app.load_inventory", return_value=[]),
        ):
            App.complete_next_step(app, step)

        self.assertTrue(step.completed)
        self.assertFalse(consume.call_args.kwargs["add_child_to_inventory"])
        self.assertIn("未写入素材库存", app.status_var.get())
        self.assertIn("未写入素材库存", showinfo.call_args.args[1])

    def test_narrow_inventory_toolbar_wraps_all_actions_instead_of_hiding_them(self) -> None:
        app = App.__new__(App)
        app.inventory_action_bar = StubGridFrame()
        app._inventory_action_layout = ""
        widget_names = (
            "inventory_refresh_button",
            "inventory_select_all_button",
            "inventory_duplicate_button",
            "inventory_export_button",
            "inventory_import_button",
            "inventory_undo_button",
            "inventory_summary_label",
            "inventory_selection_label",
            "inventory_delete_button",
        )
        for name in widget_names:
            setattr(app, name, StubGridWidget())

        App._apply_inventory_action_layout(app, "narrow")

        rows = {getattr(app, name).grid_options["row"] for name in widget_names}
        self.assertEqual(rows, {0, 1, 2})
        self.assertTrue(all(getattr(app, name).grid_options is not None for name in widget_names))

    def test_in_progress_marker_matches_same_parent_pair_after_local_replan(self) -> None:
        original = ExecutionStep(
            number=2,
            parent_a_id="material-a",
            parent_b_id="material-b",
            parent_a_label="A",
            parent_b_label="B",
            child=Monster(id="old-child", species="海星星"),
            in_progress=True,
        )
        replanned = ExecutionStep(
            number=5,
            parent_a_id="material-b",
            parent_b_id="material-a",
            parent_a_label="B",
            parent_b_label="A",
            child=Monster(id="new-child", species="海星星"),
        )
        app = App.__new__(App)

        saved_keys = App._capture_plan_progress_keys(
            app,
            ExecutionPlan(id="old", target_species="海星星", steps=[original]),
        )

        self.assertIn(App._plan_step_progress_key(replanned), saved_keys)

    def test_public_release_title_includes_author_contact(self) -> None:
        self.assertEqual(APP_TITLE, "Pokemmo孵蛋助手——作者：晨若 QQ1052495869 有问题反馈哦")

    def test_all_registered_popups_close_with_escape(self) -> None:
        popup = StubPopup()
        App._bind_popup_escape(popup)

        result = popup.bindings["<Escape>"]()

        self.assertEqual(result, "break")
        self.assertTrue(popup.destroyed)

    def test_genderless_inventory_code_round_trips(self) -> None:
        self.assertEqual(normalize_gender("N"), "N")
        self.assertEqual(normalize_gender("n"), "N")
        self.assertEqual(normalize_gender("无性别"), "N")

    def test_same_box_slot_on_different_accounts_does_not_overwrite(self) -> None:
        app = App.__new__(App)
        main = Monster(
            id="main",
            species="拉鲁拉丝",
            gender="F",
            ivs=[31, 1, 1, 1, 1, 1],
            account="主账号",
            page="1",
            slot="1",
        )
        alt = Monster(
            id="alt",
            species="凯西",
            gender="M",
            ivs=[1, 31, 1, 1, 1, 1],
            account="小号A",
            page="1",
            slot="1",
        )
        app.inventory = [main]
        app.editing_monster_id = None
        app.refresh_inventory_tree = lambda: None

        with patch("app.save_inventory"):
            App._upsert_inventory(app, alt, match_location=True)

        self.assertEqual({monster.id for monster in app.inventory}, {"main", "alt"})
        self.assertEqual(main.page, "1")
        self.assertEqual(main.slot, "1")

    def test_reused_slot_preserves_displaced_material_without_stale_location(self) -> None:
        app = App.__new__(App)
        old = Monster(
            id="old",
            species="拉鲁拉丝",
            gender="F",
            ivs=[31, 1, 1, 1, 1, 1],
            account="主账号",
            page="2",
            slot="7",
        )
        current = Monster(
            id="current",
            species="凯西",
            gender="M",
            ivs=[1, 31, 1, 1, 1, 1],
            account="主账号",
            page="2",
            slot="7",
        )
        app.inventory = [old]
        app.editing_monster_id = None
        app.refresh_inventory_tree = lambda: None

        with patch("app.save_inventory"):
            App._upsert_inventory(app, current, match_location=True)

        self.assertEqual(len(app.inventory), 2)
        self.assertEqual((old.page, old.slot), ("", ""))
        self.assertEqual((current.page, current.slot), ("2", "7"))

    def test_scan_mode_can_append_identical_rows_for_later_duplicate_review(self) -> None:
        app = App.__new__(App)
        first = Monster(
            id="first",
            species="长耳兔",
            gender="F",
            nature="固执",
            ivs=[31, 20, 31, 12, 31, 31],
            moves=["飞膝踢", "报恩"],
            page="2",
            slot="7",
        )
        repeated = Monster(
            id="repeated",
            species="长耳兔",
            gender="F",
            nature="固执",
            ivs=[31, 20, 31, 12, 31, 31],
            moves=["飞膝踢", "报恩"],
            page="2",
            slot="7",
        )
        app.inventory = [first]
        app.editing_monster_id = None
        app.refresh_inventory_tree = lambda: None

        with patch("app.save_inventory"):
            App._upsert_inventory(app, repeated, match_location=False)

        self.assertEqual([monster.id for monster in app.inventory], ["first", "repeated"])

    def test_responsive_layout_switches_at_desktop_breakpoint(self) -> None:
        self.assertEqual(App._layout_for_width(700), "compact")
        self.assertEqual(App._layout_for_width(979), "compact")
        self.assertEqual(App._layout_for_width(980), "split")
        self.assertEqual(App._layout_for_width(1600), "split")

    def test_loading_a_new_image_leaves_edit_mode(self) -> None:
        app = App.__new__(App)
        app.editing_monster_id = "first-row"
        app.current_image = None
        app.current_source = ""
        app.source_var = StubVariable()
        app.status_var = StubVariable()
        app.show_preview = lambda: None

        App.set_image(app, SimpleNamespace(width=800, height=600), "second-image.png")

        self.assertIsNone(app.editing_monster_id)
        self.assertEqual(app.current_source, "second-image.png")

    def test_blank_target_iv_cells_become_any(self) -> None:
        app = App.__new__(App)
        app.target_iv_vars = [
            StubVariable("31"),
            StubVariable(""),
            StubVariable("X"),
            StubVariable("0"),
            StubVariable(""),
            StubVariable("31"),
        ]
        app.target_iv_var = StubVariable()

        result = App._collect_target_iv_string(app)

        self.assertEqual(result, "31/x/x/0/x/31")
        self.assertEqual(app.target_iv_var.get(), result)

    def test_target_iv_cell_clamps_numeric_values_on_focus_loss(self) -> None:
        self.assertEqual(App._clamp_target_iv_text("99"), "31")
        self.assertEqual(App._clamp_target_iv_text("-4"), "0")
        self.assertEqual(App._clamp_target_iv_text(" 22 "), "22")
        self.assertEqual(App._clamp_target_iv_text("X"), "X")
        self.assertEqual(App._clamp_target_iv_text(""), "")

    def test_target_gender_lock_defaults_to_female_only_when_selectable(self) -> None:
        regular = SimpleNamespace(allowed_genders=("F", "M"))
        male_only = SimpleNamespace(allowed_genders=("M",))
        self.assertEqual(App._requested_target_gender(regular, True, "雌性"), "F")
        self.assertEqual(App._requested_target_gender(regular, False, "雌性"), "")
        self.assertEqual(App._requested_target_gender(male_only, True, "雄性"), "")
        self.assertEqual(App._requested_target_gender(male_only, False, "雄性", "M"), "M")

    def test_revalidating_same_target_preserves_unchecked_gender_lock(self) -> None:
        regular = SimpleNamespace(allowed_genders=("F", "M"))

        self.assertEqual(
            App._resolved_target_gender_controls(regular, "", False, "雌性", False),
            ("雌性", False),
        )
        self.assertEqual(
            App._resolved_target_gender_controls(regular, "", True, "雄性", False),
            ("雌性", True),
        )

    def test_gender_sensitive_evolution_always_forces_required_gender(self) -> None:
        regular = SimpleNamespace(allowed_genders=("F", "M"))

        self.assertEqual(
            App._resolved_target_gender_controls(regular, "M", False, "雌性", False),
            ("雄性", True),
        )

    def test_plan_scope_counts_explain_all_alpha_inventory(self) -> None:
        inventory = [
            Monster(
                id="ALPHA-LAND",
                species="长毛狗",
                gender="M",
                egg_groups=["陆上"],
                is_alpha=True,
            ),
            Monster(
                id="ALPHA-DITTO",
                species="百变怪",
                gender="N",
                is_alpha=True,
            ),
            Monster(
                id="NORMAL-OTHER",
                species="鲤鱼王",
                gender="M",
                egg_groups=["水中2", "龙"],
            ),
        ]

        self.assertEqual(
            App._plan_material_scope_counts(
                inventory,
                {"索罗亚", "索罗亚克"},
                {"陆上"},
                True,
            ),
            (0, 2, 1),
        )

    def test_unchecked_nature_still_remains_a_late_stage_target(self) -> None:
        self.assertEqual(App._requested_target_nature(" 固执 ", False), ("固执", "late"))
        self.assertEqual(App._requested_target_nature("固执", True), ("固执", "chain"))

    def test_alpha_material_switch_is_disabled_only_for_alpha_targets(self) -> None:
        app = App.__new__(App)
        app.target_alpha_var = StubVariable("头目")
        app.target_allow_alpha_materials_check = StubButton()
        app.target_alpha_material_hint_var = StubVariable()

        App._on_target_alpha_changed(app)

        self.assertEqual(app.target_allow_alpha_materials_check.options["state"], "disabled")
        self.assertIn("必须使用头目素材", app.target_alpha_material_hint_var.get())

        app.target_alpha_var.set("普通")
        App._on_target_alpha_changed(app)

        self.assertEqual(app.target_allow_alpha_materials_check.options["state"], "normal")
        self.assertIn("最终仍为普通", app.target_alpha_material_hint_var.get())

    def test_batch_location_advances_only_after_confirmation_or_skip(self) -> None:
        self.assertEqual(App._next_batch_location(9, 1, 60), (9, 2))
        self.assertEqual(App._next_batch_location(9, 60, 60), (10, 1))

    def test_space_shortcut_skips_during_post_save_state_but_not_in_editable_fields(self) -> None:
        app = App.__new__(App)
        app.root = object()
        app.batch_running = True
        app.batch_saved_count = 1
        app.batch_waiting_confirmation = False
        app.batch_worker_busy = False
        skipped: list[bool] = []
        app.skip_batch_location = lambda: skipped.append(True)

        self.assertEqual(
            App._handle_batch_space(app, SimpleNamespace(widget=app.root)),
            "break",
        )
        self.assertEqual(skipped, [True])

        editable_widget = SimpleNamespace(winfo_class=lambda: "TEntry")
        self.assertIsNone(
            App._handle_batch_space(app, SimpleNamespace(widget=editable_widget))
        )
        self.assertEqual(skipped, [True])

        label_widget = SimpleNamespace(winfo_class=lambda: "TLabel")
        self.assertEqual(App._handle_batch_space(app, SimpleNamespace(widget=label_widget)), "break")
        self.assertEqual(skipped, [True, True])

    def test_skipping_empty_slot_advances_without_writing_inventory(self) -> None:
        app = App.__new__(App)
        app.batch_running = True
        app.batch_saved_count = 1
        app.batch_worker_busy = False
        app.batch_waiting_confirmation = False
        app.batch_current_fingerprint = None
        app.batch_latest_fingerprint = b"last-visible-pokemon"
        app.batch_last_confirmed_fingerprint = None
        app.batch_last_confirmed_signature = None
        app.batch_current_confidence = None
        app.batch_awaiting_visual_change = False
        app.batch_pending_fingerprint = None
        app.batch_pending_count = 0
        app.batch_page_var = StubVariable("1")
        app.batch_slot_var = StubVariable("2")
        app.batch_slots_per_page_var = StubVariable("60")
        app.page_var = StubVariable("1")
        app.slot_var = StubVariable("2")
        app.save_monster_button = StubButton()
        app.status_var = StubVariable()
        app._start_batch_countdown = lambda: True
        app._focus_batch_shortcuts = lambda: None
        app._upsert_inventory = lambda *_args, **_kwargs: self.fail("empty positions must not create inventory rows")

        App.skip_batch_location(app)

        self.assertEqual(app.batch_page_var.get(), "1")
        self.assertEqual(app.batch_slot_var.get(), "3")
        self.assertEqual(app.page_var.get(), "1")
        self.assertEqual(app.slot_var.get(), "3")
        self.assertIn("1-1,2", app.status_var.get())
        self.assertIn("1-1,3", app.status_var.get())
        self.assertIn("未写入素材库", app.status_var.get())

    def test_scan_fingerprint_ignores_unrelated_full_window_animation(self) -> None:
        detail = Image.new("RGB", (320, 768), "#202830")
        changed_detail = detail.copy()
        changed_detail.paste("white", (50, 300, 250, 360))
        dark_full = Image.new("RGB", (1024, 768), "black")
        bright_full = Image.new("RGB", (1024, 768), "white")

        first = App._fingerprint(dark_full, detail)
        animated = App._fingerprint(bright_full, detail)
        changed = App._fingerprint(dark_full, changed_detail)

        self.assertEqual(first, animated)
        self.assertGreater(App._fingerprint_difference(first, changed), BATCH_CHANGE_DIFFERENCE)

    def test_scan_fingerprint_ignores_sprite_animation_above_text_rows(self) -> None:
        detail = Image.new("RGB", (320, 768), "#202830")
        animated = detail.copy()
        animated.paste("white", (40, 20, 280, 250))

        self.assertEqual(App._fingerprint(detail, detail), App._fingerprint(animated, animated))

    def test_batch_delay_defaults_to_three_seconds_and_clamps_user_value(self) -> None:
        app = App.__new__(App)
        app.batch_delay_var = StubVariable("99")

        self.assertEqual(BATCH_NEXT_COUNTDOWN_SECONDS, 3.0)
        self.assertEqual(App._batch_delay_seconds(app), 8.0)
        self.assertEqual(app.batch_delay_var.get(), "8")

        app.batch_delay_var.set("bad")
        self.assertEqual(App._batch_delay_seconds(app), 3.0)

    def test_batch_ocr_result_waits_for_enter_instead_of_saving(self) -> None:
        app = App.__new__(App)
        app._set_live_image = lambda _image, _source: None
        app._apply_parsed_result = lambda _parsed: (SimpleNamespace(allowed_genders=("F", "M")), True)
        app.species_var = StubVariable("蘑蘑菇")
        app.gender_var = StubVariable("F")
        app.page_var = StubVariable()
        app.slot_var = StubVariable()
        app.batch_page_var = StubVariable("9")
        app.batch_slot_var = StubVariable("1")
        app.save_monster_button = StubButton()
        app.status_var = StubVariable()
        app.editing_monster_id = "old"
        app.batch_waiting_confirmation = False
        app.batch_awaiting_visual_change = False
        app.batch_current_fingerprint = None
        app.batch_current_confidence = None
        app._upsert_inventory = lambda *_args, **_kwargs: self.fail("OCR result must not auto-save")

        App._accept_batch_result(
            app,
            {"ivs": [31, 20, 19, 18, 17, 16], "confidence": 0.88},
            object(),
            b"frame",
        )

        self.assertTrue(app.batch_waiting_confirmation)
        self.assertEqual(app.page_var.get(), "9")
        self.assertEqual(app.slot_var.get(), "1")
        self.assertIn("回车", app.save_monster_button.options["text"])

    def test_batch_countdown_uses_centisecond_display_and_forces_ocr_at_zero(self) -> None:
        self.assertEqual(App._format_batch_countdown(1.236), "1.24 秒")
        self.assertEqual(App._format_batch_countdown(-0.1), "0.00 秒")

        app = App.__new__(App)
        app.root = StubRoot()
        app.batch_running = True
        app.batch_countdown_active = True
        app.batch_countdown_after_id = "old-tick"
        app.batch_countdown_deadline = 0.0
        app.batch_cycle_title_var = StubVariable()
        app.batch_cycle_value_var = StubVariable()
        app.batch_cycle_hint_var = StubVariable()
        forced: list[bool] = []
        app._force_batch_countdown_ocr = lambda: forced.append(True)

        App._batch_countdown_tick(app)

        self.assertEqual(forced, [True])
        self.assertFalse(app.batch_countdown_active)
        self.assertEqual(app.batch_cycle_value_var.get(), "OCR 处理中")

    def test_forced_next_ocr_with_low_change_requires_f8_retry(self) -> None:
        app = App.__new__(App)
        app.root = StubRoot()
        app.batch_worker_busy = True
        app.batch_latest_fingerprint = b"same-frame"
        app.batch_last_confirmed_fingerprint = b"same-frame"
        app.batch_last_confirmed_signature = ("same",)
        app.batch_pending_fingerprint = None
        app.batch_pending_count = 0
        app.batch_awaiting_visual_change = False
        app.batch_waiting_confirmation = False
        app.save_monster_button = StubButton()
        app.status_var = StubVariable()
        app.batch_cycle_title_var = StubVariable()
        app.batch_cycle_value_var = StubVariable()
        app.batch_cycle_hint_var = StubVariable()
        app._accept_batch_result = lambda *_args: self.fail("unchanged frame must not become a new record")
        app._parsed_batch_signature = lambda _parsed: ("same",)

        App._handle_batch_ocr_result(app, {}, object(), b"same-frame", "", "next")

        self.assertTrue(app.batch_awaiting_visual_change)
        self.assertFalse(app.batch_waiting_confirmation)
        self.assertIn("F8", app.batch_cycle_value_var.get())
        self.assertIn("变化率", app.status_var.get())
        self.assertTrue(app.root.focused)

    def test_first_scan_after_same_app_restart_keeps_runtime_duplicate_guard(self) -> None:
        app = App.__new__(App)
        app.root = StubRoot()
        app.batch_worker_busy = True
        app.batch_latest_fingerprint = b"same-frame"
        app.batch_last_confirmed_fingerprint = b"same-frame"
        app.batch_last_confirmed_signature = ("same",)
        app.batch_pending_fingerprint = None
        app.batch_pending_count = 0
        app.batch_awaiting_visual_change = False
        app.batch_waiting_confirmation = False
        app.save_monster_button = StubButton()
        app.status_var = StubVariable()
        app.batch_cycle_title_var = StubVariable()
        app.batch_cycle_value_var = StubVariable()
        app.batch_cycle_hint_var = StubVariable()
        app._accept_batch_result = lambda *_args: self.fail("same runtime identity must require F8")
        app._parsed_batch_signature = lambda _parsed: ("same",)

        App._handle_batch_ocr_result(app, {}, object(), b"same-frame", "", "auto")

        self.assertTrue(app.batch_awaiting_visual_change)
        self.assertIn("F8", app.batch_cycle_value_var.get())
        self.assertIn("本次软件运行期间", app.status_var.get())

    def test_fresh_app_without_runtime_history_accepts_existing_inventory_identity(self) -> None:
        app = App.__new__(App)
        app.batch_worker_busy = True
        app.batch_latest_fingerprint = b"same-as-yesterday"
        app.batch_last_confirmed_fingerprint = None
        app.batch_last_confirmed_signature = None
        app.batch_pending_fingerprint = None
        app.batch_pending_count = 0
        accepted: list[tuple[dict, object, bytes]] = []
        app._accept_batch_result = lambda parsed, image, fingerprint: accepted.append((parsed, image, fingerprint))
        parsed = {"species": "长耳兔", "gender": "F", "nature": "固执"}
        image = object()

        App._handle_batch_ocr_result(app, parsed, image, b"same-as-yesterday", "", "auto")

        self.assertEqual(accepted, [(parsed, image, b"same-as-yesterday")])

    def test_low_pixel_change_is_accepted_when_ocr_fields_changed(self) -> None:
        app = App.__new__(App)
        app.batch_worker_busy = True
        app.batch_latest_fingerprint = b"same-frame"
        app.batch_last_confirmed_fingerprint = b"same-frame"
        app.batch_last_confirmed_signature = ("old",)
        app.batch_pending_fingerprint = None
        app.batch_pending_count = 0
        app._parsed_batch_signature = lambda _parsed: ("new",)
        accepted: list[tuple[dict, object, bytes]] = []
        app._accept_batch_result = lambda parsed, image, fingerprint: accepted.append((parsed, image, fingerprint))
        parsed = {"species": "艾路雷朵", "ivs": [31, 30, 31, 1, 19, 24]}
        image = object()

        App._handle_batch_ocr_result(app, parsed, image, b"same-frame", "", "next")

        self.assertEqual(accepted, [(parsed, image, b"same-frame")])

    def test_forced_next_ocr_with_changed_panel_is_presented_for_confirmation(self) -> None:
        app = App.__new__(App)
        app.batch_worker_busy = True
        app.batch_latest_fingerprint = bytes([255]) * 64
        app.batch_last_confirmed_fingerprint = bytes([0]) * 64
        app.batch_pending_fingerprint = None
        app.batch_pending_count = 0
        accepted: list[tuple[dict, object, bytes]] = []
        app._accept_batch_result = lambda parsed, image, fingerprint: accepted.append((parsed, image, fingerprint))
        parsed = {"species": "烈咬陆鲨"}
        image = object()

        App._handle_batch_ocr_result(app, parsed, image, bytes([255]) * 64, "", "next")

        self.assertEqual(accepted, [(parsed, image, bytes([255]) * 64)])
        self.assertFalse(app.batch_worker_busy)

    def test_ocr_species_resolution_uses_only_the_level_name_row(self) -> None:
        app = App.__new__(App)
        app.species_db = get_species_database()
        parsed = {
            "species": "引1梦人'超",
            "gender": "M",
            "raw_text": "电脑箱子\nLv.67引1梦人'超\n精神强念\n吸取拳",
        }

        record, confident = App._resolve_ocr_species(app, parsed)

        self.assertIsNotNone(record)
        self.assertEqual(record.display_name, "引梦貘人")
        self.assertTrue(confident)


if __name__ == "__main__":
    unittest.main()
