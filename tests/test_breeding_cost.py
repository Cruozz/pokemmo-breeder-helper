import json
from pathlib import Path
import tempfile
import time
import unittest

from breeding_cost import ACTIVE_BOOK, PriceBook, amount, cost_state_rank, material_record, load_price_book, save_price_book
from chain_planner import ChainCandidate, ChainState, SpeciesProfile, _forced_child
from market_data import parse_snapshot, load_catalog
from models import Monster
from planner import make_report_with_candidates


def breeder(key, gender, ivs, species="鲤鱼王", nature=""):
    return Monster(id=key, species=species, gender=gender, ivs=ivs, nature=nature, egg_groups=["水中2", "龙"])


def leaf(monster, virtual=False):
    return ChainState(monster.species, monster.gender, tuple(monster.egg_groups),
                      sum(1 << i for i, value in enumerate(monster.ivs) if value == 31),
                      bool(monster.nature), monster.nature, monster.is_alpha,
                      frozenset({monster.id}), 0, 0, 0, 0, purchases=int(virtual),
                      leaf=monster, is_virtual=virtual)


class CostTests(unittest.TestCase):
    def market(self, rows, *, age=0):
        date = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - age))
        return parse_snapshot(dict(items=[], pokemonQueries=[dict(familyId=f, query=q, price=p, at=date) for f, q, p in rows]))

    def alpha_material(self, ivs=None, species="美纳斯", gender="F"):
        monster = breeder("alpha", gender, ivs or [31, 1, 31, 1, 1, 1], species, "内敛")
        monster.is_alpha = True
        monster.has_hidden_ability = True
        monster.moves = ["水炮"]
        return monster

    def test_inventory_alpha_2v_uses_family_gender_quote(self):
        book = PriceBook(snapshot=self.market([(349, "alpha", 38000), (349, "alpha_female", 40000), (349, "alpha_male", 60000)]))
        self.assertEqual(book.material_quote(material_record(self.alpha_material())), (40000, "头目2V行情"))
        self.assertEqual(book.material_quote(material_record(self.alpha_material(gender="M")))[0], 60000)

    def test_alpha_without_gender_quote_uses_alpha_baseline(self):
        book = PriceBook(snapshot=self.market([(349, "alpha", 38000), (349, "any", 1000)]))
        self.assertEqual(book.material_quote(material_record(self.alpha_material())), (38000, "头目2V行情"))

    def test_alpha_three_and_more_v_require_manual_price(self):
        book = PriceBook(snapshot=self.market([(349, "alpha", 38000)]))
        for ivs in ([31, 31, 31, 1, 1, 1], [31] * 6):
            row = material_record(self.alpha_material(ivs))
            self.assertEqual(book.material_quote(row), (None, "待报价"))
            book.prices[row["key"]] = 90000
            self.assertEqual(book.material_quote(row), (90000, "手动估值"))

    def test_normal_one_v_matches_group_stat_and_gender(self):
        book = PriceBook(snapshot=self.market([(0, "egg:11:iv_hp:male", 4500), (0, "egg:11:iv_hp:female", 6500), (0, "egg:11:iv_atk:male", 9999)]))
        monster = breeder("gengar", "M", [31, 1, 1, 1, 1, 1], "耿鬼", "内敛")
        monster.moves = ["影子球"]
        self.assertEqual(book.material_quote(material_record(monster)), (4500, "蛋组1V行情"))
        monster.gender = "F"
        self.assertEqual(book.material_quote(material_record(monster))[0], 6500)

    def test_ditto_one_v_matches_genderless_query(self):
        monster = breeder("ditto", "N", [1, 1, 1, 1, 1, 31], "百变怪")
        book = PriceBook(snapshot=self.market([(0, "egg:13:iv_spe", 6000)]))
        self.assertEqual(book.material_quote(material_record(monster))[0], 6000)

    def test_genderless_one_v_uses_genderless_market_category(self):
        monster = breeder("beldum", "N", [31, 1, 1, 1, 1, 1], "铁哑铃")
        book = PriceBook(snapshot=self.market([(0, "egg:0:iv_hp", 8000)]))
        self.assertEqual(book.material_quote(material_record(monster)), (8000, "蛋组1V行情"))

    def test_dual_group_normal_one_v_uses_lower_compatible_quote(self):
        book = PriceBook(snapshot=self.market([(0, "egg:1:iv_hp:male", 5000), (0, "egg:7:iv_hp:male", 3000)]))
        monster = breeder("bulbasaur", "M", [31, 1, 1, 1, 1, 1], "妙蛙种子")
        self.assertEqual(book.material_quote(material_record(monster))[0], 3000)

    def test_normal_multi_v_is_not_priced_as_one_v(self):
        book = PriceBook(snapshot=self.market([(0, "egg:11:iv_hp:male", 4500)]))
        monster = breeder("gengar", "M", [31, 31, 1, 1, 1, 1], "耿鬼")
        self.assertIsNone(book.material_quote(material_record(monster))[0])

    def test_manual_override_and_clear_restores_market(self):
        book = PriceBook(snapshot=self.market([(349, "alpha", 38000)]))
        row = material_record(self.alpha_material())
        book.prices[row["key"]] = 80000
        self.assertEqual(book.material_quote(row), (80000, "手动估值"))
        del book.prices[row["key"]]
        self.assertEqual(book.material_quote(row), (38000, "头目2V行情"))

    def test_stale_material_quote_is_not_automatic(self):
        book = PriceBook(snapshot=self.market([(349, "alpha", 38000)], age=90000))
        self.assertIsNone(book.material_quote(material_record(self.alpha_material()))[0])

    def test_market_prices_drive_search_and_survive_snapshot(self):
        mother = breeder("mother", "F", [31, 1, 1, 1, 1, 1])
        donor = breeder("donor", "M", [1, 31, 1, 1, 1, 1])
        book = PriceBook(snapshot=self.market([(0, "egg:12:iv_hp:female", 4000), (0, "egg:12:iv_atk:male", 5000)]))
        _text, candidates = make_report_with_candidates([mother, donor], "鲤鱼王", "", "", "31/31/x/x/x/x", ["水中2", "龙"], strategy="省钱规划", allow_ditto=False, cost_pricing=book)
        report = candidates[0].cost_report()
        self.assertEqual(report.total_known, 29000)
        self.assertEqual(report.missing, 0)
        restored = ChainCandidate.from_dict(json.loads(json.dumps(candidates[0].to_dict())))
        self.assertEqual(restored.cost_report().total_known, 29000)

    def test_new_plan_does_not_freeze_an_expired_material_quote(self):
        mother = breeder("mother", "F", [31, 1, 1, 1, 1, 1])
        donor = breeder("donor", "M", [1, 31, 1, 1, 1, 1])
        key = material_record(mother)["key"]
        book = PriceBook(dict(auto_materials={key: dict(price=4000, at=time.time()-90000, source="蛋组1V行情")}))
        _text, candidates = make_report_with_candidates([mother, donor], "鲤鱼王", "", "", "31/31/x/x/x/x", ["水中2", "龙"], strategy="cost", allow_ditto=False, cost_pricing=book)
        self.assertEqual(candidates[0].cost_pricing["auto_materials"], {})
        self.assertGreater(candidates[0].cost_report().missing, 0)

    def pair(self):
        a = leaf(breeder("a", "F", [31, 2, 3, 4, 5, 6]))
        b = leaf(breeder("b", "M", [1, 31, 3, 4, 5, 6]), True)
        root = _forced_child(a, b, SpeciesProfile("鲤鱼王", "鲤鱼王", ("水中2", "龙"), False, ("F", "M")), "F", 0, 1)
        return a, b, root

    def test_inventory_value_and_cash_are_separate(self):
        a, b, root = self.pair()
        book = PriceBook()
        book.prices[book.remember(a)["key"]] = 11000
        book.prices[book.remember(b)["key"]] = 7000
        report = book.report(root, "F")
        self.assertEqual(report.total_known, 43000)
        self.assertEqual(report.cash_known, 32000)
        self.assertEqual(report.missing, 0)
        self.assertEqual(report.steps[0]["fees"], 25000)

    def test_unknown_materials_are_not_zero_and_known_routes_rank_first(self):
        a, b, root = self.pair()
        book = PriceBook()
        report = book.report(root)
        self.assertEqual(report.missing, 2)
        self.assertIn("待报价", report.summary())
        book.prices[book.remember(a)["key"]] = 0
        book.prices[book.remember(b)["key"]] = 80000
        quoted = book.report(root)
        self.assertLess(quoted.rank(), report.rank())

    def test_unrequested_gender_is_free_at_final_step(self):
        _a, _b, root = self.pair()
        self.assertFalse(any(line.kind == "性别" for line in PriceBook().report(root).lines))

    def test_skewed_gender_requires_override(self):
        _a, _b, root = self.pair()
        root.species = "伊布"
        book = PriceBook()
        self.assertIsNone(book.gender_price(root)[0])
        book.gender_overrides["133:F"] = 21000
        self.assertEqual(book.gender_price(root)[0], 21000)

    def test_fixed_gender_has_no_fee(self):
        _a, _b, root = self.pair()
        root.species = "吉利蛋"
        self.assertEqual(PriceBook().gender_price(root)[0], 0)

    def test_stock_already_satisfying_target_is_not_consumed(self):
        a, _b, _root = self.pair()
        self.assertEqual(PriceBook().report(a).missing, 0)
        self.assertEqual(PriceBook().report(a).total_known, 0)

    def test_higher_generation_has_no_double_counted_materials(self):
        a, b, root = self.pair()
        from chain_planner import ChainAction
        second = ChainState("鲤鱼王", "F", root.egg_groups, 7, False, "", False,
                            frozenset({"a", "b", "c"}), 2, 2, 4, 0,
                            action=ChainAction(root, leaf(breeder("c", "M", [31, 1, 31, 1, 1, 1])), "防御护腕", "HP护腕"))
        book = PriceBook()
        def fill(state):
            if state.action:
                fill(state.action.parent_a)
                fill(state.action.parent_b)
            else:
                book.prices[book.remember(state)["key"]] = 1000
        fill(second)
        report = book.report(second, "F")
        self.assertEqual(sum(line.quantity for line in report.lines if line.kind in {"库存", "采购"}), 3)
        self.assertEqual(report.total_known, 53000)
        self.assertEqual(report.steps[-1]["total"], report.total_known)

    def test_price_key_protects_changed_inventory_conditions(self):
        monster = breeder("same", "F", [31, 1, 2, 3, 4, 5])
        before = material_record(monster)["key"]
        monster.nature = "固执"
        self.assertNotEqual(before, material_record(monster)["key"])

    def test_duplicate_purchase_copies_share_quote(self):
        a = breeder("buy:1", "M", [31, None, None, None, None, None])
        b = breeder("buy:2", "M", a.ivs)
        self.assertEqual(material_record(a, True)["key"], material_record(b, True)["key"])

    def test_candidate_snapshot_preserves_cost_after_price_changes(self):
        a, b, root = self.pair()
        book = PriceBook()
        book.prices[book.remember(a)["key"]] = 2000
        book.prices[book.remember(b)["key"]] = 3000
        candidate = ChainCandidate(root, [31, 31, None, None, None, None], "", "F", cost_pricing=book.to_dict())
        restored = ChainCandidate.from_dict(json.loads(json.dumps(candidate.to_dict())))
        book.prices.clear()
        self.assertEqual(restored.cost_report().total_known, 30000)

    def test_actual_search_prefers_cheaper_equivalent_inventory(self):
        expensive = breeder("expensive", "F", [31, 1, 1, 1, 1, 1])
        cheap = breeder("cheap", "F", expensive.ivs)
        donor = breeder("donor", "M", [1, 31, 1, 1, 1, 1])
        book = PriceBook()
        for monster, value in ((expensive, 90000), (cheap, 3000), (donor, 4000)):
            book.prices[material_record(monster)["key"]] = value
        _report, candidates = make_report_with_candidates([expensive, cheap, donor], "鲤鱼王", "", "", "31/31/x/x/x/x", ["水中2", "龙"], strategy="cost", allow_ditto=False, cost_pricing=book)
        self.assertTrue(candidates)
        self.assertIn("cheap", candidates[0].root.used_ids)
        self.assertNotIn("expensive", candidates[0].root.used_ids)
        self.assertEqual(candidates[0].cost_report().total_known, 27000)
        self.assertIsNone(ACTIVE_BOOK.get())

    def test_large_equivalent_stock_pruning_keeps_cheap_later_record(self):
        mothers = [breeder(f"m{i}", "F", [31, 1, 1, 1, 1, 1]) for i in range(20)]
        donor = breeder("donor", "M", [1, 31, 1, 1, 1, 1])
        book = PriceBook()
        for monster in [*mothers, donor]:
            book.prices[material_record(monster)["key"]] = 1000 if monster.id == "m19" else 90000
        _report, candidates = make_report_with_candidates([*mothers, donor], "鲤鱼王", "", "", "31/31/x/x/x/x", ["水中2", "龙"], strategy="cost", allow_ditto=False, cost_pricing=book)
        self.assertIn("m19", candidates[0].root.used_ids)

    def test_x_iv_protection_still_applies_in_cost_mode(self):
        forbidden = breeder("extra-v", "F", [31, 31, 1, 1, 1, 1])
        _report, candidates = make_report_with_candidates([forbidden], "鲤鱼王", "", "", "31/x/x/x/x/x", ["水中2", "龙"], strategy="cost", allow_ditto=False)
        self.assertTrue(all("extra-v" not in candidate.root.used_ids for candidate in candidates))

    def test_quoted_purchase_can_preserve_expensive_inventory(self):
        mother = breeder("valuable", "F", [31, 1, 1, 1, 1, 1])
        donor = breeder("donor", "M", [1, 31, 1, 1, 1, 1])
        book = PriceBook()
        book.prices[material_record(mother)["key"]] = 90000
        book.prices[material_record(donor)["key"]] = 4000
        args = ([mother, donor], "鲤鱼王", "", "", "31/31/x/x/x/x", ["水中2", "龙"])
        make_report_with_candidates(*args, strategy="cost", allow_ditto=False, cost_pricing=book)
        row = next(row for row in book.materials.values() if row["virtual"]
                   and row["conditions"]["species"] == "鲤鱼王"
                   and row["conditions"]["gender"] == "F"
                   and row["conditions"]["ivs"] == [31, None, None, None, None, None])
        book.prices[row["key"]] = 1000
        _report, candidates = make_report_with_candidates(*args, strategy="cost", allow_ditto=False, cost_pricing=book)
        self.assertNotIn("valuable", candidates[0].root.used_ids)
        self.assertEqual(candidates[0].cost_report().total_known, 25000)

    def test_quoted_multi_iv_purchase_participates(self):
        book = PriceBook()
        args = ([], "鲤鱼王", "", "", "31/31/x/x/x/x", ["水中2", "龙"])
        make_report_with_candidates(*args, strategy="cost", allow_ditto=False, cost_pricing=book)
        row = next(row for row in book.materials.values() if row["virtual"]
                   and row["conditions"]["species"] == "鲤鱼王"
                   and row["conditions"]["gender"] == "F"
                   and row["conditions"]["ivs"] == [31, 31, None, None, None, None])
        book.prices[row["key"]] = 12000
        _report, candidates = make_report_with_candidates(*args, strategy="cost", allow_ditto=False, cost_pricing=book)
        self.assertEqual(candidates[0].cost_report().total_known, 12000)
        self.assertEqual(candidates[0].root.breeds, 0)

    def test_auto_everstone_quote_and_manual_override(self):
        items = [item for item in load_catalog()["items"] if item["name"] in {"不变石", "不变之石"}]
        self.assertGreaterEqual(len(items), 1)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        snapshot = parse_snapshot(dict(items=[dict(itemId=items[0]["id"], price=7600, at=now)], pokemonQueries=[]))
        book = PriceBook(snapshot=snapshot)
        self.assertEqual(book.stone_quote()[0], 7600)
        book.everstone = 8000
        self.assertEqual(book.stone_quote()[0], 8000)

    def test_stale_auto_price_is_not_used(self):
        book = PriceBook(dict(auto_everstone=dict(price=7000, at=time.time() - 90000)))
        self.assertIsNone(book.stone_quote()[0])

    def test_historical_snapshot_keeps_planning_time_quote(self):
        book = PriceBook(dict(auto_everstone=dict(price=7000, at=time.time() - 90000), frozen=True))
        self.assertEqual(book.stone_quote(), (7000, "规划时行情快照"))

    def test_invalid_amounts_rejected_and_zero_preserved(self):
        for value in (-1, True, 1.5, "-1", "NaN", 10**13):
            with self.assertRaises(ValueError):
                amount(value)
        self.assertEqual(amount("5,000"), 5000)
        self.assertEqual(amount(0), 0)
        self.assertIsNone(amount("", optional=True))

    def test_local_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prices.json"
            book = PriceBook(dict(gender=5000, prices={"stock:example": 0}))
            save_price_book(path, book)
            self.assertEqual(load_price_book(path).prices, book.prices)
            self.assertEqual(load_price_book(path).gender, 5000)
