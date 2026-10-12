from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from breeding_cost import PriceBook, load_price_book, material_record
from models import Monster
from planner import make_report_with_candidates
from species_data import get_species_database
from storage import load_inventory, save_inventory


class Revision0232Tests(unittest.TestCase):
    def leaves(self, root):
        if root.action:
            return self.leaves(root.action.parent_a) + self.leaves(root.action.parent_b)
        return [root]

    def test_steps_ceiling_blocks_high_v_purchases_but_keeps_high_v_stock(self):
        ivs = "31/31/31/x/31/31"
        text, candidates = make_report_with_candidates([], "鲤鱼王", "", "", ivs, ["水中2", "龙"],
                                                       strategy="steps", allow_ditto=False, max_purchase_v=3)
        self.assertTrue(candidates, text)
        self.assertGreaterEqual(candidates[0].root.breeds, 3)
        for candidate in candidates:
            self.assertTrue(all(leaf.leaf.ivs.count(31) <= 3 for leaf in self.leaves(candidate.root) if leaf.is_virtual))
        stock = [Monster(id="mother", species="鲤鱼王", gender="F", ivs=[31,31,31,1,31,1]),
                 Monster(id="father", species="鲤鱼王", gender="M", ivs=[31,31,1,1,31,31])]
        text, candidates = make_report_with_candidates(stock, "鲤鱼王", "", "", ivs, ["水中2", "龙"],
                                                       strategy="steps", allow_ditto=False, max_purchase_v=3)
        self.assertTrue(candidates, text)
        self.assertEqual((candidates[0].root.breeds, candidates[0].root.purchases), (1,0))

    def test_cash_basis_needs_no_stock_quotes_and_survives_snapshot(self):
        stock = [Monster(id="a", species="鲤鱼王", gender="F", ivs=[31,1,1,1,1,1]),
                 Monster(id="b", species="鲤鱼王", gender="M", ivs=[1,31,1,1,1,1])]
        book = PriceBook({"include_inventory_value": False})
        book.prices[material_record(stock[0])["key"]] = 999999
        text, candidates = make_report_with_candidates(stock, "鲤鱼王", "", "", "31/31/x/x/x/x", ["水中2", "龙"],
                                                       strategy="cost", allow_ditto=False, cost_pricing=book)
        self.assertTrue(candidates, text)
        report = candidates[0].cost_report()
        self.assertEqual((report.total_known, report.cash_known, report.missing), (20000,20000,0))
        self.assertTrue(all(line.unit_price == 0 for line in report.lines if line.kind == "库存"))
        self.assertFalse(candidates[0].cost_pricing["include_inventory_value"])
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(load_price_book(Path(folder)/"missing.json").include_inventory_value)

    def test_reviewed_ocr_names_resolve_and_unknown_names_stay_unknown(self):
        database = get_species_database()
        for raw, expected in (("扭拉'冰恶",215), ("催眠'超",96), ("玛狂拉'恶冰",461),
                              ("玛狙拉恶冰",461), ("蜈蛤王虫毒",545)):
            record, confident, score = database.resolve_ocr_name(raw, "F")
            self.assertEqual(record.id, expected)
            self.assertTrue(confident)
            self.assertEqual(score, 1)
        self.assertIsNone(database.reviewed_ocr_record("扭拉测试昵称"))
        self.assertIsNone(database.reviewed_ocr_record("不存在的精灵"))
        self.assertEqual(database.reviewed_ocr_record("娱王'毒虫").id, 545)
        self.assertEqual(database.reviewed_ocr_record("玛拉'冰恶").id, 461)
        self.assertIsNone(database.reviewed_ocr_record("娱王"))
        self.assertIsNone(database.reviewed_ocr_record("玛拉冰"))

    def test_inventory_name_repair_preserves_order_fields_and_local_backup(self):
        with tempfile.TemporaryDirectory() as folder, patch("storage.data_dir", return_value=Path(folder)):
            stock = [Monster(id="a", species="催眠'超", gender="F", ivs=[31,2,3,4,5,6], notes="keep"),
                     Monster(id="b", species="玛狂拉恶冰", gender="M", ivs=[1,31,3,4,31,6])]
            save_inventory(stock)
            before = [monster.to_dict() for monster in stock]
            loaded = load_inventory()
            self.assertEqual([monster.id for monster in loaded], ["a","b"])
            self.assertEqual([monster.species for monster in loaded], ["催眠貘","玛狃拉"])
            for original, repaired in zip(before, loaded):
                value = repaired.to_dict()
                for key in original.keys() - {"species","egg_groups"}:
                    self.assertEqual(value[key], original[key], key)
            load_inventory()
            with closing(sqlite3.connect(Path(folder)/"inventory.db")) as connection:
                history = json.loads(connection.execute("SELECT value FROM metadata WHERE key='ocr_species_name_repairs'").fetchone()[0])
            self.assertEqual(len(history), 2)
            self.assertEqual([row["before"] for row in history], before)
