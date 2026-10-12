from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import Mock

from breeding_cost import PriceBook, load_price_book, material_record
from cost_views import CostDialog
from market_data import MarketError, parse_snapshot
from tests.test_breeding_cost import breeder, leaf
from chain_planner import ChainCandidate, SpeciesProfile, _forced_child


class CostViewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()
        self.monster = breeder("local", "F", [31, 1, 1, 1, 1, 1])
        self.client = Mock()
        self.saved = Mock()
        self.path = Path(self.directory.name) / "prices.json"
        self.dialog = CostDialog(self.root, book=PriceBook(), path=self.path,
                                 inventory=[self.monster], on_saved=self.saved, client=self.client)
        self.root.update()

    def tearDown(self):
        if self.dialog.winfo_exists():
            self.dialog.close()
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()
        self.directory.cleanup()

    def select(self):
        key = material_record(self.monster)["key"]
        self.dialog.material_tree.selection_set(key)
        self.dialog.select_material()
        return key

    def pump(self):
        until = time.monotonic() + 3
        while self.dialog.in_flight and time.monotonic() < until:
            self.root.update()
            time.sleep(.01)
        self.root.update()

    def test_manual_value_saved_and_loaded(self):
        key = self.select()
        self.dialog.price_var.set("13,000")
        self.dialog.set_material_price()
        self.dialog.save()
        self.assertEqual(load_price_book(self.path).prices[key], 13000)
        self.saved.assert_called_once()

    def test_zero_is_distinct_from_blank(self):
        key = self.select()
        self.dialog.price_var.set("0")
        self.dialog.set_material_price()
        self.assertEqual(self.dialog.book.prices[key], 0)
        self.dialog.clear_material_price()
        self.assertNotIn(key, self.dialog.book.prices)

    def test_invalid_value_is_not_saved(self):
        key = self.select()
        self.dialog.price_var.set("-50")
        self.dialog.set_material_price()
        self.assertNotIn(key, self.dialog.book.prices)
        self.assertTrue(self.dialog.edit_error.get())

    def test_invalid_default_fee_does_not_change_book(self):
        self.dialog.fee_vars["gender"].set("-1")
        self.dialog.save()
        self.assertEqual(self.dialog.book.gender, 5000)
        self.assertFalse(self.path.exists())

    def test_market_failure_keeps_manual_prices(self):
        key = self.select()
        self.dialog.book.prices[key] = 5000
        self.client.snapshot.side_effect = MarketError("offline", 180)
        self.dialog.refresh_market()
        self.pump()
        self.assertEqual(self.dialog.book.prices[key], 5000)
        self.assertGreater(self.dialog.retry_until, time.time() + 100)
        self.assertIn("保留", self.dialog.status_var.get())

    def test_refresh_is_single_flight_and_cache_saved(self):
        self.client.snapshot.return_value = parse_snapshot(dict(items=[], pokemonQueries=[]))
        self.dialog.refresh_market()
        self.dialog.refresh_market()
        self.pump()
        self.client.snapshot.assert_called_once()
        self.assertTrue(self.dialog.cache_path.exists())

    def test_minimum_size_keeps_actions_visible(self):
        self.root.deiconify()
        self.dialog.deiconify()
        self.dialog.geometry("660x480")
        self.dialog.tabs.select(1)
        self.root.update()
        self.assertLess(self.dialog.price_entry.winfo_rooty() + self.dialog.price_entry.winfo_height(), self.dialog.winfo_rooty() + self.dialog.winfo_height())
        self.assertTrue(self.dialog.material_tree.winfo_ismapped())

    def test_details_and_special_fee_can_be_edited(self):
        mother = leaf(self.monster)
        father = leaf(breeder("father", "M", [1, 31, 1, 1, 1, 1]))
        state = _forced_child(mother, father, SpeciesProfile("鲤鱼王", "鲤鱼王", ("水中2", "龙"), False, ("F", "M")), "F", 0, 1)
        self.dialog.candidates = [ChainCandidate(state, [31, 31, None, None, None, None], "", "F")]
        self.dialog.render_report()
        self.assertIn("总消耗价值", self.dialog.summary_var.get())
        self.assertEqual(len(self.dialog.details_tree.get_children()), 5)
        self.dialog.gender_tree.selection_set("129:F")
        self.dialog.gender_price_var.set("12000")
        self.dialog.set_gender_price()
        self.assertEqual(self.dialog.book.gender_overrides["129:F"], 12000)
