"""Manual route UI checks with synthetic monsters and a temporary database."""
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import App
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from test_execution_consistency import fixture
from planner import make_report_with_candidates
from execution import build_execution_plan
from storage import save_inventory, save_active_plan
import tkinter as tk


def main():
    with tempfile.TemporaryDirectory(prefix="breeder-execution-qa-") as temporary:
        with patch("storage.data_dir", return_value=Path(temporary)):
            plan, inventory = fixture()
            plan.steps[0].completed = True
            inventory = [plan.steps[0].child, inventory[-1]]
            save_inventory(inventory)
            save_active_plan(plan.to_dict())
            root = tk.Tk()
            app = App(root)
            root.title("路线一致性验证（合成素材／隔离库存）")
            root.geometry("1100x850")
            report, candidates = make_report_with_candidates(inventory, "巨钳螳螂", "", "固执", "31/31/31/x/31/31", ["虫"])
            app.current_candidates = candidates
            app.proposed_plan = build_execution_plan(candidates[0])
            app._select_workspace_mode("planner")
            app._set_planner_details_collapsed(True)
            app.refresh_plan_status()
            root.mainloop()


if __name__ == "__main__":
    main()
