from __future__ import annotations

import ctypes
import unittest
from ctypes import wintypes
from types import SimpleNamespace
from unittest.mock import patch

import app  # Adds the bundled vendor directory before capture imports Pillow.
from capture import WindowInfo, capture_window, physical_coordinates


class CaptureTests(unittest.TestCase):
    def test_dpi_context_is_restored_even_when_capture_fails(self):
        calls = []
        def setter(value):
            calls.append(value)
            return 123
        fake = SimpleNamespace(SetThreadDpiAwarenessContext=setter)
        with patch("capture.user32", fake):
            with self.assertRaises(OSError):
                with physical_coordinates():
                    self.assertIsInstance(calls[0], ctypes.c_void_p)
                    raise OSError("capture failed")
        self.assertEqual(calls[-1], 123)

    def test_capture_refreshes_window_bounds_each_frame(self) -> None:
        window = WindowInfo(123, "PokeMMO", 0, 0, 640, 480)

        def get_window_rect(_hwnd, pointer) -> bool:
            rect = ctypes.cast(pointer, ctypes.POINTER(wintypes.RECT)).contents
            rect.left = 100
            rect.top = 80
            rect.right = 1124
            rect.bottom = 848
            return True

        fake_user32 = SimpleNamespace(
            IsWindow=lambda _hwnd: True,
            IsIconic=lambda _hwnd: False,
            GetWindowRect=get_window_rect,
        )
        screenshot = SimpleNamespace(size=(1024, 768))
        screenshot.convert = lambda _mode: screenshot
        with patch("capture.user32", fake_user32), patch("capture.ImageGrab.grab", return_value=screenshot) as grab:
            result = capture_window(window)

        self.assertEqual((window.left, window.top, window.right, window.bottom), (100, 80, 1124, 848))
        self.assertEqual(result.size, (1024, 768))
        self.assertEqual(grab.call_args.kwargs["bbox"], (100, 80, 1124, 848))


if __name__ == "__main__":
    unittest.main()
