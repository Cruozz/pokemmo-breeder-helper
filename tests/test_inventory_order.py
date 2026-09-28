from __future__ import annotations

import copy
from contextlib import closing
import os
import sqlite3
import tempfile
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app import App
from account_order_dialog import AccountOrderDialog
from inventory_order import inventory_in_display_order, sorted_inventory_ids
from models import Monster
from storage import (
    active_plan_path, database_path, load_accounts, load_inventory,
    load_inventory_display_order, save_accounts, save_inventory,
    save_inventory_display_order,
)


def material(identifier, account="OneBit", page="1", slot="1"):
    return Monster(id=identifier, account=account, page=page, slot=slot, species="伊布")


class InventoryOrderTests(unittest.TestCase):
    def test_account_grouping_and_numeric_positions(self):
        items = [
            material("two9", "TwoBit", slot="9"),
            material("one10", slot="10"), material("one9", slot="9"),
            material("one_page10", page="10"), material("one_page2", page="2"),
            material("one11", slot="11"), material("three", "ThreeBit"),
        ]
        before = copy.deepcopy(items)
        self.assertEqual(sorted_inventory_ids(items, ["OneBit", "TwoBit", "ThreeBit"]),
                         ["one9", "one10", "one11", "one_page2", "one_page10", "two9", "three"])
        self.assertEqual(sorted_inventory_ids(items, ["ThreeBit", "TwoBit", "OneBit"])[:2], ["three", "two9"])
        self.assertEqual(items, before)

    def test_unknown_positions_duplicates_and_case_distinct_accounts_remain_intact(self):
        items = [material("blank", page=""), material("invalid", page="bad"),
                 material("zero", slot="0"), material("a", slot="9"), material("b", slot="9"),
                 material("lowercase", "onebit"), material("negative", page="-1")]
        self.assertEqual(sorted_inventory_ids(items, ["OneBit"]),
                         ["a", "b", "blank", "invalid", "zero", "negative", "lowercase"])

    def test_new_material_stays_last_until_next_manual_sort(self):
        items = [material("two9", "TwoBit", slot="9"), material("one9", slot="9")]
        snapshot = sorted_inventory_ids(items, ["OneBit", "TwoBit"])
        items.append(material("replacement", slot="10"))
        self.assertEqual([item.id for item in inventory_in_display_order(items, snapshot)],
                         ["one9", "two9", "replacement"])
        next_snapshot = sorted_inventory_ids(items, ["OneBit", "TwoBit"])
        self.assertEqual(next_snapshot, ["one9", "replacement", "two9"])
        self.assertEqual([item.id for item in inventory_in_display_order(items[1:], next_snapshot)],
                         ["one9", "replacement"])

    def test_sort_settings_survive_restart_without_touching_inventory_or_active_plan(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": directory}):
            items = [material("two", "TwoBit"), material("one")]
            save_inventory(items)
            active_plan_path().write_text('{"test":"unchanged"}', encoding="utf-8")
            with closing(sqlite3.connect(database_path())) as connection:
                before = connection.execute("SELECT rowid, * FROM inventory").fetchall()
            accounts = ["OneBit", "TwoBit", "主账号", "EmptyAccount"]
            save_inventory_display_order(accounts, ["one", "two"])
            self.assertEqual(load_accounts(), accounts)
            self.assertEqual(load_inventory_display_order(), ["one", "two"])
            self.assertEqual([item.id for item in load_inventory()], ["two", "one"])
            with closing(sqlite3.connect(database_path())) as connection:
                self.assertEqual(connection.execute("SELECT rowid, * FROM inventory").fetchall(), before)
            self.assertEqual(active_plan_path().read_text(encoding="utf-8"), '{"test":"unchanged"}')
            save_accounts([*accounts, "NewAccount"])
            self.assertEqual(load_accounts(), [*accounts, "NewAccount"])

    def test_old_database_and_invalid_display_metadata_fall_back_to_insertion_order(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": directory}):
            self.assertEqual(load_inventory_display_order(), [])
            self.assertEqual(load_accounts(), ["主账号"])
            with closing(sqlite3.connect(database_path())) as connection:
                connection.execute("INSERT OR REPLACE INTO metadata VALUES ('inventory_display_order', 'bad json')")
                connection.commit()
            self.assertEqual(load_inventory_display_order(), [])


class InventoryOrderUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"LOCALAPPDATA": self.temp.name})
        self.env.start()
        self.root = tk.Tk()
        self.root.geometry("900x520+0+0")
        self.app = App.__new__(App)
        self.app.root = self.root
        self.app.inventory = [material("two9", "TwoBit", slot="9"), material("one9", slot="9")]
        self.app.accounts = ["OneBit", "TwoBit", "主账号"]
        self.app.inventory_display_order = []
        for attr, value in [("inventory_filter_var", ""), ("inventory_status_filter_var", "全部状态"),
                            ("inventory_type_filter_var", "全部类别"), ("inventory_account_filter_var", "全部账号"),
                            ("inventory_summary_var", ""), ("inventory_selection_var", ""), ("status_var", "")]:
            setattr(self.app, attr, tk.StringVar(self.root, value=value))
        self.app.account_var = tk.StringVar(self.root, value="TwoBit")
        self.app.account_combo = ttk.Combobox(self.root, textvariable=self.app.account_var)
        self.app.batch_account_combo = ttk.Combobox(self.root, textvariable=self.app.account_var)
        parent = ttk.Frame(self.root)
        parent.pack(fill="both", expand=True)
        self.app.build_inventory_tab(parent)
        self.app.refresh_inventory_tree()
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        self.env.stop()
        self.temp.cleanup()

    def test_sort_keeps_selection_filters_and_new_entries_append(self):
        app = self.app
        before = copy.deepcopy(app.inventory)
        app.inventory_tree.selection_set("one9")
        app.inventory_tree.focus("one9")
        app.inventory_account_filter_var.set("OneBit")
        app.inventory_reorder_button.invoke()
        self.root.update()
        self.assertEqual(app.inventory_tree.get_children(), ("one9",))
        self.assertEqual(app.inventory_tree.selection(), ("one9",))
        self.assertEqual(app.inventory_tree.focus(), "one9")
        self.assertEqual(app.inventory, before)
        self.assertEqual(load_inventory_display_order(), ["one9", "two9"])
        app.inventory_account_filter_var.set("全部账号")
        app.inventory.append(material("one10", slot="10"))
        app.refresh_inventory_tree()
        self.assertEqual(app.inventory_tree.get_children(), ("one9", "two9", "one10"))
        app.inventory_reorder_button.invoke()
        self.assertEqual(app.inventory_tree.get_children(), ("one9", "one10", "two9"))
        self.assertEqual(app.account_var.get(), "TwoBit")

    def test_drag_save_syncs_all_account_selectors_and_cancel_discards_draft(self):
        app = self.app
        dialog = AccountOrderDialog(tk.Toplevel(self.root), app.accounts, app.reorder_inventory)
        self.root.update()
        first, second = dialog.tree.bbox("0"), dialog.tree.bbox("1")
        dialog.tree.event_generate("<ButtonPress-1>", x=20, y=second[1] + 5)
        dialog.tree.event_generate("<B1-Motion>", x=20, y=first[1] + 2)
        dialog.tree.event_generate("<ButtonRelease-1>", x=20, y=first[1] + 2)
        self.root.update()
        self.assertEqual(dialog.ordered_accounts(), ["TwoBit", "OneBit", "主账号"])
        self.assertEqual(app.accounts, ["OneBit", "TwoBit", "主账号"])
        dialog.save_button.invoke()
        self.root.update()
        self.assertEqual(load_accounts(), ["TwoBit", "OneBit", "主账号"])
        for combo in (app.account_combo, app.batch_account_combo):
            self.assertEqual(tuple(combo["values"]), ("TwoBit", "OneBit", "主账号"))
        self.assertEqual(tuple(app.inventory_account_filter["values"]), ("全部账号", "TwoBit", "OneBit", "主账号"))
        draft = AccountOrderDialog(tk.Toplevel(self.root), app.accounts, app.reorder_inventory)
        self.root.update()
        draft.down_button.invoke()
        draft.cancel_button.invoke()
        self.assertEqual(load_accounts(), ["TwoBit", "OneBit", "主账号"])

    def test_write_failure_preserves_previous_order_and_keeps_dialog_open(self):
        app = self.app
        before = app.inventory_tree.get_children()
        dialog = AccountOrderDialog(tk.Toplevel(self.root), app.accounts, app.reorder_inventory)
        self.root.update()
        dialog.down_button.invoke()
        with patch("app.save_inventory_display_order", side_effect=OSError("read-only")), patch("app.messagebox.showerror") as error:
            dialog.save_button.invoke()
        self.assertTrue(dialog.window.winfo_exists())
        self.assertEqual(app.accounts, ["OneBit", "TwoBit", "主账号"])
        self.assertEqual(app.inventory_tree.get_children(), before)
        error.assert_called_once()
        dialog.cancel()

    def test_drag_many_accounts_autoscrolls_and_long_names_remain_available(self):
        names = ["角色" + str(i) + "很长的角色名称" * 3 for i in range(30)]
        dialog = AccountOrderDialog(tk.Toplevel(self.root), names, lambda _names: True)
        self.root.update()
        bbox = dialog.tree.bbox("0")
        dialog._press(SimpleNamespace(y=bbox[1] + 5))
        dialog._drag(SimpleNamespace(y=dialog.tree.winfo_height() - 4))
        for _ in range(15):
            if dialog.scroll_timer is not None:
                dialog.window.after_cancel(dialog.scroll_timer)
            dialog._scroll_drag()
            self.root.update()
        dialog._release()
        self.assertGreater(dialog.tree.index("0"), 8)
        self.assertEqual(set(dialog.ordered_accounts()), set(names))
        dialog.cancel()


if __name__ == "__main__":
    unittest.main()
