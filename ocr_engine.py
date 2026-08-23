from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import numpy as np


NATURES = {
    "adamant", "大胆", "bashful", "害羞", "bold", "大胆", "brave", "勇敢",
    "calm", "沉着", "careful", "慎重", "docile", "温顺", "gentle", "温和",
    "hardy", "勤奋", "hasty", "急躁", "impish", "淘气", "jolly", "爽朗",
    "lax", "松懈", "lonely", "孤独", "mild", "温和", "modest", "内敛",
    "naive", "天真", "naughty", "顽皮", "quiet", "冷静", "rash", "马虎",
    "relaxed", "悠闲", "sassy", "自大", "serious", "认真", "timid", "胆小",
}


@dataclass
class OCRItem:
    text: str
    score: float
    box: Any = None


class OCRProcessor:
    def __init__(self) -> None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise RuntimeError("缺少 rapidocr_onnxruntime，请重新运行构建脚本。") from exc
        self.engine = RapidOCR()

    def recognize(self, image) -> list[OCRItem]:
        array = np.asarray(image.convert("RGB"))
        result, _elapsed = self.engine(array)
        items: list[OCRItem] = []
        for item in result or []:
            if len(item) < 3:
                continue
            try:
                items.append(OCRItem(str(item[1]), float(item[2]), item[0]))
            except (TypeError, ValueError):
                continue
        return items

    @staticmethod
    def _line_text(items: list[OCRItem]) -> str:
        if not items:
            return ""
        sorted_items = sorted(items, key=lambda x: (OCRProcessor._top(x.box), OCRProcessor._left(x.box)))
        rows: list[list[OCRItem]] = []
        for item in sorted_items:
            top = OCRProcessor._top(item.box)
            height = OCRProcessor._height(item.box)
            tolerance = max(8.0, height * 0.65)
            row = next((row for row in rows if abs(OCRProcessor._top(row[0].box) - top) <= tolerance), None)
            if row is None:
                rows.append([item])
            else:
                row.append(item)
        lines: list[str] = []
        for row in sorted(rows, key=lambda r: OCRProcessor._top(r[0].box)):
            lines.append(" ".join(x.text.strip() for x in sorted(row, key=lambda x: OCRProcessor._left(x.box))))
        return "\n".join(lines)

    @staticmethod
    def _left(box: Any) -> float:
        try:
            return min(float(point[0]) for point in box)
        except Exception:
            return 0.0

    @staticmethod
    def _top(box: Any) -> float:
        try:
            return min(float(point[1]) for point in box)
        except Exception:
            return 0.0

    @staticmethod
    def _height(box: Any) -> float:
        try:
            ys = [float(point[1]) for point in box]
            return max(ys) - min(ys)
        except Exception:
            return 12.0

    @staticmethod
    def _after_label(lines: list[str], labels: tuple[str, ...]) -> str:
        for line in lines:
            for label in labels:
                if label in line:
                    value = line.split(label, 1)[1].lstrip(" :：")
                    if value:
                        return value.strip()
        return ""

    @staticmethod
    def parse(items: list[OCRItem]) -> dict[str, Any]:
        lines_text = OCRProcessor._line_text(items)
        compact = lines_text.replace("／", "/").replace("|", "/").replace(" ", "")

        ivs: list[int] | None = None
        pattern = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{1,2})/(\d{1,2})/(\d{1,2})/(\d{1,2})(?!\d)")
        for match in pattern.finditer(compact):
            values = [int(x) for x in match.groups()]
            if all(0 <= value <= 31 for value in values):
                ivs = values
                break

        lines = [line.strip() for line in lines_text.splitlines() if line.strip()]
        nature = OCRProcessor._after_label(lines, ("性格", "Nature", "nature"))
        if not nature:
            for line in lines:
                lowered = line.lower()
                if any(name in lowered for name in NATURES):
                    nature = line
                    break

        species = ""
        for line in lines:
            if re.search(r"\bLv\.?\s*\d+", line, flags=re.IGNORECASE) or "等级" in line:
                species = re.sub(r"\s*Lv\.?\s*\d+", "", line, flags=re.IGNORECASE).strip()
                species = species.replace("等级", "").strip(" ：:")
                break

        gender = ""
        if "♂" in lines_text or "雄性" in lines_text:
            gender = "M"
        elif "♀" in lines_text or "雌性" in lines_text:
            gender = "F"

        ability = OCRProcessor._after_label(lines, ("特性", "Ability", "ability"))
        held_item = OCRProcessor._after_label(lines, ("持有道具", "Held Item", "Item"))
        return {
            "species": species,
            "gender": gender,
            "nature": nature,
            "ivs": ivs or [None] * 6,
            "ability": ability,
            "held_item": held_item,
            "raw_text": lines_text,
            "items": items,
            "confidence": min((item.score for item in items), default=0.0),
        }
