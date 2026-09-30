import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from app import App
from window_memory import WindowMemory, visible_state


class WindowMemoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"LOCALAPPDATA": self.directory.name})
        self.environment.start()
        self.path = Path(self.directory.name) / "window.json"
        self.roots = []

    def tearDown(self):
        for root in self.roots:
            try:
                for callback in root.tk.call("after", "info"):
                    root.after_cancel(callback)
                root.destroy()
            except tk.TclError:
                pass
        self.environment.stop()
        self.directory.cleanup()

    def root(self):
        root = tk.Tk()
        root.geometry("800x650+100+70")
        self.roots.append(root)
        return root

    def test_move_resize_close_and_reopen_restore_last_geometry(self):
        root = self.root()
        memory = WindowMemory(root, self.path)
        root.geometry("920x720+160+110")
        root.update()
        memory.save()
        root.destroy()
        reopened = self.root()
        WindowMemory(reopened, self.path)
        reopened.update()
        self.assertEqual(reopened.geometry(), "920x720+160+110")

    def test_maximized_reopens_maximized_and_keeps_normal_restore_position(self):
        root = self.root()
        memory = WindowMemory(root, self.path)
        root.update()
        before = dict(memory.normal)
        root.state("zoomed")
        root.update()
        memory.save()
        root.destroy()
        reopened = self.root()
        restored = WindowMemory(reopened, self.path)
        reopened.update()
        self.assertEqual(reopened.state(), "zoomed")
        self.assertEqual(restored.normal, before)
        reopened.state("normal")
        reopened.update()
        self.assertEqual(reopened.geometry(), "800x650+100+70")

    def test_minimized_close_keeps_last_visible_position(self):
        root = self.root()
        memory = WindowMemory(root, self.path)
        root.update()
        before = dict(memory.normal)
        root.iconify()
        root.update()
        memory.save()
        self.assertEqual(json.loads(self.path.read_text()), {**before, "maximized": False})

    def test_negative_secondary_screen_coordinates_restore_as_absolute_positions(self):
        saved = dict(width=800, height=650, x=-1000, y=-200, maximized=False)
        self.path.write_text(json.dumps(saved))
        root = self.root()
        with patch("window_memory.monitor_workareas", return_value=[(-1920, -600, 0, 1080), (0, 0, 1920, 1080)]):
            WindowMemory(root, self.path)
        root.update()
        self.assertEqual((root.winfo_x(), root.winfo_y()), (-1000, -200))

    def test_removed_monitor_position_returns_to_visible_workarea(self):
        saved = dict(width=900, height=650, x=-2000, y=-800, maximized=False)
        adjusted = visible_state(saved, [(0, 0, 1920, 1040)])
        self.assertEqual((adjusted["x"], adjusted["y"]), (0, 0))
        self.assertEqual((adjusted["width"], adjusted["height"]), (900, 650))

    def test_invalid_or_missing_settings_keep_the_startup_default(self):
        for content in (None, "bad json", "[]", '{}', '{"width": "900"}'):
            root = self.root()
            if content is not None:
                self.path.write_text(content)
            WindowMemory(root, self.path)
            root.update()
            self.assertEqual(root.geometry(), "800x650+100+70")
            root.destroy()

    def test_app_close_handler_saves_and_next_app_restores(self):
        root = self.root()
        app = App(root)
        root.geometry("940x700+130+90")
        root.update()
        handler = root.protocol("WM_DELETE_WINDOW")
        self.assertTrue(handler)
        root.tk.call(handler)
        saved = app.window_memory.path
        self.assertTrue(saved.is_file())
        reopened = self.root()
        App(reopened)
        reopened.update()
        self.assertEqual(reopened.geometry(), "940x700+130+90")


if __name__ == "__main__":
    unittest.main()
