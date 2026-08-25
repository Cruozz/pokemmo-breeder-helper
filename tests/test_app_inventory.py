from __future__ import annotations

import unittest
from types import SimpleNamespace

from app import APP_TITLE, BATCH_CHANGE_DIFFERENCE, BATCH_NEXT_COUNTDOWN_SECONDS, App
from models import normalize_gender
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


class AppInventoryFlowTests(unittest.TestCase):
    def test_public_release_title_includes_author_contact(self) -> None:
        self.assertEqual(APP_TITLE, "Pokemmo孵蛋助手——作者：晨若 QQ1052495869 有问题反馈哦")

    def test_genderless_inventory_code_round_trips(self) -> None:
        self.assertEqual(normalize_gender("N"), "N")
        self.assertEqual(normalize_gender("n"), "N")
        self.assertEqual(normalize_gender("无性别"), "N")

    def test_responsive_layout_switches_at_desktop_breakpoint(self) -> None:
        self.assertEqual(App._layout_for_width(700), "vertical")
        self.assertEqual(App._layout_for_width(1179), "vertical")
        self.assertEqual(App._layout_for_width(1180), "horizontal")
        self.assertEqual(App._layout_for_width(1600), "horizontal")

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
