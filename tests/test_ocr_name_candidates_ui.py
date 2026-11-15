import os
import tempfile
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from app import App
from ocr_engine import OCRItem, OCRProcessor


class OCRNameCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"LOCALAPPDATA": self.directory.name})
        self.environment.start()
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0)
        self.app = App(self.root)
        self.root.geometry("720x600")
        self.root.update()
        self.app._apply_responsive_layout()
        self.root.update_idletasks()

    def tearDown(self):
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()
        self.environment.stop()
        self.directory.cleanup()

    def apply_incomplete_name(self):
        parsed = OCRProcessor.parse([OCRItem("Lv.40 拉'恶冰", .99,
            [[30, 120], [270, 120], [270, 140], [30, 140]])])
        parsed.update(gender="M", ivs=[31, 1, 2, 3, 4, 5], nature="固执", is_alpha=True,
                      has_hidden_ability=True, particles=["bats"], has_particles=True)
        self.app._apply_parsed_result(parsed)
        self.root.update_idletasks()

    def test_candidate_selection_only_fills_name_and_keeps_the_result_for_review(self):
        self.apply_incomplete_name()
        app = self.app
        self.assertEqual(app.species_var.get(), "")
        self.assertEqual(set(app.ocr_species_combo.cget("values")), {"狃拉", "玛狃拉"})
        self.assertEqual(app.ocr_species_choice_var.get(), "请选择候选精灵")
        self.assertTrue(app.ocr_species_panel.winfo_ismapped())
        self.assertFalse(app.current_form.winfo_manager())  # Still available when the form is folded.
        before = (app.iv_var.get(), app.nature_var.get(), app.gender_var.get(), app.alpha_var.get(),
                  app.hidden_ability_var.get(), tuple(app.current_particles), app.page_var.get(), app.slot_var.get())
        app.confirm_batch_result = Mock()
        app.save_current_monster = Mock()
        app.ocr_species_choice_var.set("玛狃拉")
        app.ocr_species_combo.event_generate("<<ComboboxSelected>>")
        self.root.update_idletasks()
        self.assertEqual(app.species_var.get(), "玛狃拉")
        self.assertEqual(app.groups_var.get(), "陆上")
        self.assertEqual(before, (app.iv_var.get(), app.nature_var.get(), app.gender_var.get(), app.alpha_var.get(),
            app.hidden_ability_var.get(), tuple(app.current_particles), app.page_var.get(), app.slot_var.get()))
        self.assertIn("原文：拉'恶冰", app.raw_text_box.get("1.0", "1.end"))
        self.assertIn("｜玛狃拉｜", app.recent_scan_var.get())
        self.assertFalse(app.ocr_species_panel.winfo_manager())
        app.confirm_batch_result.assert_not_called()
        app.save_current_monster.assert_not_called()

    def test_dropdown_enter_does_not_save_and_stale_choices_are_ignored(self):
        self.apply_incomplete_name()
        app = self.app
        app.batch_running = app.batch_waiting_confirmation = True
        app.confirm_batch_result = Mock()
        for widget in (app.ocr_species_combo, str(app.ocr_species_combo) + ".popdown.f.l"):
            self.assertEqual(app._handle_batch_enter(SimpleNamespace(widget=widget)), "break")
        app.confirm_batch_result.assert_not_called()
        app._set_ocr_species_candidates(())
        app.ocr_species_choice_var.set("玛狃拉")
        app._select_ocr_species_candidate()
        self.assertEqual(app.species_var.get(), "")

    def test_new_result_new_image_and_clear_discard_previous_candidates(self):
        self.apply_incomplete_name()
        app = self.app
        app._apply_parsed_result({"species": "百变怪", "gender": "", "ivs": [31] * 6})
        self.assertEqual(app.species_var.get(), "百变怪")
        self.assertEqual(app.gender_var.get(), "N")
        self.assertEqual(app.ocr_species_candidates, ())
        self.apply_incomplete_name()
        app.set_image(Image.new("RGB", (400, 300)), "测试截图")
        self.assertEqual(app.ocr_species_candidates, ())
        self.apply_incomplete_name()
        app.clear_current()
        self.assertEqual(app.ocr_species_candidates, ())
        self.assertFalse(app.ocr_species_panel.winfo_manager())

    def test_manual_name_entry_expands_form_and_partial_name_cannot_bypass_choice(self):
        self.apply_incomplete_name()
        app = self.app
        app._edit_ocr_species()
        self.root.update_idletasks()
        self.assertTrue(app.current_form.winfo_manager())
        app.species_var.set("拉'恶冰")
        app._upsert_inventory = Mock()
        with patch("app.messagebox.showwarning") as warning:
            app.save_current_monster()
        warning.assert_called_once()
        app._upsert_inventory.assert_not_called()
        app._on_current_species_autocomplete("玛狃拉")
        self.assertEqual(app.ocr_species_candidates, ())
        self.assertEqual(app.species_var.get(), "玛狃拉")
