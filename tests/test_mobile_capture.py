"""Mobile OCR uses recorded geometry and never silently verifies inventory."""
import importlib.util
import json
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "android-app/app/src/main/python/mobile_capture.py"
spec = importlib.util.spec_from_file_location("mobile_capture", MODULE)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


def line(text, y, x=10, width=220):
    return dict(text=text, box=[[x, y], [x+width, y], [x+width, y+20], [x, y+20]])


def parse(*lines):
    return json.loads(capture.parse_capture(json.dumps(lines, ensure_ascii=False)))


def test_labeled_iv_row_wins_over_ability_and_effort_values():
    result = parse(line("Lv.1 蘑蘑菇 ♀", 20), line("能力值：12/5/6/5/6/5", 60),
                   line("个体值：", 100, width=70), line("26/2/19/0/16/6", 100, x=100),
                   line("努力值：0/0/0/0/0/0", 140), line("性格：坦率Docile", 180))
    m = result["material"]
    assert m["species"] == "蘑蘑菇"
    assert m["ivs"] == [26, 2, 19, 0, 16, 6]
    assert m["gender"] == "F"
    assert m["nature"] == "坦率"
    assert m["verified"] is False
    assert m["source"] == "mobile-ocr"
    assert m["confidence"] is None
    assert not m["is_alpha"] and not m["has_hidden_ability"]
    assert m["page"] == m["slot"] == ""
    assert result["warnings"]


@pytest.mark.parametrize("title", ["蘑蘑菇", "蘑蘑菇 Lv.50", "名称：蘑蘑菇"])
def test_split_and_reversed_name_lines_can_be_reviewed(title):
    result = parse(line(title, 20), line("个体值：31/2/19/0/16/6", 100))
    assert result["material"]["species"] == "蘑蘑菇"
    assert result["material"]["gender"] == ""
    assert not result["material"]["verified"]


@pytest.mark.parametrize("extra", [[], [line("个体值：", 160)]])
def test_unlabeled_or_misaligned_numeric_row_is_never_guessed(extra):
    result = parse(line("Lv.1 蘑蘑菇", 20), line("能力值：12/5/6/5/6/5", 60), *extra)
    assert result["material"]["ivs"] == [None] * 6


def test_partial_iv_screen_is_kept_for_manual_name_selection():
    result = parse(line("个体值：31/31/31/0/0/31", 20))
    assert result["material"]["species"] == ""
    assert result["material"]["ivs"] == [31, 31, 31, 0, 0, 31]


def test_blank_and_gameplay_frames_are_skipped():
    assert parse()["material"] is None
    assert parse(line("交易行", 20), line("金币 123456", 60))["material"] is None


def test_ocr_identity_is_not_inventory_identity():
    a, b = [parse(line("Lv.1 蘑蘑菇", 20), line("个体值：31/1/2/3/4/5", 100)) for _ in range(2)]
    assert a["fingerprint"] == b["fingerprint"]
    assert a["material"]["id"] != b["material"]["id"]
    assert a["material"]["scan_fingerprint"] == ""  # Never auto-merge different specimens.


def test_bad_geometry_and_excessive_input_are_rejected_safely():
    result = parse(dict(text="Lv.1 蘑蘑菇", box=[[float("nan"), 0]] * 4))
    assert result["material"] is None
    with pytest.raises(ValueError):
        capture.parse_capture(json.dumps([line("text", 0)] * 1001))
