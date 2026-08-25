from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NatureInfo:
    english: str
    chinese: str
    increased: str = ""
    decreased: str = ""

    @property
    def effect(self) -> str:
        if not self.increased or not self.decreased:
            return "无属性增减"
        return f"{self.increased} +10%，{self.decreased} -10%"


# Chinese names follow the translations used by PokeMMO's Chinese client.
# Neutral natures are retained because users may want to reproduce an existing
# Pokémon exactly even though they do not change battle stats.
NATURES: tuple[NatureInfo, ...] = (
    NatureInfo("Hardy", "勤奋"),
    NatureInfo("Lonely", "怕寂寞", "攻击", "防御"),
    NatureInfo("Brave", "勇敢", "攻击", "速度"),
    NatureInfo("Adamant", "固执", "攻击", "特攻"),
    NatureInfo("Naughty", "顽皮", "攻击", "特防"),
    NatureInfo("Bold", "大胆", "防御", "攻击"),
    NatureInfo("Docile", "坦率"),
    NatureInfo("Relaxed", "悠闲", "防御", "速度"),
    NatureInfo("Impish", "淘气", "防御", "特攻"),
    NatureInfo("Lax", "乐天", "防御", "特防"),
    NatureInfo("Timid", "胆小", "速度", "攻击"),
    NatureInfo("Hasty", "急躁", "速度", "防御"),
    NatureInfo("Serious", "认真"),
    NatureInfo("Jolly", "爽朗", "速度", "特攻"),
    NatureInfo("Naive", "天真", "速度", "特防"),
    NatureInfo("Modest", "内敛", "特攻", "攻击"),
    NatureInfo("Mild", "慢吞吞", "特攻", "防御"),
    NatureInfo("Quiet", "冷静", "特攻", "速度"),
    NatureInfo("Bashful", "害羞"),
    NatureInfo("Rash", "马虎", "特攻", "特防"),
    NatureInfo("Calm", "温和", "特防", "攻击"),
    NatureInfo("Gentle", "温顺", "特防", "防御"),
    NatureInfo("Sassy", "自大", "特防", "速度"),
    NatureInfo("Careful", "慎重", "特防", "特攻"),
    NatureInfo("Quirky", "浮躁"),
)

NATURE_BY_ENGLISH = {nature.english.lower(): nature for nature in NATURES}
NATURE_BY_CHINESE = {nature.chinese: nature for nature in NATURES}

NEUTRAL_TARGET_NAME = "无修正（任一）"
NEUTRAL_NATURES = tuple(nature for nature in NATURES if not nature.increased and not nature.decreased)
PLANNER_NATURES = tuple(nature for nature in NATURES if nature.increased and nature.decreased)


def find_nature(value: str) -> NatureInfo | None:
    query = (value or "").strip()
    return NATURE_BY_CHINESE.get(query) or NATURE_BY_ENGLISH.get(query.lower())


def is_neutral_nature(value: str) -> bool:
    query = (value or "").strip().lower()
    if query in {NEUTRAL_TARGET_NAME.lower(), "无修正", "无属性增减", "neutral"}:
        return True
    nature = find_nature(value)
    return bool(nature and not nature.increased and not nature.decreased)
