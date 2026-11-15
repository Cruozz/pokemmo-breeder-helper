import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from ocr_engine import OCRItem, OCRProcessor
from scripts.build_species_ocr_types import build
from species_data import SpeciesDatabase, get_species_database


def test_every_canonical_name_and_alias_still_resolves_exactly():
    database = get_species_database()
    for record in database.records:
        for name in record.names:
            resolved, confident, score = database.resolve_ocr_name(name)
            assert resolved == database.get(name)
            assert confident and score == 1.0, name
    assert database.get("Raltss", fuzzy=True).id == 280
    assert database.find_in_text("arbitrary ralts prose") is None


def test_incomplete_name_has_type_narrowed_suggestions_without_becoming_confirmed():
    database = get_species_database()
    for raw in ("拉'恶冰", "Lv.40 拉'冰恶♀", "拉'恶冰♂"):
        assert database.resolve_ocr_name(raw)[0] is None
        assert {record.id for record in database.ocr_name_candidates(raw)} == {215, 461}
    assert database.resolve_ocr_name("安飘虫'虫飞")[0].id == 166
    assert database.ocr_name_candidates("安飘虫'虫飞")[0].id == 166


def test_type_context_never_promotes_a_candidate_to_an_automatic_correction():
    database = get_species_database()
    with patch.object(database, "_ocr_types", {461: frozenset({"DARK", "ICE"})}):
        assert [record.id for record in database.ocr_name_candidates("拉'恶冰")] == [461]
        assert database.resolve_ocr_name("拉'恶冰")[1] is False


def test_dictionary_cache_covers_matches_and_misses_with_gender_in_the_key():
    database = get_species_database()
    database.resolve_ocr_name.cache_clear()
    for raw in ("安瓢虫'虫飞", "安飘虫'虫飞", "拉'恶冰", "未知测试名字"):
        first = database.resolve_ocr_name(raw, "F")
        before = database.resolve_ocr_name.cache_info()
        assert database.resolve_ocr_name(raw, "F") == first
        assert database.resolve_ocr_name.cache_info().hits == before.hits + 1
        database.resolve_ocr_name(raw, "M")
        assert database.resolve_ocr_name.cache_info().misses == before.misses + 1
    assert database.resolve_ocr_name.cache_info().maxsize == 2048
    assert database._rank_ocr_names.cache_info().maxsize == 128


def test_suggestions_are_bounded_immutable_and_ignore_garbage():
    database = get_species_database()
    assert isinstance(database.ocr_name_candidates("拉"), tuple)
    assert len(database.ocr_name_candidates("拉", limit=100)) <= 5
    assert database.ocr_name_candidates("安瓢虫", limit=0) == ()
    for raw in ("", "!", "1234", "xyz", "未知测试名字", "拉" * 41):
        assert database.ocr_name_candidates(raw) == (), raw


def test_optional_candidate_index_is_reproducible_and_complete():
    root = Path(__file__).resolve().parents[1]
    source = (root / "data/guide.json.gz").read_bytes()
    index = json.loads((root / "data/species_ocr_types.json").read_text(encoding="utf-8"))
    assert index == build(source)
    assert index["source_sha256"] == hashlib.sha256(source).hexdigest()
    assert len(index["types"]) == 649


def test_missing_catalog_and_missing_optional_index_degrade_safely(tmp_path):
    database = SpeciesDatabase(tmp_path / "missing.json")
    assert database.resolve_ocr_name("拉'恶冰") == (None, False, 0.0)
    assert database.ocr_name_candidates("拉'恶冰") == ()
    source = Path(__file__).resolve().parents[1] / "data/species.json"
    target = tmp_path / "species.json"
    target.write_bytes(source.read_bytes())
    database = SpeciesDatabase(target)
    assert database.resolve_ocr_name("玛狃拉'恶冰")[0].id == 461
    assert database.ocr_name_candidates("拉'恶冰")
    assert database.resolve_ocr_name("拉'恶冰")[1] is False


def test_parser_returns_fresh_candidate_lists_without_leaking_cached_results():
    box = [[30, 120], [270, 120], [270, 140], [30, 140]]
    items = [OCRItem("Lv.40 拉'恶冰", .99, box)]
    first = OCRProcessor.parse(items)
    assert first["species"] == ""
    assert set(first["species_candidates"]) == {"狃拉", "玛狃拉"}
    first["species_candidates"].clear()
    assert len(OCRProcessor.parse(items)["species_candidates"]) == 2
    assert OCRProcessor.parse([OCRItem("Lv.40 玛狃拉'恶冰", .99, box)])["species_candidates"] == []
