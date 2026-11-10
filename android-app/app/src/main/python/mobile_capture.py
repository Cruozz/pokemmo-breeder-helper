"""Parse local Android OCR lines without loading the desktop OCR runtime."""
from __future__ import annotations

import hashlib
import json
import math
import re
from uuid import uuid4

from models import Monster
from ocr_engine import OCRItem, OCRProcessor
from species_data import get_species_database


def parse_capture(lines_json: str) -> str:
    lines = json.loads(lines_json)
    if not isinstance(lines, list) or len(lines) > 1000:
        raise ValueError("识别文本过多，请选择精灵详情截图。")
    items = []
    for line in lines:
        text = str(line.get("text", ""))[:1000].strip()
        box = line.get("box")
        if not text or not isinstance(box, list) or len(box) != 4:
            continue
        if not all(isinstance(p, list) and len(p) == 2 and
                   all(type(v) in (int, float) and math.isfinite(v) for v in p) for p in box):
            continue
        items.append(OCRItem(text, 0.0, box))  # ML Kit has no calibrated cross-engine confidence.
    parsed = OCRProcessor.parse(items)
    # Mobile screenshots often contain other panels. Never accept a bare six-number row.
    labels = [item for item in items if OCRProcessor._is_iv_label(item.text)]
    has_iv_label = bool(labels)
    iv_row = [item for item in items if any(
        abs(OCRProcessor._center_y(item.box) - OCRProcessor._center_y(label.box)) <=
        max(10.0, OCRProcessor._height(item.box) * 0.8, OCRProcessor._height(label.box) * 0.8)
        for label in labels)]
    values, _ = OCRProcessor._find_individual_values(iv_row, OCRProcessor._line_text(iv_row))
    parsed["ivs"] = values or [None] * 6
    database = get_species_database()
    record = database.get(parsed["species"], fuzzy=False) if parsed["species"] else None
    if record is None:
        # Handle a split level/name line and "name Lv.50", but never guess from arbitrary prose.
        names = set()
        for item in items:
            candidate = re.sub(r"(?i)\bLv\.?\s*\d+", "", item.text)
            candidate = re.sub(r"^(?:名字|名称|名稱|种族|種族|精灵|精靈)\s*[:：]\s*", "", candidate)
            candidate = candidate.replace("♀", "").replace("♂", "").strip(" ：:")
            match = database.get(candidate, fuzzy=False) if candidate else None
            if match:
                names.add(match.display_name)
        if len(names) == 1:
            record = database.get(names.pop(), fuzzy=False)
    # Empty frames and transitions are not candidates; partial detail pages remain reviewable.
    if record is None and not has_iv_label:
        return json.dumps({"material": None, "warnings": [], "raw_text": parsed["raw_text"]}, ensure_ascii=False)
    warnings = ["请对照画面核对性别、头目、梦特及技能；未显示的字段不会自动补全。"]
    if record is None:
        warnings.append("精灵名称未确认，请手动选择。")
    if any(v is None for v in parsed["ivs"]):
        warnings.append("六项个体值未完整识别，请打开个体值详情页补录，X 代表未知。")
    if not parsed["gender"]:
        warnings.append("性别图标未识别，请手动选择。")
    if not parsed["nature"]:
        warnings.append("性格未识别。")
    material = Monster(
        id=str(uuid4()), species=record.display_name if record else "",
        gender=parsed["gender"], nature=parsed["nature"], ivs=parsed["ivs"],
        ability=parsed["ability"], moves=parsed["moves"][:4],
        egg_groups=list(record.egg_groups) if record else [],
        source="mobile-ocr", verified=False, confidence=None,
    )
    # A grouping key is not an inventory identity: identical creatures can be separate specimens.
    fingerprint = hashlib.sha256(re.sub(r"\s+", "", parsed["raw_text"]).encode()).hexdigest()
    return json.dumps({"material": material.to_dict(), "warnings": warnings,
                       "raw_text": parsed["raw_text"], "fingerprint": fingerprint}, ensure_ascii=False)
