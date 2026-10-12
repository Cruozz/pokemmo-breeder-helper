import os
from types import SimpleNamespace
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from PIL import Image
from app import App


class SmallScanWindowTests(unittest.TestCase):
    def test_small_window_fits_whole_image_and_scroll_selects_bottom(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"LOCALAPPDATA": folder}):
            root = tk.Tk()
            root.attributes("-alpha", 0)
            try:
                instance = App(root)
                root.geometry("720x600")
                instance.compact_scan_view = "preview"
                root.update()
                instance._apply_responsive_layout()
                root.update_idletasks()
                instance.current_image = Image.new("RGB", (1288,822))
                instance.fit_preview()
                width, height = instance.canvas.winfo_width(), instance.canvas.winfo_height()
                self.assertGreater(height, 80)
                self.assertLessEqual(instance.preview_render_size[0]+instance.preview_offset[0], width)
                self.assertLessEqual(instance.preview_render_size[1]+instance.preview_offset[1], height)
                instance.fit_preview(actual_size=True)
                self.assertEqual(instance.preview_render_size, (1288,822))
                instance.canvas.yview_moveto(1)
                root.update_idletasks()
                instance.start_roi(SimpleNamespace(x=50,y=height-40))
                instance.finish_roi(SimpleNamespace(x=120,y=height-10))
                self.assertGreater(instance.roi[3], 790)
                self.assertEqual(instance._purchase_v_limit(), 1)
                for value in instance.target_iv_vars:
                    value.set("31")
                self.assertEqual(instance._purchase_v_limit(), 4)
                instance.target_purchase_max_v_var.set("2V")
                self.assertEqual(instance._purchase_v_limit(), 2)
            finally:
                for callback in root.tk.call("after", "info"):
                    root.after_cancel(callback)
                root.destroy()
