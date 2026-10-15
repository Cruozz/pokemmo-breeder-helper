import copy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from breeding_cost import ACTIVE_BOOK, PriceBook, material_record, cost_state_rank
from chain_planner import ChainState, _virtual_materials, _with_prepared_moves
from execution import build_execution_plan, ExecutionPlan
from market_data import MarketError, parse_snapshot
from planner import make_report_with_candidates
from planner_worker import purchase_market_snapshot
from reference_data import get_reference_database
from test_egg_moves import profile
from test_skill_spine_0234 import material
import test_skill_spine_0234 as spine


def market(rows=(), *, age=0):
    # datetime timestamps and time.time() can round the same Windows clock
    # tick differently. A fixture must be in the past, not a fraction ahead.
    at = datetime.now(timezone.utc) - timedelta(seconds=age + 1)
    return parse_snapshot(dict(items=[], updatedAt=at.isoformat(), pokemonQueries=[
        dict(familyId=family, query=query, price=price, quantity=quantity, listings=quantity, at=at.isoformat())
        for family, query, price, quantity in rows
    ]))


def strict_book(rows=(), **kwargs):
    return PriceBook(dict(include_inventory_value=False, require_market_availability=True), market(rows, **kwargs))


def leaf_state(monster):
    return ChainState(monster.species, monster.gender, tuple(monster.egg_groups),
                      sum(1 << i for i, v in enumerate(monster.ivs) if v == 31), False, "", True,
                      frozenset({monster.id}), 0, 0, 0, 0, leaf=monster, breeding_species=monster.species,
                      inherited_moves=frozenset(monster.moves))


