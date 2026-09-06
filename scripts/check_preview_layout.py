"""Real Tk layout assertions; run on a machine with a desktop/Tk runtime."""
from pathlib import Path
import sys
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor"))
from PIL import Image
from preview_dialog import PreviewZoomWindow


def check():
    root = tk.Tk()
    root.geometry("700x500")
    preview = PreviewZoomWindow(root, Image.new("RGB", (1288, 822)), (0, 0, 412, 822), lambda roi: None)
    try:
        for size in ("1000x720", "640x460", "1400x900"):
            preview.window.geometry(size)
            root.update()
            preview._resize()
            root.update_idletasks()
            viewport = (preview.canvas.winfo_width(), preview.canvas.winfo_height())
            rendered = preview.rendered_size
            assert preview.fit_mode
            assert all(rendered[i] <= viewport[i] for i in (0, 1)), (size, rendered, viewport)
            assert any(rendered[i] == viewport[i] for i in (0, 1)), (size, rendered, viewport)
            assert abs(rendered[0] / rendered[1] - 1288 / 822) < 0.015
            assert preview.roi == (0, 0, 412, 822)

            def visit(widget):
                for child in widget.winfo_children():
                    if child.winfo_class() in {"TButton", "TEntry", "TCheckbutton"}:
                        assert child.winfo_ismapped(), (size, child)
                        assert child.winfo_width() >= child.winfo_reqwidth(), (size, child, "clipped")
                        assert child.winfo_x() + child.winfo_width() <= widget.winfo_width(), (size, child)
                    visit(child)

            visit(preview.window)
            print(f"PASS {size}: viewport={viewport}, rendered={rendered}, controls fit")
        preview.actual_size()
        assert preview.rendered_size == preview.image.size
        preview.window.geometry("640x460")
        root.update()
        preview._resize()
        assert preview.rendered_size == preview.image.size, "manual 1:1 must survive resize"
        preview.fit_to_window()
        assert preview.fit_mode
        print("PASS manual 1:1 survives resize; fit mode can be restored")
    finally:
        preview.close()
        root.destroy()


if __name__ == "__main__":
    check()
