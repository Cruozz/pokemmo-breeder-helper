from __future__ import annotations

import itertools
import re
from dataclasses import dataclass

from models import Monster, normalize_gender


STAT_NAMES = ("HP", "攻击", "防御", "特攻", "特防", "速度")

NATURE_ALIASES = {
    "adamant": "adamant", "固执": "adamant",
    "bashful": "bashful", "害羞": "bashful",
    "bold": "bold", "大胆": "bold",
    "brave": "brave", "勇敢": "brave",
    "calm": "calm", "沉着": "calm",
    "careful": "careful", "慎重": "careful",
    "docile": "docile", "温顺": "docile", "坦率": "docile",
    "gentle": "gentle", "温和": "gentle",
    "hardy": "hardy", "勤奋": "hardy",
    "hasty": "hasty", "急躁": "hasty",
    "impish": "impish", "淘气": "impish",
    "jolly": "jolly", "爽朗": "jolly",
    "lax": "lax", "松懈": "lax",
    "lonely": "lonely", "孤独": "lonely", "怕寂寞": "lonely",
    "mild": "mild",
    "modest": "modest", "内敛": "modest",
    "naive": "naive", "天真": "naive",
    "naughty": "naughty", "顽皮": "naughty",
    "quiet": "quiet", "冷静": "quiet",
    "rash": "rash", "马虎": "rash",
    "relaxed": "relaxed", "悠闲": "relaxed",
    "sassy": "sassy", "自大": "sassy",
    "serious": "serious", "认真": "serious",
    "timid": "timid", "胆小": "timid",
    "quirky": "quirky", "浮躁": "quirky",
}


def parse_iv_requirements(value: str) -> list[int | None]:
    parts = re.split(r"[/,，\s]+", (value or "").strip())
    result: list[int | None] = []
    for part in parts[:6]:
        token = part.strip().lower()
        if token in {"", "x", "any", "任意", "-", "—", "?"}:
            result.append(None)
        else:
            try:
                number = int(token)
            except ValueError:
                result.append(None)
            else:
                result.append(number if 0 <= number <= 31 else None)
    return result + [None] * max(0, 6 - len(result))


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip().lower())


def normalize_nature(value: str) -> str:
    compact = normalize_text(value)
    if not compact:
        return ""
    if compact in NATURE_ALIASES:
        return NATURE_ALIASES[compact]
    for alias, canonical in NATURE_ALIASES.items():
        if alias in compact:
            return canonical
    return compact


def shares_egg_group(a: Monster, b: Monster, target_groups: list[str]) -> bool:
    a_groups = {normalize_text(x) for x in a.egg_groups}
    b_groups = {normalize_text(x) for x in b.egg_groups}
    if normalize_text(a.species) == "ditto" or normalize_text(b.species) == "ditto":
        return normalize_text(a.species) != "ditto" or normalize_text(b.species) != "ditto"
    if not a_groups or not b_groups:
        if target_groups:
            return bool(a_groups & {normalize_text(x) for x in target_groups}) or bool(
                b_groups & {normalize_text(x) for x in target_groups}
            )
        return False
    return bool(a_groups & b_groups)


def target_iv_guaranteed(a: Monster, b: Monster, target: list[int | None], brace_a: int | None, brace_b: int | None) -> list[bool]:
    result: list[bool] = []
    for index, required in enumerate(target):
        if required is None:
            result.append(True)
            continue
        shared = a.ivs[index] == required and b.ivs[index] == required
        braced = (brace_a == index and a.ivs[index] == required) or (brace_b == index and b.ivs[index] == required)
        result.append(shared or braced)
    return result


@dataclass
class Candidate:
    a: Monster
    b: Monster
    nature_holder: Monster | None
    brace_a: int | None
    brace_b: int | None
    cost: int
    guaranteed: list[bool]

    def description(self, target_gender: str) -> str:
        items: list[str] = []
        if self.nature_holder:
            items.append(f"Everstone → {self.nature_holder.species} {self.nature_holder.gender}")
        if self.brace_a is not None:
            items.append(f"Brace({STAT_NAMES[self.brace_a]}) → {self.a.species}")
        if self.brace_b is not None:
            items.append(f"Brace({STAT_NAMES[self.brace_b]}) → {self.b.species}")
        if target_gender in {"M", "F"}:
            items.append(f"子代选择{'雄性' if target_gender == 'M' else '雌性'}")
        item_text = "；".join(items) if items else "无需强制道具"
        return (
            f"父代 A：{self.a.species} {self.a.gender} {self.a.iv_string} {self.a.nature or '性格未知'}\n"
            f"父代 B：{self.b.species} {self.b.gender} {self.b.iv_string} {self.b.nature or '性格未知'}\n"
            f"操作：{item_text}\n"
            f"保证结果：{self.cost:,} 金币估算；{', '.join(STAT_NAMES[i] for i, ok in enumerate(self.guaranteed) if ok)}"
        )


