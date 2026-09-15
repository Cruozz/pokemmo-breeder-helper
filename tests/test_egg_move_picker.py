from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk
import unittest

from app import App
from reference_data import get_reference_database
from species_data import get_species_database


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class EggMovePickerTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = App.__new__(App)
        self.app.root = self.root
        self.app.app_icon_photo = None
        self.app.species_db = get_species_database()
        self.app.reference_db = get_reference_database()
        self.app.selected_egg_moves = ["祈愿"]
        self.app.target_egg_moves_var = tk.StringVar(master=self.root, value="祈愿")
        self.app.lookup_target_species = lambda silent=False: self.app.species_db.get("伊布")
        self.app._configure_styles()
        self.app.open_egg_move_picker()
        self.window = next(child for child in self.root.winfo_children() if isinstance(child, tk.Toplevel))
        self.root.update_idletasks()
        self.widgets = list(descendants(self.window))
        self.listbox = next(widget for widget in self.widgets if isinstance(widget, tk.Listbox))
        self.text = next(widget for widget in self.widgets if isinstance(widget, tk.Text))
        self.buttons = {str(widget.cget("text")): widget for widget in self.widgets if isinstance(widget, ttk.Button)}

    def select(self, names):
        self.listbox.selection_clear(0, tk.END)
        all_names = list(self.listbox.get(0, tk.END))
        for name in names:
            self.listbox.selection_set(all_names.index(name))
        # The test window remains withdrawn, so Tk intentionally suppresses
        # UI events. Invoke its registered handler through Tcl instead.
        script = self.listbox.bind("<<ListboxSelect>>")
        command = re.search(r"\[([^ ]+)", script).group(1)
        self.listbox.tk.call(command)
        self.root.update_idletasks()

    def test_reference_is_read_only_and_scrollable(self):
        self.assertEqual(str(self.text.cget("state")), "disabled")
        self.assertTrue(self.text.cget("yscrollcommand"))
        self.assertIn("祈愿", self.text.get("1.0", tk.END))
        self.assertIn("采购父本必须已经携带", self.text.get("1.0", tk.END))

    def test_over_limit_selection_disables_confirmation(self):
        self.select(list(self.listbox.get(0, 4)))
        self.assertIn("disabled", self.buttons["确认选择"].state())
        self.buttons["确认选择"].invoke()
        self.assertTrue(self.window.winfo_exists())
        self.assertEqual(self.app.selected_egg_moves, ["祈愿"])
        self.select(["祈愿", "哈欠"])
        self.assertNotIn("disabled", self.buttons["确认选择"].state())
        self.buttons["确认选择"].invoke()
        self.assertEqual(set(self.app.selected_egg_moves), {"祈愿", "哈欠"})

    def test_clear_is_local_until_confirmed(self):
        self.buttons["清空选择"].invoke()
        self.assertEqual(self.listbox.curselection(), ())
        self.assertEqual(self.app.selected_egg_moves, ["祈愿"])
        self.buttons["确认选择"].invoke()
        self.assertEqual(self.app.selected_egg_moves, [])
        self.assertEqual(self.app.target_egg_moves_var.get(), "不需要遗传技能")

    def test_cancel_does_not_change_the_target(self):
        self.select(["哈欠"])
        self.buttons["取消"].invoke()
        self.assertEqual(self.app.selected_egg_moves, ["祈愿"])


if __name__ == "__main__":
    unittest.main()