class SkillMarketTests(unittest.TestCase):
    def test_female_ninetales_builds_a_male_skill_branch_then_five_iv_zorua(self):
        stock = [material("mother", "索罗亚", "F", (0, 2, 3, 4)),
                 material("ninetales", "九尾", "F", (0, 2), ("神通力",)),
                 material("stunky", "臭鼬噗", "M", (0, 3), ("临别礼物",)),
                 material("iv-sire", "小拉达", "M", (0, 3, 5))]
        before = copy.deepcopy([m.to_dict() for m in stock])
        report, candidates = make_report_with_candidates(
            stock, "索罗亚", "", "胆小", "31/x/31/31/31/31", [], target_alpha=True,
            allow_ditto=False, convert_maternal_with_ditto=True, nature_strategy="late",
            target_moves=["神通力", "临别礼物"], max_purchase_v=2, cost_pricing=strict_book())
        self.assertTrue(candidates, report)
        candidate = candidates[0]
        self.assertEqual((candidate.root.purchases, candidate.root.breeds), (0, 3))
        self.assertIn("ninetales", candidate.root.used_ids)
        plan = ExecutionPlan.from_dict(build_execution_plan(candidate).to_dict())
        self.assertEqual(plan.materials["ninetales"]["species"], "九尾")
        self.assertEqual([s.child.species for s in plan.steps], ["六尾", "六尾", "索罗亚"])
        self.assertEqual([s.child.gender for s in plan.steps[:2]], ["F", "M"])
        self.assertEqual(set(plan.steps[-1].child.moves), {"神通力", "临别礼物"})
        self.assertNotIn("神通力", plan.steps[-2].child.moves)
        self.assertEqual(plan.steps[-1].preparations[0]["species"], "六尾")
        spine.SkillSpineTests().assert_mechanically_replayable(plan)
        self.assertEqual([m.to_dict() for m in stock], before)

    def test_learning_uses_real_form_and_does_not_assign_an_ancestor_move(self):
        reference = get_reference_database()
        self.assertIn("九尾", reference.move_preparation_sources("神通力"))
        self.assertIn("坦克臭鼬", reference.move_preparation_sources("临别礼物"))
        state = leaf_state(material("nine", "九尾", "F", (0, 5)))
        state.species = state.breeding_species = "六尾"  # also test legacy serialized states
        prepared = _with_prepared_moves(state, frozenset({"神通力"}))
        self.assertEqual(prepared.move_preparations[0][0], "九尾")
        self.assertIn("1 级", prepared.move_preparations[0][2])
        self.assertFalse(state.leaf.moves)
        self.assertIsNone(_with_prepared_moves(state, frozenset({"临别礼物"})))

    def test_attack_v_ninetales_remains_protected(self):
        stock = [material("body", "索罗亚", "F", (0, 2)),
                 material("protected-nine", "九尾", "F", (0, 1), ("神通力",))]
        report, candidates = make_report_with_candidates(
            stock, "索罗亚", "", "", "31/x/31/31/x/x", [], target_alpha=True,
            allow_ditto=False, target_moves=["神通力"], max_purchase_v=2,
            cost_pricing=strict_book([(37, "alpha_male", 40000, 2)]))
        self.assertTrue(candidates, report)
        self.assertNotIn("protected-nine", candidates[0].root.used_ids)

    def test_available_stunky_replaces_unknown_alpha_smeargle_purchase(self):
        stock = [material("body", "索罗亚", "F", (0, 2))]
        book = strict_book([(434, "alpha_male", 45000, 5)])
        report, candidates = make_report_with_candidates(
            stock, "索罗亚", "", "", "31/x/31/31/x/x", [], target_alpha=True,
            allow_ditto=False, target_moves=["临别礼物"], max_purchase_v=2, cost_pricing=book)
        self.assertTrue(candidates, report)
        def leaves(s):
            if s.action:
                return leaves(s.action.parent_a) + leaves(s.action.parent_b)
            return [s]
        bought = [s for s in leaves(candidates[0].root) if s.is_virtual]
        self.assertEqual(len(bought), 1)
        self.assertIn(bought[0].leaf.species, {"臭鼬噗", "坦克臭鼬"})
        self.assertFalse(bought[0].leaf.moves)
        self.assertEqual(bought[0].move_preparations[0][1], "临别礼物")
        self.assertEqual(candidates[0].cost_report().cash_known, 65000)  # 45k + braces 20k; preparation/gender pending
        self.assertGreater(candidates[0].cost_report().missing, 0)  # learning is not free
        quote = next(iter(candidates[0].cost_pricing["auto_materials"].values()))
        self.assertEqual((quote["family_id"], quote["query"], quote["quantity"]), (434, "alpha_male", 5))
        restored = PriceBook(candidates[0].cost_pricing)
        self.assertEqual(next(iter(restored.auto_materials.values()))["family_id"], 434)

    def test_no_market_cannot_recommend_an_alpha_skill_purchase(self):
        book = PriceBook(dict(require_market_availability=True))
        token = ACTIVE_BOOK.set(book)
        try:
            candidates = _virtual_materials(profile("索罗亚"), [31, None, 31, 31, None, None], False, "", True,
                                            allow_ditto=False, target_moves=frozenset({"临别礼物"}))
        finally:
            ACTIVE_BOOK.reset(token)
        self.assertFalse(candidates)
        self.assertTrue(book.materials)  # specifications remain available for manual pricing

    def test_missing_zero_stale_and_wrong_sex_do_not_count_as_available(self):
        row = material_record(material("dog", "图图犬", "M", (0, 2)), True)
        for book in (strict_book(), strict_book([(235, "alpha_male", None, 0)]),
                     strict_book([(235, "alpha_male", 1, 2)], age=86401),
                     strict_book([(235, "alpha_male", None, 0), (235, "alpha", 1, 4)]),
                     strict_book([(235, "alpha_female", 1, 3)])):
            with self.subTest(book=book.snapshot.payload):
                self.assertFalse(book.purchase_available(row))
                self.assertIsNone(book.material_quote(row)[0])
        # Unrestricted prices can value owned 2V stock, but cannot prove that
        # a required male is currently listed when its query is absent.
        unrestricted = strict_book([(235, "alpha", 15000, 4)])
        self.assertFalse(unrestricted.purchase_available(row))
        self.assertEqual(unrestricted.material_quote(row)[0], 15000)

    def test_explicit_manual_specification_can_be_used_without_feed_coverage(self):
        book = strict_book()
        row = material_record(material("dog", "图图犬", "M", (0, 2), ("临别礼物",)), True)
        book.prices[row["key"]] = 75000
        self.assertTrue(book.purchase_available(row))
        self.assertEqual(book.material_quote(row), (75000, "手动估值"))

    def test_cheapest_quote_keeps_family_and_sex_and_rejects_zero_listings(self):
        book = strict_book([(37, "alpha_male", 30000, 4), (434, "alpha_male", 10000, 0),
                            (235, "alpha_male", 40000, 2)])
        monster = material("generic", "小拉达", "M", (0, 2))
        monster.species = "陆上组兼容雄性"
        monster.egg_groups = ["陆上"]
        quote = book.market_material(material_record(monster, True))
        self.assertEqual((quote["price"], quote["family_id"], quote["query"]), (30000, 37, "alpha_male"))

    def test_worker_refresh_failure_and_fresh_cache_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory, patch("storage.data_dir", return_value=Path(directory)), \
                patch("market_data.MarketClient") as client:
            from market_data import save_cache
            snapshot = market([(434, "alpha_male", 45000, 2)])
            save_cache(Path(directory) / "market_cache.json", snapshot, time.time())
            self.assertEqual(purchase_market_snapshot(None), snapshot)
            client.assert_not_called()
            (Path(directory) / "market_cache.json").unlink()
            client.return_value.snapshot.side_effect = MarketError("offline")
            self.assertIsNone(purchase_market_snapshot(market(age=90000)))
            client.return_value.snapshot.assert_called_once()

    def test_inventory_ties_compare_available_donor_prices_in_both_directions(self):
        for cheap_family in (434, 235):
            with self.subTest(cheap_family=cheap_family):
                book = strict_book([(family, "alpha_male", 1000 if family == cheap_family else 40000, 3)
                                    for family in (434, 235)])
                for name, method in get_reference_database().move_preparation_sources("临别礼物").items():
                    book.prices[book.remember_preparation((name, "临别礼物", method))["key"]] = 0
                report, candidates = make_report_with_candidates(
                    [material("body", "索罗亚", "F", (0, 2))], "索罗亚", "F", "", "31/x/31/31/x/x", [],
                    target_alpha=True, allow_ditto=False, target_moves=["临别礼物"], max_purchase_v=2,
                    strategy="inventory", cost_pricing=book)
                self.assertTrue(candidates, report)
                used_family = next(iter(candidates[0].cost_pricing["auto_materials"].values()))["family_id"]
                self.assertEqual(used_family, cheap_family)

    def test_lazy_market_refresh_updates_previously_ranked_inventory_quotes(self):
        book = strict_book([(37, "alpha_female", 30000, 2)])
        book.include_inventory_value = True
        state = leaf_state(material("nine", "九尾", "F", (0, 5)))
        book.market_loader = lambda current: market([(37, "alpha_female", 20000, 3)])
        token = ACTIVE_BOOK.set(book)
        try:
            self.assertEqual(cost_state_rank(state)[2], 30000)
            book.ensure_purchase_market()
            self.assertEqual(cost_state_rank(state)[2], 20000)
        finally:
            ACTIVE_BOOK.reset(token)

    def test_worker_preserves_pending_specs_for_manual_quote_after_no_route(self):
        from planner_worker import calculate, encode_request
        book = strict_book()
        request = ([material("body", "索罗亚", "F", (0, 2))], "索罗亚", "F", "", "31/x/31/31/x/x", [],
                   True, False, "inventory", "late", False, frozenset(), "smart", False,
                   ("临别礼物",), False, frozenset(), book, 2)
        result = calculate(encode_request(request))
        self.assertFalse(result["candidates"])
        rows = result["materials"]
        row = next(row for row in rows if row["virtual"] and row["conditions"].get("species") == "臭鼬噗"
                   and row["conditions"]["gender"] == "M"
                   and row["conditions"]["ivs"] == [None, None, 31, 31, None, None])
        book.prices[row["key"]] = 20000
        self.assertTrue(calculate(encode_request(request))["candidates"])


if __name__ == "__main__":
    unittest.main()
