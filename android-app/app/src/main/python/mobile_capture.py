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
from reference_data import get_reference_database, normalize_move


def parse_capture(lines_json: str, visual_gender: str = "") -> str:
    lines = json.loads(lines_json)
    if not isinstance(lines, list) or len(lines) > 1000:
        raise ValueError("识别文本过多，请选择精灵详情截图。")
    items = []
    alternatives = {}
    for line in lines:
        text = str(line.get("text", ""))[:1000].strip()
        box = line.get("box")
        if not text or not isinstance(box, list) or len(box) != 4:
            continue
        if not all(isinstance(p, list) and len(p) == 2 and
                   all(type(v) in (int, float) and math.isfinite(v) for v in p) for p in box):
            continue
        item = OCRItem(text, 0.0, box)  # ML Kit has no calibrated cross-engine confidence.
        items.append(item)
        options = line.get("alternatives", [])
        if isinstance(options, list):
            alternatives[id(item)] = [str(value)[:1000] for value in options[:8]]
    parsed = OCRProcessor.parse(items)
    if visual_gender in {"M", "F"}:
        parsed["gender"] = visual_gender
        # The colored symbol is often transcribed as a terminal 8. Only strip it
        # when image analysis actually found a gender icon on this name row.
        name, _ = OCRProcessor._species_from_level_item(items)
        name = name.rstrip(" ♀♂8")
        record, confident, _ = get_species_database().resolve_ocr_name(name, visual_gender)
        if record and confident:
            parsed["species"] = record.display_name
    # ML Kit has no per-line confidence. Use the same geometric move band,
    # explicitly without the desktop engine's calibrated confidence threshold.
    move_items = []
    for item in items:
        if re.match(r"^标记|^標記", OCRProcessor._compact(item.text)):
            x, y = OCRProcessor._left(item.box), OCRProcessor._top(item.box)
            right = min(OCRProcessor._right(item.box), x + OCRProcessor._height(item.box) * 3)
            bottom = OCRProcessor._bottom(item.box)
            item = OCRItem("标记:", item.score, [[x, y], [right, y], [right, bottom], [x, bottom]])
        move_items.append(item)
    moves, selected = OCRProcessor._find_moves(move_items, minimum_score=0.0)
    reference = get_reference_database()
    resolved_moves = []
    for move, item in zip(moves, selected[1:]):
        options = [move, *alternatives.get(id(item), [])]
        # Prefer an exact dictionary match from the same row over a noisy second
        # pass. Do not fuzzy-match short move names or silently invent skills.
        exact = next((reference.move_aliases[normalize_move(value)] for value in options
                      if normalize_move(value) in reference.move_aliases), "")
        resolved_moves.append(exact or move)
    parsed["moves"] = list(dict.fromkeys(resolved_moves))
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
            candidate = re.sub(r"(?i)\bL(?:[vw][.,，·]?|[.,，·])\s*\d+", "", item.text)
            candidate = re.sub(r"^(?:名字|名称|名稱|种族|種族|精灵|精靈)\s*[:：]\s*", "", candidate)
            candidate = candidate.replace("♀", "").replace("♂", "").strip(" ：:")
            match = database.get(candidate, fuzzy=False) if candidate else None
            if match:
                names.add(match.display_name)
        if len(names) == 1:
            record = database.get(names.pop(), fuzzy=False)
    if record and parsed["ability"]:
        abilities = reference.abilities_for_species(record.id)
        known = [a["canonical"] for values in abilities.values() for a in values]
        # The blue diamond next to the ability may be OCR'd as one trailing glyph.
        for ability in known:
            if parsed["ability"].startswith(ability) and parsed["ability"][len(ability):].strip() in {"", "北", "t", "十", "◆", "◇", "学", "令"}:
                parsed["ability"] = ability
                break
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
