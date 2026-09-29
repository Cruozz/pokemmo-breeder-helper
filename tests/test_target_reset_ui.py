import os
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from app import App


class TargetResetUITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"LOCALAPPDATA": self.directory.name})
        self.environment.start()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = App(self.root)
        self.app.target_species_var.set("皮卡丘")
        self.app.lookup_target_species(silent=True)
        self.app.target_nature_var.set("固执")
        self.app.target_alpha_var.set("头目")
        self.app.selected_egg_moves = ["祈愿"]
        self.app.target_egg_moves_var.set("祈愿")
        for name in ("target_hidden_ability_var", "target_lock_gender_var", "target_lock_nature_var",
                     "target_allow_ditto_var", "target_convert_mother_with_ditto_var", "target_allow_alpha_materials_var"):
            getattr(self.app, name).set(True)
        for variable in self.app.target_iv_vars:
            variable.set("31")

    def tearDown(self):
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()
        self.environment.stop()
        self.directory.cleanup()

    def test_clear_without_generated_route_resets_all_target_constraints(self):
        self.assertIsNone(self.app.active_plan)
        self.assertFalse(self.app.clear_current_plan_button.instate(["disabled"]))
        with patch("app.messagebox.askyesno", return_value=True):
            self.app.clear_current_plan()
        self.assertEqual(self.app.target_species_var.get(), "")
        self.assertIsNone(self.app.selected_target_species_id)
        self.assertEqual(self.app.target_nature_var.get(), "")
        self.assertEqual(self.app.target_iv_var.get(), "x/x/x/x/x/x")
        self.assertEqual([variable.get() for variable in self.app.target_iv_vars], ["X"] * 6)
        self.assertEqual(self.app.selected_egg_moves, [])
        self.assertEqual(self.app.target_groups_var.get(), "待选择")
        self.assertEqual(self.app.target_alpha_var.get(), "普通")
        self.assertEqual(self.app.target_info_var.get(), "")
        for name in ("target_hidden_ability_var", "target_lock_gender_var", "target_lock_nature_var",
                     "target_allow_ditto_var", "target_convert_mother_with_ditto_var", "target_allow_alpha_materials_var"):
            self.assertFalse(getattr(self.app, name).get(), name)
        self.assertEqual(self.app.target_species_list.size(), 0)

    def test_cancel_preserves_targets(self):
        with patch("app.messagebox.askyesno", return_value=False):
            self.app.clear_current_plan()
        self.assertEqual(self.app.target_species_var.get(), "皮卡丘")
        self.assertEqual(self.app.target_nature_var.get(), "固执")
        self.assertEqual(self.app.selected_egg_moves, ["祈愿"])


if __name__ == "__main__":
    unittest.main()
