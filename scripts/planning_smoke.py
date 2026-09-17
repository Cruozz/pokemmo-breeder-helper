"""Exercise planning/reset UI using synthetic inventory only; --visible captures PNGs."""
from pathlib import Path
import argparse
import sys
import tempfile
import tkinter as tk
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "tests"))
from app import App
from PIL import ImageGrab
from storage import load_active_plan, load_inventory, save_active_plan, save_inventory
from test_route_colors import color_fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visible", action="store_true", help="Briefly show the test window to render screenshots")
    parser.add_argument("--size", default="1460x1000")
    parser.add_argument("--maternal-skill", action="store_true")
    args = parser.parse_args()
    output = PROJECT / "release" / ("qa-027-maternal" if args.maternal_skill else "qa-027")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="breeder-planning-qa-") as temporary, \
         patch("storage.data_dir", return_value=Path(temporary)), patch("app.list_windows", return_value=[]):
        candidate, plan, inventory = color_fixture(maternal_skill=args.maternal_skill)
        save_inventory(inventory)
        save_active_plan(plan.to_dict())
        root = tk.Tk()
        root.withdraw()
        try:
            app = App(root)
            app.current_candidates = [candidate]
            app.proposed_plan = plan
            app._select_workspace_mode("planner")
            app._set_planner_details_collapsed(True)
            root.state("normal")
            root.geometry(args.size + ("+20+20" if args.visible else "+30000+30000"))
            root.deiconify()
            root.update()
            app.plan_map.set_zoom(0.7)
            app.refresh_plan_status()

            def snapshot(name):
                root.update()
                if args.visible:
                    ImageGrab.grab(window=int(root.frame(), 16)).save(output / name)

            def verify():
                try:
                    snapshot("active.png")
                    assert app.clear_current_plan_button.winfo_ismapped()
                    assert str(app.clear_current_plan_button["state"]) == "normal"
                    app._set_plan_view("proposal")
                    snapshot("proposal.png")
                    assert app.plan_map.root_node.route_moves == ("祈愿",)
                    assert {n.route_role for n in app.plan_map.nodes_by_key.values()} == {"maternal", "nature", "iv"}
                    app._set_plan_view("active")
                    app.active_plan.steps[0].completed = True
                    app.expanded_completed_sources.add((plan.id, 1))
                    app.refresh_plan_status()
                    snapshot("expanded.png")
                    before = [m.to_dict() for m in load_inventory()]
                    with patch("app.messagebox.askyesno", return_value=True):
                        app.clear_current_plan_button.invoke()
                    snapshot("cleared.png")
                    assert app.plan_map.node_count == 0
                    assert load_active_plan() is None
                    assert before == [m.to_dict() for m in load_inventory()]
                    assert str(app.clear_current_plan_button["state"]) == "disabled"
                    print(f"Planning UI checks passed; screenshots: {output}", flush=True)
                except BaseException as exc:
                    failures.append(exc)
                finally:
                    root.quit()

            failures = []
            root.after(400, verify)
            root.mainloop()
            if failures:
                raise failures[0]
        finally:
            root.destroy()


if __name__ == "__main__":
    main()