def find_candidates(
    inventory: list[Monster],
    species: str,
    target_gender: str,
    nature: str,
    iv_string: str,
    egg_groups: list[str],
    max_results: int = 8,
) -> tuple[list[Candidate], list[str]]:
    species_key = normalize_text(species)
    target_gender = normalize_gender(target_gender) or ""
    target_ivs = parse_iv_requirements(iv_string)
    nature_key = normalize_nature(nature)
    missing: list[str] = []

    females = [m for m in inventory if normalize_gender(m.gender) == "F" and normalize_text(m.species) == species_key]
    if not females:
        missing.append(f"目标种类 {species or '未填写'} 的雌性母体")

    possible_males = [m for m in inventory if normalize_gender(m.gender) == "M" or normalize_text(m.species) == "ditto"]
    pairs = [(a, b) for a in females for b in possible_males if a.id != b.id and shares_egg_group(a, b, egg_groups)]
    if not pairs and females:
        missing.append("与目标母体兼容的雄性蛋组素材或 Ditto（请为素材填写蛋组）")

    candidates: list[Candidate] = []
    for a, b in pairs:
        nature_holders: list[Monster | None]
        if nature_key:
            nature_holders = [m for m in (a, b) if normalize_nature(m.nature) == nature_key]
            if not nature_holders:
                continue
        else:
            nature_holders = [None]

        for nature_holder in nature_holders:
            allowed_a = [None] if nature_holder is a else [None] + [i for i, value in enumerate(target_ivs) if value is not None and a.ivs[i] == value]
            allowed_b = [None] if nature_holder is b else [None] + [i for i, value in enumerate(target_ivs) if value is not None and b.ivs[i] == value]
            for brace_a, brace_b in itertools.product(allowed_a, allowed_b):
                if brace_a is not None and brace_b is not None and brace_a == brace_b:
                    continue
                guaranteed = target_iv_guaranteed(a, b, target_ivs, brace_a, brace_b)
                if not all(guaranteed):
                    continue
                cost = 10_000 * sum(x is not None for x in (brace_a, brace_b))
                cost += 5_000 if nature_holder else 0
                cost += 5_000 if target_gender in {"M", "F"} else 0
                candidates.append(Candidate(a, b, nature_holder, brace_a, brace_b, cost, guaranteed))

    if nature_key and not candidates and pairs:
        missing.append(f"性格为 {nature or '目标性格'} 且可以携带 Everstone 的兼容素材")

    for index, required in enumerate(target_ivs):
        if required is None or any(candidate.guaranteed[index] for candidate in candidates):
            continue
        missing.append(f"{STAT_NAMES[index]} IV={required} 的可兼容父代素材；或准备两只共享该 IV 的父代")

    candidates.sort(key=lambda item: (item.cost, sum(x is not None for x in (item.brace_a, item.brace_b))))
    return candidates[:max_results], list(dict.fromkeys(missing))


def make_report(
    inventory: list[Monster],
    species: str,
    target_gender: str,
    nature: str,
    iv_string: str,
    egg_groups: list[str],
) -> str:
    if not species.strip():
        return "请先填写目标种类。"
    candidates, missing = find_candidates(inventory, species, target_gender, nature, iv_string, egg_groups)
    lines = [
        "当前版本：严格保证模式 / 直接配对规划",
        "说明：只使用库存中已经确认的素材，不把随机 IV 当成保证结果。",
        "",
    ]
    if candidates:
        lines.append(f"找到 {len(candidates)} 个可行的直接方案，按估算消耗排序：")
        lines.append("")
        for index, candidate in enumerate(candidates, 1):
            lines.append(f"方案 {index}（估算 {candidate.cost:,} 金币）")
            lines.append(candidate.description(target_gender))
            lines.append("")
    else:
        lines.append("当前库存没有找到能保证目标结果的直接配对。")
        lines.append("")

    if missing:
        lines.append("需要补充或继续链式孵蛋的素材：")
        lines.extend(f"- {item}" for item in missing)
    else:
        lines.append("没有发现额外缺口。")

    lines.append("")
    lines.append("提示：当前版本先覆盖直接配对；完整的多代链式规划、蛋招式、Alpha/隐藏特性会在下一阶段加入。")
    return "\n".join(lines)
