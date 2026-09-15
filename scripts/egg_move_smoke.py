"""Isolated egg-move picker; never reads/writes the user's inventory or game.

python scripts/egg_move_smoke.py --size 680x430
For automated visual QA, --offscreen avoids covering the user's desktop.
"""
from pathlib import Path
import argparse
import sys
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import App
from reference_data import get_reference_database
from species_data import get_species_database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", default="860x560")
    parser.add_argument("--offscreen", action="store_true")
    parser.add_argument("--auto-close", type=int, default=0, help="Close after this many seconds")
    args = parser.parse_args()
    root = tk.Tk()
    root.withdraw()
    try:
        app = App.__new__(App)
        app.root = root
        app.app_icon_photo = None
        app.species_db = get_species_database()
        app.reference_db = get_reference_database()
        app.selected_egg_moves = ["祈愿", "哈欠"]
        app.target_egg_moves_var = tk.StringVar(master=root, value="祈愿、哈欠")
        app.lookup_target_species = lambda silent=False: app.species_db.get("伊布")
        app._configure_styles()
        app.open_egg_move_picker()
        window = next(child for child in root.winfo_children() if isinstance(child, tk.Toplevel))
        window.title("遗传技能选择 UI 验证（隔离数据）")
        window.geometry(args.size + ("+30000+30000" if args.offscreen else ""))
        window.transient("")
        if args.auto_close > 0:
            root.after(args.auto_close * 1000, window.destroy)
        root.wait_window(window)
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
