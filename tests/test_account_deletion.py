from __future__ import annotations

import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from app import App
from models import Monster
from storage import (
    database_path, delete_accounts_and_inventory, load_accounts, load_active_plan, load_inventory,
    load_inventory_display_order, save_accounts, save_inventory, save_inventory_display_order,
    undo_last_inventory_deletion,
    save_active_plan,
)


def materials():
    return [Monster(id="one", account="OneBit", species="皮卡丘"),
            Monster(id="two", account="TwoBit", species="伊布"),
            Monster(id="lower", account="onebit", species="皮卡丘")]


class AccountDeletionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"LOCALAPPDATA": self.directory.name})
        self.environment.start()
        save_inventory(materials())
        save_inventory_display_order(["OneBit", "TwoBit", "onebit", "主账号", "Empty"], ["two", "one", "lower"])

    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()

    def test_deletion_is_exact_and_restores_account_and_order(self):
        before = [item.to_dict() for item in load_inventory()]
        result = delete_accounts_and_inventory(["OneBit"], ["TwoBit", "onebit", "主账号", "Empty"], {"one"})
        self.assertEqual([item.id for item in result], ["one"])
        self.assertEqual({item.id for item in load_inventory()}, {"two", "lower"})
        self.assertNotIn("OneBit", load_accounts())
        self.assertIn("onebit", load_accounts())
        self.assertNotIn("one", load_inventory_display_order())
        self.assertEqual([item.id for item in undo_last_inventory_deletion()], ["one"])
        self.assertIn("OneBit", load_accounts())
        self.assertEqual(load_inventory_display_order(), ["two", "one", "lower"])
        after = {item.id: item.to_dict() for item in load_inventory()}
        for item in before:
            item.pop("updated_at", None)
            restored = after[item["id"]]
            restored.pop("updated_at", None)
            self.assertEqual(restored, item)

    def test_empty_account_and_main_account_can_be_deleted_and_undone(self):
        delete_accounts_and_inventory(["主账号", "Empty"], ["OneBit", "TwoBit", "onebit"], set())
        self.assertNotIn("主账号", load_accounts())
        self.assertNotIn("Empty", load_accounts())
        self.assertEqual(undo_last_inventory_deletion(), [])
        self.assertIn("主账号", load_accounts())
        self.assertIn("Empty", load_accounts())

    def test_delete_all_accounts_persists_empty_list(self):
        delete_accounts_and_inventory(load_accounts(), [], {"one", "two", "lower"})
        self.assertEqual(load_inventory(), [])
        self.assertEqual(load_accounts(), [])
        self.assertEqual(load_inventory_display_order(), [])
        undo_last_inventory_deletion()
        self.assertEqual(len(load_inventory()), 3)
        self.assertIn("OneBit", load_accounts())

    def test_changed_inventory_aborts_everything(self):
        with self.assertRaises(ValueError):
            delete_accounts_and_inventory(["OneBit"], [], set())
        self.assertEqual(len(load_inventory()), 3)
        self.assertIn("OneBit", load_accounts())
        self.assertEqual(undo_last_inventory_deletion(), [])

    def test_failed_history_write_rolls_back_accounts_and_inventory(self):
        with closing(sqlite3.connect(database_path())) as connection:
            connection.execute("CREATE TRIGGER prevent_history BEFORE INSERT ON inventory_delete_history BEGIN SELECT RAISE(ABORT, 'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            delete_accounts_and_inventory(["OneBit"], [], {"one"})
        self.assertEqual(len(load_inventory()), 3)
        self.assertIn("OneBit", load_accounts())
        self.assertEqual(load_inventory_display_order(), ["two", "one", "lower"])

    def test_undo_preserves_new_accounts(self):
        delete_accounts_and_inventory(["OneBit"], [], {"one"})
        save_accounts([*load_accounts(), "NewAccount"])
        undo_last_inventory_deletion()
        self.assertIn("NewAccount", load_accounts())

    def test_legacy_database_gains_history_column(self):
        with closing(sqlite3.connect(database_path())) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(inventory_delete_history)")}
        self.assertIn("account_snapshot", columns)


class AccountDeletionUITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"LOCALAPPDATA": self.directory.name})
        self.environment.start()
        save_inventory(materials())
        save_accounts(["OneBit", "TwoBit", "onebit", "Empty"])
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = App(self.root)

    def tearDown(self):
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()
        self.environment.stop()
        self.directory.cleanup()

    def draft_delete(self, name):
        self.app.open_account_order_dialog()
        dialog = self.app.account_order_dialog
        selected = next(item for item in dialog.tree.get_children() if dialog.tree.item(item, "text") == name)
        dialog.tree.selection_set(selected)
        dialog.delete_selected()
        return dialog

    def test_cancel_draft_preserves_account_and_materials(self):
        dialog = self.draft_delete("OneBit")
        dialog.cancel()
        self.assertIn("OneBit", load_accounts())
        self.assertEqual(len(load_inventory()), 3)

    def test_decline_save_confirmation_preserves_everything(self):
        dialog = self.draft_delete("OneBit")
        with patch("app.messagebox.askyesno", return_value=False):
            dialog.save()
        self.assertTrue(dialog.window.winfo_exists())
        self.assertIn("OneBit", load_accounts())
        self.assertEqual(len(load_inventory()), 3)

    def test_save_deletes_hidden_materials_resets_filters_and_undo_restores(self):
        self.app.account_var.set("OneBit")
        self.app.inventory_account_filter_var.set("OneBit")
        self.app.inventory_filter_var.set("不会匹配的素材")
        dialog = self.draft_delete("OneBit")
        with patch("app.messagebox.askyesno", return_value=True) as confirm:
            dialog.save()
        self.assertIn("OneBit：1 条素材", confirm.call_args.args[1])
        self.assertNotIn("OneBit", self.app.accounts)
        self.assertEqual(self.app.inventory_account_filter_var.get(), "全部账号")
        self.assertNotEqual(self.app.account_var.get(), "OneBit")
        self.assertEqual({item.id for item in self.app.inventory}, {"two", "lower"})
        self.assertIsNone(load_active_plan())
        self.app.undo_last_inventory_delete()
        self.assertIn("OneBit", self.app.accounts)
        self.assertEqual(len(self.app.inventory), 3)

    def test_empty_account_undo_is_not_reported_as_nothing_to_undo(self):
        dialog = self.draft_delete("Empty")
        with patch("app.messagebox.askyesno", return_value=True):
            dialog.save()
        with patch("app.messagebox.showinfo") as message:
            self.app.undo_last_inventory_delete()
        message.assert_not_called()
        self.assertIn("Empty", self.app.accounts)

    def test_capture_in_progress_blocks_deletion(self):
        dialog = self.draft_delete("OneBit")
        self.app.batch_running = True
        with patch("app.messagebox.showwarning"), patch("app.messagebox.askyesno") as confirm:
            dialog.save()
        confirm.assert_not_called()
        self.assertIn("OneBit", load_accounts())
        self.app.batch_running = False

    def test_storage_failure_preserves_saved_route_and_accounts(self):
        dialog = self.draft_delete("OneBit")
        saved_route = {"id": "preserved-test-route"}
        save_active_plan(saved_route)
        with patch("app.messagebox.askyesno", return_value=True), patch("app.messagebox.showerror"), \
             patch("app.delete_accounts_and_inventory", side_effect=OSError("read only")):
            dialog.save()
        self.assertEqual(load_active_plan(), saved_route)
        self.assertIn("OneBit", load_accounts())
        self.assertEqual(len(self.app.inventory), 3)

    def test_deleting_accounts_discards_running_planner_result(self):
        dialog = self.draft_delete("OneBit")
        old_queue = self.app.plan_result_queue
        old_request = self.app.plan_request_id
        self.app.plan_worker_busy = True
        self.app.target_nature_var.set("固执")
        with patch("app.messagebox.askyesno", return_value=True):
            dialog.save()
        old_queue.put(("stale", [], ""))
        self.app._poll_plan_result(old_request)
        self.assertIsNot(self.app.plan_result_queue, old_queue)
        self.assertFalse(self.app.plan_worker_busy)
        self.assertIsNone(self.app.proposed_plan)
        self.assertEqual(self.app.target_nature_var.get(), "固执")


if __name__ == "__main__":
    unittest.main()
