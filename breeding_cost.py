"""Local price book and route accounting. No inventory is sent to the market."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import time

from models import Monster

STAT_NAMES = ("HP", "攻击", "防御", "特攻", "特防", "速度")
STAT_KEYS = ("hp", "atk", "def", "spa", "spd", "spe")
MAX_PRICE = 10**12
ACTIVE_BOOK = ContextVar("breeding_price_book", default=None)


def _group_name(value):
    value = "".join(str(value).casefold().split()).removesuffix("组")
    return {"人型": "人形"}.get(value, value)


@lru_cache(maxsize=1)
def _market_families():
    from market_data import load_catalog
    catalog = load_catalog()
    index = {member["id"]: family for family, members in catalog["families"].items() for member in members}
    return catalog["families"], index


@lru_cache(maxsize=4096)
def _gender_metadata(species):
    from species_data import get_species_database
    record = get_species_database().get(species, fuzzy=True)
    return (record.id, record.allowed_genders, record.female_percent) if record else (species, (), None)


def amount(value, *, optional=False):
    if optional and (value is None or value == ""):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "").replace("，", "")
        if not value.isascii() or not value.isdigit():
            raise ValueError("请输入非负整数金额；留空表示待报价。")
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_PRICE:
        raise ValueError(f"金额须为 0 至 {MAX_PRICE:,} 的整数。")
    return value


def material_record(monster, virtual=False):
    conditions = {
        "species": monster.species, "gender": monster.gender,
        "ivs": list(monster.ivs), "nature": monster.nature,
        "groups": sorted(monster.egg_groups), "alpha": monster.is_alpha,
        "hidden": monster.has_hidden_ability, "moves": sorted(monster.moves),
    }
    signature = hashlib.sha256(json.dumps(conditions, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
    key = ("buy:" if virtual else f"stock:{monster.id}:") + signature
    sex = {"M": "雄", "F": "雌", "N": "无性别"}.get(monster.gender, "性别待确认")
    label = f"{monster.species} · {sex} · {monster.iv_string} · {monster.nature or '不限性格'}"
    if monster.is_alpha:
        label += " · 头目"
    if monster.has_hidden_ability:
        label += " · 梦特"
    if monster.moves:
        label += " · " + "/".join(monster.moves)
    return dict(key=key, label=label, virtual=virtual, conditions=conditions,
                location="待采购" if virtual else f"{monster.account} {monster.position_label}".strip())


def state_record(state):
    return material_record(state.leaf, state.is_virtual) if state.leaf else None


@dataclass
class CostLine:
    label: str
    kind: str
    quantity: int
    unit_price: int | None
    source: str
    key: str = ""

    @property
    def subtotal(self):
        return None if self.unit_price is None else self.quantity * self.unit_price


@dataclass
class CostReport:
    lines: list[CostLine] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)

    @property
    def missing(self):
        return sum(line.quantity for line in self.lines if line.unit_price is None)

    @property
    def total_known(self):
        return sum(line.subtotal or 0 for line in self.lines)

    @property
    def cash_known(self):
        return sum(line.subtotal or 0 for line in self.lines if line.kind != "库存")

    @property
    def cash_missing(self):
        return sum(line.quantity for line in self.lines if line.kind != "库存" and line.unit_price is None)

    def summary(self):
        total = f"已知 {self.total_known:,}（待报价 {self.missing} 项）" if self.missing else f"{self.total_known:,}"
        cash = f"已知 {self.cash_known:,}（待报价 {self.cash_missing} 项）" if self.cash_missing else f"{self.cash_known:,}"
        return f"总消耗价值 {total} · 还需支出 {cash}"

    def rank(self):
        # Incomplete totals are never compared as if their missing terms were free.
        return (bool(self.missing), self.missing, self.total_known)


class PriceBook:
    def __init__(self, value=None, snapshot=None):
        value = value or {}
        self.brace = amount(value.get("brace", 10000))
        self.gender = amount(value.get("gender", 5000))
        self.everstone = amount(value.get("everstone"), optional=True)
        self.gender_overrides = {str(k): amount(v) for k, v in value.get("gender_overrides", {}).items()}
        self.prices = {str(k): amount(v) for k, v in value.get("prices", {}).items()}
        self.materials = {row["key"]: row for row in value.get("materials", []) if isinstance(row, dict) and isinstance(row.get("key"), str)}
        self.snapshot = snapshot
        self.frozen = value.get("frozen") is True
        self.auto_everstone = value.get("auto_everstone")
        self.auto_materials = {}
        self._material_lookup = {}
        for key, quote in value.get("auto_materials", {}).items():
            if not isinstance(quote, dict) or not isinstance(quote.get("at"), (int, float)):
                continue
            self.auto_materials[str(key)] = dict(price=amount(quote.get("price")), at=quote["at"], source=str(quote.get("source", "行情")))
        if self.auto_everstone is not None:
            self.auto_everstone = dict(self.auto_everstone)
            self.auto_everstone["price"] = amount(self.auto_everstone.get("price"))
        if snapshot is not None:
            from market_data import load_catalog
            catalog = load_catalog()
            matches = [item for item in catalog["items"] if item["name"] in {"不变之石", "不变石"}]
            usable = [snapshot.items[item["id"]] for item in matches if item["id"] in snapshot.items]
            usable = [quote for quote in usable if quote.price is not None and not quote.stale and not snapshot.stale and quote.at is not None]
            self.auto_everstone = {"price": usable[0].price, "at": usable[0].at} if len(usable) == 1 else None

    def to_dict(self, *, include_materials=True):
        return dict(schema=1, brace=self.brace, gender=self.gender, everstone=self.everstone,
                    gender_overrides=dict(self.gender_overrides), prices=dict(self.prices),
                    auto_everstone=self.auto_everstone,
                    auto_materials=dict(self.auto_materials),
                    materials=list(self.materials.values()) if include_materials else [])

    def remember(self, state):
        row = state_record(state)
        if row is not None:
            self.materials[row["key"]] = row
        return row

    def stone_quote(self):
        if self.everstone is not None:
            return self.everstone, "手动报价"
        quote = self.auto_everstone
        if quote and isinstance(quote.get("at"), (int, float)) and (self.frozen or 0 <= time.time() - quote["at"] <= 86400):
            return quote["price"], "规划时行情快照" if self.frozen else "市场挂牌价（24 小时内）"
        return None, "待报价 / 行情已过期"

    def _market_material(self, row):
        """User-defined baseline: Alpha 2V by family; normal 1V by egg group."""
        if self.snapshot is None:
            return None
        c = row["conditions"]
        indices = [i for i, v in enumerate(c["ivs"]) if v == 31]
        from market_data import EGG_GROUPS
        from species_data import get_species_database
        species_db = get_species_database()
        record = species_db.get(c["species"], fuzzy=False)
        group_names = {_group_name(name) for name in (record.egg_groups if record else c["groups"])}
        groups = [k for k, name in EGG_GROUPS.items() if _group_name(name) in group_names]
        if c["species"].casefold() in {"百变怪", "ditto"}:
            groups = [13]
        elif c["gender"] == "N":
            groups = [0]
        sex = {"M": "male", "F": "female"}.get(c["gender"])
        quotes = []

        def usable(quote):
            return bool(quote and quote.price is not None and not quote.stale and not self.snapshot.stale
                        and quote.at is not None and 0 <= time.time() - quote.at <= 86400)

        if c["alpha"]:
            if len(indices) != 2:
                return None
            families, family_index = _market_families()
            family_ids = [family_index[record.id]] if record and record.id in family_index else []
            if not family_ids and row["virtual"] and record is None:
                # Generic purchased donors can be any compatible Alpha family.
                family_ids = [family for family, members in families.items() if any(
                    group_names & {_group_name(group) for group in member["egg_groups"]}
                    and (not c["gender"] or c["gender"] in species_db.get_by_id(member["id"]).allowed_genders)
                    for member in members
                )]
            for family in family_ids:
                keys = ["alpha_" + sex, "alpha"] if sex else ["alpha"]
                for key in keys:
                    quote = self.snapshot.queries.get((family, key))
                    if usable(quote):
                        quotes.append(dict(price=quote.price, at=quote.at, source="头目2V行情"))
                        break
        elif len(indices) == 1:
            for group in groups:
                if group not in {0, 13} and not sex:
                    continue
                key = f"egg:{group}:iv_{STAT_KEYS[indices[0]]}" + (f":{sex}" if group not in {0, 13} else "")
                quote = self.snapshot.queries.get((0, key))
                if usable(quote):
                    quotes.append(dict(price=quote.price, at=quote.at, source="蛋组1V行情"))
        return min(quotes, key=lambda quote: quote["price"]) if quotes else None

    def market_material(self, row):
        key = row["key"]
        if self.snapshot is not None and key not in self._material_lookup:
            quote = self._market_material(row)
            self._material_lookup[key] = quote
            if quote is None:
                self.auto_materials.pop(key, None)
            else:
                self.auto_materials[key] = quote
        quote = self._material_lookup.get(key) if self.snapshot is not None else self.auto_materials.get(key)
        if quote and (self.frozen or 0 <= time.time() - quote["at"] <= 86400):
            return quote
        return None

    def reference(self, row):
        quote = self.market_material(row)
        return quote["price"] if quote else None

    def material_quote(self, row):
        if row["key"] in self.prices:
            return self.prices[row["key"]], "手动估值"
        quote = self.market_material(row)
        return (quote["price"], quote["source"]) if quote else (None, "待报价")

    def gender_price(self, state):
        identifier, genders, female_percent = _gender_metadata(state.output_species)
        if genders and genders != ("F", "M") and not state.gender_species:
            return 0, "固定性别，无指定费用"
        key = f"{identifier}:{state.gender}"
        # Skewed-ratio fees must be filled in explicitly, rather than guessed.
        if key in self.gender_overrides:
            return self.gender_overrides[key], "特殊费用设置"
        if female_percent is not None and female_percent not in {0, 50, 100}:
            return None, "特殊性别比例：待填写"
        return self.gender, "默认指定性别费"

    def report(self, root, target_gender="", gender_strategy="smart", *, estimated=False):
        from chain_planner import child_gender_policy
        report = CostReport()
        if not estimated and root.action is None and not root.is_virtual:
            return report
        quantities = {}

        def add(line):
            key = (line.kind, line.key, line.label, line.unit_price, line.source)
            if key in quantities:
                quantities[key].quantity += line.quantity
            else:
                quantities[key] = line
                report.lines.append(line)

        def walk(state, sibling=None):
            start_known = report.total_known
            start_missing = report.missing
            if state.action is None:
                row = self.remember(state)
                if row:
                    price, source = self.material_quote(row)
                    add(CostLine(row["label"], "采购" if state.is_virtual else "库存", 1, price,
                                 source, row["key"]))
                return
            a, b = state.action.parent_a, state.action.parent_b
            children = [(a, b), (b, a)]
            children.sort(key=lambda pair: (pair[0].purchases > 0, pair[0].purchases, -pair[0].inventory_breeds, pair[0].breeds))
            for child, mate in children:
                walk(child, mate)
            before_fees = report.total_known
            before_fee_missing = report.missing
            braces = sum(bool(item) and item != "不变之石" for item in (state.action.item_a, state.action.item_b))
            stones = sum(item == "不变之石" for item in (state.action.item_a, state.action.item_b))
            if braces:
                add(CostLine("护腕", "道具", braces, self.brace, "固定费用设置"))
            if stones:
                price, source = self.stone_quote()
                add(CostLine("不变之石", "道具", stones, price, source))
            # During beam pruning, assume a usable sex for the unfinished root;
            # final comparison always uses the candidate's actual execution policy.
            policy = child_gender_policy(state, root, target_gender or (state.gender if estimated else ""), gender_strategy, sibling)
            if policy == "locked":
                price, source = self.gender_price(state)
                from species_data import get_species_database
                record = get_species_database().get(state.output_species, fuzzy=True)
                key = f"gender:{record.id if record else state.output_species}:{state.gender}"
                add(CostLine(f"{state.output_species} 指定{'雌性' if state.gender == 'F' else '雄性'}", "性别", 1, price, source, key))
            report.steps.append(dict(number=len(report.steps) + 1, label=state.output_species,
                                     fees=report.total_known - before_fees,
                                     fee_missing=report.missing - before_fee_missing,
                                     total=report.total_known - start_known,
                                     missing=report.missing - start_missing))

        walk(root)
        return report


def cost_state_rank(state, target_gender=None, gender_strategy="smart"):
    book = ACTIVE_BOOK.get()
    if book is None:
        return (1, 1, state.item_cost)
    if target_gender is not None:
        return book.report(state, target_gender, gender_strategy).rank()
    cached = getattr(state, "_cost_rank_cache", None)
    if cached is None or cached[0] is not book:
        if state.action is None:
            row = book.remember(state)
            price = book.material_quote(row)[0] if row else None
            missing, known = int(price is None), price or 0
        else:
            left = cost_state_rank(state.action.parent_a)
            right = cost_state_rank(state.action.parent_b)
            missing, known = left[1] + right[1], left[2] + right[2]
            for item in (state.action.item_a, state.action.item_b):
                if item == "不变之石":
                    price, _source = book.stone_quote()
                    missing += int(price is None)
                    known += price or 0
                elif item:
                    known += book.brace
            if state.gender in {"F", "M"}:
                price, _source = book.gender_price(state)
                missing += int(price is None)
                known += price or 0
        cached = (book, (bool(missing), missing, known))
        state._cost_rank_cache = cached
    return cached[1]


def cost_search(function):
    @wraps(function)
    def wrapped(*args, cost_pricing=None, **kwargs):
        book = cost_pricing if isinstance(cost_pricing, PriceBook) else PriceBook(cost_pricing)
        token = ACTIVE_BOOK.set(book)
        try:
            candidates, missing = function(*args, **kwargs)
            for candidate in candidates:
                report = book.report(candidate.root, candidate.working_gender or candidate.target_gender, candidate.gender_strategy)
                used_keys = {line.key for line in report.lines if line.key}
                snapshot = book.to_dict(include_materials=False)
                # Resolve freshness now; an activated historical estimate must
                # retain this quote after the live quote expires.
                snapshot["auto_everstone"] = book.auto_everstone if book.stone_quote()[0] is not None else None
                snapshot["frozen"] = True
                snapshot["prices"] = {k: v for k, v in book.prices.items() if k in used_keys}
                auto_keys = {line.key for line in report.lines if line.key and line.unit_price is not None and line.key not in book.prices}
                snapshot["auto_materials"] = {k: v for k, v in book.auto_materials.items() if k in auto_keys}
                candidate.cost_pricing = snapshot
                candidate.cost_materials = list(book.materials.values())
            return candidates, missing
        finally:
            ACTIVE_BOOK.reset(token)
    return wrapped


def load_price_book(path):
    try:
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("报价文件过大")
        return PriceBook(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return PriceBook()


def save_price_book(path, book):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(book.to_dict(), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)
