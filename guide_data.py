from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import gzip
import json

from species_data import get_species_database, resource_path


STAT_LABELS = {"hp": "HP", "attack": "攻击", "defense": "防御", "sp_attack": "特攻", "sp_defense": "特防", "speed": "速度"}
TYPE_LABELS = dict(zip(
    "NORMAL FIRE WATER ELECTRIC GRASS ICE FIGHTING POISON GROUND FLYING PSYCHIC BUG ROCK GHOST DRAGON DARK STEEL FAIRY".split(),
    "一般 火 水 电 草 冰 格斗 毒 地面 飞行 超能力 虫 岩石 幽灵 龙 恶 钢 妖精".split(),
))
PERIOD_KEYS = {"清晨": "rarity_morning", "白天": "rarity_day", "夜晚": "rarity_night"}
SEASONS = ("全部季节", "春", "夏", "秋", "冬")
REGIONS = ("全部地区", "关都", "城都", "丰缘", "神奥", "合众", "黑白二")


def normalized(value: str) -> str:
    return "".join(value.casefold().split())


def ev_values(species: dict) -> dict[str, int]:
    return {key: int(species["yields"].get("ev_" + key, 0)) for key in STAT_LABELS}


def ev_text(species: dict, quantity: int = 1) -> str:
    return " / ".join(f"{STAT_LABELS[key]} +{value * quantity}" for key, value in ev_values(species).items() if value) or "无"


@dataclass(frozen=True)
class Encounter:
    species_id: int
    name: str
    region: str
    location: str
    method: str
    season: str
    quantity: int
    min_level: int
    max_level: int
    chances: tuple[tuple[str, str], ...]

    @property
    def periods(self) -> str:
        return " / ".join(period for period, _chance in self.chances) or "时段未标注"

    @property
    def level(self) -> str:
        return str(self.min_level) if self.min_level == self.max_level else f"{self.min_level}–{self.max_level}"

    @property
    def season_label(self) -> str:
        return "全年（源标任意）" if self.season == "任意" else self.season

    def available(self, season: str, period: str) -> bool:
        return (season == "全部季节" or self.season in {"任意", season}) and (
            period == "全部时段" or any(name == period for name, _chance in self.chances))


class GuideDatabase:
    def __init__(self, payload: dict) -> None:
        if payload.get("schema_version") != 1:
            raise ValueError("不支持的查询资料版本")
        self.metadata = {key: value for key, value in payload.items() if key != "species"}
        self.species = tuple(payload["species"])
        self.by_id = {record["id"]: record for record in self.species}
        if len(self.by_id) != len(self.species):
            raise ValueError("图鉴编号重复")
        self.search_names: dict[int, str] = {}
        existing = get_species_database()
        for record in self.species:
            aliases = existing.by_id.get(record["id"])
            self.search_names[record["id"]] = normalized(" ".join([
                str(record["id"]), f"{record['id']:03}", record["name"],
                *(aliases.names if aliases else ()), aliases.identifier if aliases else "",
            ]))
        encounters = []
        seen = set()
        for record in self.species:
            for location in record["locations"]:
                chances = tuple((period, str(location.get(key, ""))) for period, key in PERIOD_KEYS.items()
                                if location.get(key) not in {None, "", "--", "0%"})
                quantities = [size for size, flag in ((3, "is_horde_3x"), (5, "is_horde_5x")) if location.get(flag)] or [1]
                for quantity in quantities:
                    row = Encounter(record["id"], record["name"], location["region_name"], location["location"],
                                    location["type"], location["season"], quantity,
                                    location["min_level"], location["max_level"], chances)
                    if row not in seen:
                        seen.add(row)
                        encounters.append(row)
        self.encounters = tuple(encounters)
        self.hordes = tuple(row for row in self.encounters if row.quantity > 1)

    def find_species(self, query: str = "", pokemon_type: str = "全部属性", egg_group: str = "全部蛋组", ability: str = "") -> list[dict]:
        query = normalized(query.lstrip("#"))
        ability = normalized(ability)
        return [record for record in self.species
                if (not query or (record["id"] == int(query) if query.isdecimal() else query in self.search_names[record["id"]]))
                and (pokemon_type == "全部属性" or pokemon_type in [TYPE_LABELS.get(value, value) for value in record["types"]])
                and (egg_group == "全部蛋组" or egg_group in record["egg_groups"])
                and (not ability or any(ability in normalized(value["name"]) for value in record["abilities"]))]

    def find_encounters(
        self, query: str = "", *, region: str = "全部地区", season: str = "全部季节",
        period: str = "全部时段", quantity: str = "全部群怪", method: str = "全部方式",
        stat: str = "", single_stat: bool = False, species_id: int | None = None,
    ) -> list[Encounter]:
        tokens = query.replace("、", " ").casefold().split()
        rows = self.encounters if quantity == "全部遭遇" else self.hordes
        results = []
        for row in rows:
            if species_id is not None and row.species_id != species_id:
                continue
            if region != "全部地区" and row.region != region:
                continue
            if not row.available(season, period):
                continue
            if quantity in {"3只", "5只"} and row.quantity != int(quantity[0]):
                continue
            if method != "全部方式" and row.method != method:
                continue
            haystack = self.search_names[row.species_id] + normalized(row.location)
            if any(normalized(token) not in haystack for token in tokens):
                continue
            values = ev_values(self.by_id[row.species_id])
            if stat and not values.get(stat, 0):
                continue
            if single_stat and sum(value > 0 for value in values.values()) != 1:
                continue
            results.append(row)
        if stat:
            results.sort(key=lambda row: (-ev_values(self.by_id[row.species_id])[stat] * row.quantity, row.region, row.location, row.species_id, row.season))
        else:
            results.sort(key=lambda row: (row.region, row.location, row.species_id, row.season, row.quantity))
        return results


@lru_cache(maxsize=1)
def get_guide_database() -> GuideDatabase:
    with gzip.open(resource_path("data", "guide.json.gz"), "rt", encoding="utf-8") as stream:
        return GuideDatabase(json.load(stream))
