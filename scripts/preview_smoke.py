"""Manual UI smoke test with synthetic live frames and an isolated inventory.

Run with the project Python (and vendor dependencies): python scripts/preview_smoke.py
No game connection, input automation, or real inventory writes are performed.
"""
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import App
from PIL import Image, ImageDraw
import tkinter as tk


def frame(number):
    image = Image.new("RGB", (1288, 822), "#222d32")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1287, 821), outline="#38bdf8", width=4)
    draw.rectangle((12, 40, 400, 800), fill="#192126")
    for y, label in enumerate(("PREVIEW TEST - NO GAME", "Pokemon: TEST", "IV: 21/31/31/31/29/30",
                               "Nature: Impish", "Ability: TEST", "Frame: " + str(number))):
        draw.text((30, 100 + y * 65), label, fill="white", font_size=24)
    for row in range(6):
        for col in range(10):
            x, y = 430 + col * 80, 280 + row * 70
            draw.rectangle((x, y, x + 68, y + 60), fill="#344148", outline="#596970")
            draw.text((x + 8, y + 18), str(row * 10 + col + 1), fill="#85d6fb", font_size=22)
    draw.text((430, 90), "Synthetic live inventory / manual selection", fill="white", font_size=25)
    return image


def main():
    with tempfile.TemporaryDirectory(prefix="breeder-preview-qa-") as temporary:
        with patch("storage.data_dir", return_value=Path(temporary)):
            root = tk.Tk()
            app = App(root)
            root.title("孵蛋助手 UI 验证（模拟画面／隔离库存）")
            app.set_image(frame(0), "UI 验证模拟图")
            app.set_default_roi()
            number = 0

            def refresh():
                nonlocal number
                number += 1
                app._set_live_image(frame(number), "UI 验证模拟实时画面")
                root.after(300, refresh)

            root.after(300, refresh)
            root.mainloop()


if __name__ == "__main__":
    main()
