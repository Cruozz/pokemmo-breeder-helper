from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image
import pytest

from app import App
from ocr_engine import OCRItem, OCRProcessor
from species_data import get_species_database


def box(left=40, top=120, right=280, bottom=140):
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


@pytest.mark.parametrize("raw", ["安飘虫'虫飞", "安飘虫'飞虫", "安飘虫'虫飞♂", "安瓢虫'虫飞", "安瓢虫'虫飞♀"])
def test_reviewed_ledian_glyph_and_type_suffix_become_a_canonical_species(raw):
    parsed = OCRProcessor.parse([OCRItem("Lv.50 " + raw, .99, box())])
    assert parsed["species"] == "安瓢虫"
    assert parsed["species_raw"].startswith(("安飘虫", "安瓢虫"))


@pytest.mark.parametrize("raw", ["拉'恶冰", "安'虫飞", "未知测试名字"])
def test_incomplete_name_is_not_returned_as_a_species(raw):
    parsed = OCRProcessor.parse([OCRItem("Lv.40 " + raw, .99, box())])
    assert parsed["species"] == ""
    assert parsed["species_raw"] == raw


def test_name_fragments_join_only_the_adjacent_level_row():
    items = [OCRItem("Lv.40", .99, box(right=95)),
             OCRItem("玛狃拉'恶冰", .98, box(left=100, right=245)),
             OCRItem("个体值:31/1/2/3/4/5", .99, box(top=175, bottom=195)),
             OCRItem("沙奈朵", .99, box(left=500, right=560))]
    assert OCRProcessor.parse(items)["species"] == "玛狃拉"
    assert OCRProcessor.parse(items)["ivs"] == [31, 1, 2, 3, 4, 5]


def engine_line(text, scale=1):
    return [box(20 * scale, 10 * scale, 220 * scale, 30 * scale), text, .99]


def recognizer(*results):
    processor = OCRProcessor.__new__(OCRProcessor)
    processor.engine = Mock(side_effect=[(rows, None) for rows in results])
    return processor


def test_unresolved_summary_name_is_retried_without_losing_iv_rows():
    processor = recognizer(
        [engine_line("Lv.40 拉'恶冰"), [box(top=175, bottom=195), "个体值:31/1/2/3/4/5", .99]],
        [engine_line("Lv.40 玛狃拉'恶冰", 2)],
        [engine_line("Lv.40 玛扭拉'恶冰", 3)])
    items = processor.recognize(Image.new("RGB", (400, 240)))
    parsed = OCRProcessor.parse(items)
    assert parsed["species"] == "玛狃拉"
    assert parsed["ivs"] == [31, 1, 2, 3, 4, 5]
    assert processor.engine.call_count == 3


def test_disagreeing_rereads_do_not_guess_between_sneasel_and_weavile():
    processor = recognizer([engine_line("Lv.40 拉'恶冰")],
                           [engine_line("Lv.40 玛狃拉'恶冰", 2)],
                           [engine_line("Lv.40 狃拉'恶冰", 3)])
    parsed = OCRProcessor.parse(processor.recognize(Image.new("RGB", (400, 240))))
    assert parsed["species"] == ""
    assert parsed["species_raw"] == "拉'恶冰"


def test_reread_from_a_different_level_is_rejected():
    processor = recognizer([engine_line("Lv.40 拉'恶冰")], [engine_line("Lv.41 玛狃拉'恶冰", 2)])
    assert OCRProcessor.parse(processor.recognize(Image.new("RGB", (400, 240))))["species"] == ""


def test_valid_name_does_not_trigger_repeated_ocr():
    processor = recognizer([engine_line("Lv.40 玛狃拉'恶冰")])
    assert OCRProcessor.parse(processor.recognize(Image.new("RGB", (400, 240))))["species"] == "玛狃拉"
    assert processor.engine.call_count == 1


def test_incomplete_form_name_cannot_be_confirmed_into_inventory():
    app = App.__new__(App)
    app.batch_running = app.batch_waiting_confirmation = True
    app.species_var = SimpleNamespace(get=lambda: "拉'恶冰")
    app.species_db = get_species_database()
    with patch("app.messagebox.showwarning") as warning:
        assert app.confirm_batch_result() is False
    warning.assert_called_once()
    assert warning.call_args.args[0] == "名字未确认"


def test_low_confidence_candidate_is_not_applied_as_a_confirmed_species():
    app = App.__new__(App)
    record = get_species_database().get("安瓢虫")
    app.species_db = SimpleNamespace(resolve_ocr_name=lambda *_args: (record, False, .8))
    assert app._resolve_ocr_species({"species": "有歧义的名字", "raw_text": ""}) == (None, False)
