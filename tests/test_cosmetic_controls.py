import tkinter as tk
from tkinter import ttk
import unittest

from cosmetic_views import choose_particles


class CosmeticControlsTests(unittest.TestCase):
    def test_ordinary_picker_keeps_intrinsic_status_and_unrecognized_future_id(self):
        root=tk.Tk();root.withdraw()
        saved=[]
        try:
            window=choose_particles(root,["shiny","bats","future-particle"],saved.append)
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            next(widget for widget in descendants(window) if isinstance(widget,ttk.Button) and widget.cget("text")=="保存").invoke()
            self.assertEqual(set(saved[0]),{"shiny","bats","future-particle"})
        finally:
            root.destroy()
