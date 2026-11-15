from dataclasses import replace
import json
import uuid

from PIL import Image, ImageDraw
import pytest

from bulk_ocr import BulkResult, BulkRow, combine, next_batch_range, parse_release, prepare_inventory, patch_inventory_records, read_warehouse, slot_range, validate_roi
from bulk_session import BulkSessionStore
from models import Monster
from ocr_engine import OCRItem


def item(text,x,y,width=168):
    return OCRItem(text,.99,[[x,y],[x+width,y],[x+width,y+20],[x,y+20]])


def ready(index=1,slot=8,**changes):
    return replace(BulkRow(index,species="玛狃拉",level=40,warehouse_level=40,slot=slot,gender="M",ivs=[31,1,2,3,4,5],
                           hidden_ability=False,nature="",is_alpha=False,has_particles=False,is_costume=False,reviewed=True),**changes)


def test_list_parser_orders_cells_and_keeps_identical_names_separate():
    image = Image.new("RGB",(700,250),(50,60,65))
    items = [item("Lv.40 路卡利欧'斗钢",350,50),item("2/3/4/5/6/7",355,75),
             item("Lv.40 路卡利欧'斗钢",70,50),item("1/2/3/4/5/6",75,75)]
    rows = parse_release(image,list(reversed(items)))
    assert len(rows)==2 and [row.species for row in rows]==["路卡利欧"]*2
    assert [row.ivs for row in rows]==[[1,2,3,4,5,6],[2,3,4,5,6,7]]
    assert all(row.nature is None and row.has_particles is None and row.is_costume is None and not row.reviewed for row in rows)


def test_badge_detector_excludes_the_next_column_sprite_and_green_star():
    image = Image.new("RGB",(700,460),(50,60,65))
    draw = ImageDraw.Draw(image)
    # This blue square is the next column's sprite, inside the old broad search.
    draw.rectangle((319,60,329,70),fill=(40,200,250))
    # The star is green, unlike a cyan HA diamond.
    draw.polygon([(530,55),(534,62),(541,65),(534,68),(530,75),(526,68),(519,65),(526,62)],fill=(80,230,150))
    items = [item("Lv.40 路卡利欧'斗钢",70,50),item("1/2/3/4/5/6",75,75),
             item("Lv.40 猫老大'普",350,50,158),item("2/3/4/5/6/7",355,75)]
    rows = parse_release(image,items)
    assert [row.hidden_ability for row in rows]==[False,False]
    draw.polygon([(530,55),(540,65),(530,75),(520,65)],fill=(40,200,250))
    assert parse_release(image,items)[1].hidden_ability is True


@pytest.mark.parametrize("missing",["name","iv"])
def test_missing_line_keeps_a_placeholder_instead_of_shifting_other_records(missing):
    image = Image.new("RGB",(700,230))
    names = [item("Lv.40 玛狃拉'恶冰",70,50),item("Lv.40 路卡利欧'斗钢",350,50)]
    ivs = [item("1/2/3/4/5/6",75,75),item("2/3/4/5/6/7",355,75)]
    rows = parse_release(image,[*names[1 if missing=="name" else 0:],*ivs[1 if missing=="iv" else 0:]])
    assert len(rows)==2
    assert rows[1].species=="路卡利欧" and rows[1].ivs==[2,3,4,5,6,7]
    assert rows[0].species=="" if missing=="name" else rows[0].ivs==[None]*6


def test_name_fragments_are_joined_only_inside_the_same_cell():
    image = Image.new("RGB",(700,180))
    rows = parse_release(image,[item("Lv.40",70,50,60),item("玛狃拉'恶冰",135,50,100),item("1/2/3/4/5/6",75,75)])
    assert rows[0].species=="玛狃拉"


@pytest.mark.parametrize("page,start,count",[(0,1,20),(1,0,20),(1,1,21),(1,50,20),(1,1,0),(True,1,20),(1,1.5,20)])
def test_invalid_or_cross_page_ranges_are_rejected(page,start,count):
    with pytest.raises(ValueError):slot_range(page,start,count)


def test_range_can_cross_rows_but_keeps_exact_physical_slots():
    assert slot_range(6,8,20)==list(range(8,28))
    assert slot_range(6,60,1)==[60]


@pytest.mark.parametrize("page,start,count,preferred,expected",[
    (3,1,20,20,(3,21,20)),(3,21,20,20,(3,41,20)),(3,41,20,20,(4,1,20)),
    (3,31,20,20,(3,51,10)),(3,51,10,20,(4,1,20)),(3,8,5,5,(3,13,5)),
])
def test_next_batch_follows_the_last_slot_and_clamps_at_page_end(page,start,count,preferred,expected):
    assert next_batch_range(page,start,count,preferred)==expected


def test_next_batch_cannot_overflow_last_page_or_accept_bad_batch_size():
    with pytest.raises(ValueError):next_batch_range(999,41,20,20)
    with pytest.raises(ValueError):next_batch_range(3,1,20,21)


def test_count_or_highlight_mismatch_leaves_all_positions_unassigned():
    cells=[dict(slot=i+8,gender="M",level=40) for i in range(2)]
    for count,highlights in ((1,[]),(2,[8,10])):
        result=combine([ready(1,8),ready(2,9)],cells,6,8,count,highlights)
        assert result.blockers and all(row.slot is None and row.gender=="" for row in result.rows)


def test_warehouse_level_mismatch_cannot_be_confirmed_without_manual_position_review():
    result=combine([ready()],[dict(slot=8,gender="M",level=41)],6,8,1)
    assert "仓库等级需核对" in result.rows[0].problems()
    result.rows[0].position_reviewed=True
    assert not result.rows[0].problems()


def test_absent_gender_is_not_automatically_genderless():
    row=combine([ready()],[dict(slot=8,gender="",level=40)],6,8,1).rows[0]
    assert row.gender=="" and "性别待核对" in row.problems()
    row=combine([ready(species="百变怪")],[dict(slot=8,gender="",level=40)],6,8,1).rows[0]
    assert row.gender=="N"


@pytest.mark.parametrize("field",["nature","is_alpha","has_particles","is_costume","hidden_ability"])
def test_unseen_optional_fields_can_enter_inventory_without_becoming_reviewed(field):
    row=ready(reviewed=False,**{field:None})
    result=BulkResult([row])
    combined,_=prepare_inventory(result,"test","主账号",6,[1],[],False)
    assert not combined[0].verified and combined[0].usable_unreviewed and combined[0].planner_usable
    assert ("has_hidden_ability" if field=="hidden_ability" else field) in combined[0].unreviewed_fields


def test_no_manual_review_or_optional_fields_are_required_to_save_a_scan():
    for row,order in ((ready(reviewed=False),True),(ready(species="拉'恶冰"),True),(ready(),False)):
        combined,_=prepare_inventory(BulkResult([row]),"test","主账号",6,[1],[],order)
        assert len(combined)==1
    empty=BulkRow(1,slot=8)
    combined,_=prepare_inventory(BulkResult([empty]),"empty","主账号",6,[1],[],False)
    assert combined[0].species=="待识别" and combined[0].ivs==[None]*6 and not combined[0].verified
    assert not combined[0].planner_usable
    assert not replace(combined[0],verified=True).planner_usable


def test_supplement_updates_only_chosen_fields_and_does_not_recreate_consumed_stock():
    result=BulkResult([ready(reviewed=False,has_particles=True,particles=["bats"],is_costume=True)])
    inventory,ids=prepare_inventory(result,"test","主账号",6,[1],[],False)
    changed=patch_inventory_records(inventory,ids,{"nature":"固执"})
    assert changed[0].nature=="固执" and not changed[0].verified and changed[0].planner_usable
    assert changed[0].particles==["bats"] and changed[0].is_costume and changed[0].id==ids[0]
    assert inventory[0].nature==""
    with pytest.raises(ValueError,match="已不在库存"):patch_inventory_records([],ids,{"nature":"固执"})


def test_json_roundtrip_and_older_mobile_export_preserve_batch_usability():
    original=ready(reviewed=False,nature=None,has_particles=None,is_costume=None).monster("roundtrip","主账号",6)
    restored=Monster.from_dict(json.loads(json.dumps(original.to_dict())))
    assert not restored.verified and restored.planner_usable and "nature" in restored.unreviewed_fields
    legacy=original.to_dict();legacy.pop("usable_unreviewed");legacy.pop("unreviewed_fields")
    assert Monster.from_dict(legacy).planner_usable
    assert not Monster(id="legacy-other",species="伊布",gender="F",verified=False,source="mobile-ocr").planner_usable


def test_position_uncertainty_survives_older_json_until_explicitly_checked():
    original=ready(reviewed=False,warehouse_level=41).monster("position","主账号",6)
    assert not original.planner_usable
    legacy=original.to_dict();legacy.pop("usable_unreviewed");legacy.pop("unreviewed_fields")
    restored=Monster.from_dict(legacy)
    assert not restored.planner_usable and "position" in restored.unreviewed_fields
    checked=patch_inventory_records([restored],[restored.id],{"position_reviewed":True})[0]
    assert checked.planner_usable and Monster.from_dict(checked.to_dict()).planner_usable


def test_empty_and_partial_scans_survive_inventory_storage_without_manual_fields(tmp_path,monkeypatch):
    from storage import load_inventory,save_inventory
    monkeypatch.setenv("LOCALAPPDATA",str(tmp_path))
    rows=[BulkRow(1,slot=8),ready(2,9,reviewed=False,nature=None,has_particles=None,is_costume=None,ivs=[31,None,None,None,None,None])]
    inventory,ids=prepare_inventory(BulkResult(rows),"partial","主账号",6,[1,2],[],False)
    save_inventory(inventory)
    restored=load_inventory()
    assert [monster.id for monster in restored]==ids
    assert restored[0].ivs==[None]*6 and not restored[0].verified and not restored[0].planner_usable
    assert restored[1].ivs==[31,None,None,None,None,None] and restored[1].planner_usable
    assert restored[1].nature=="" and "nature" in restored[1].unreviewed_fields


def test_unreviewed_materials_actually_supply_a_breeding_plan_with_partial_ivs():
    from planner import make_report_with_candidates
    rows=[ready(1,8,species="伊布",gender="F",ivs=[31,None,None,None,None,None],reviewed=False,nature=None,has_particles=None,is_costume=None),
          ready(2,9,species="伊布",gender="M",ivs=[None,31,None,None,None,None],reviewed=False,nature=None,has_particles=None,is_costume=None)]
    inventory,ids=prepare_inventory(BulkResult(rows),"plan","主账号",6,[1,2],[],False)
    report,candidates=make_report_with_candidates(inventory,"伊布","F","","31/31/x/x/x/x",["陆上"],allow_ditto=False)
    assert candidates,report
    assert candidates[0].root.used_ids==frozenset(ids)
    assert candidates[0].root.purchases==0 and candidates[0].root.breeds==1
    assert all(not monster.verified and monster.nature=="" for monster in inventory)


@pytest.mark.parametrize("trait",[{"has_particles":True,"particles":["bats"]},{"is_costume":True}])
def test_known_rare_traits_stay_protected_even_without_review(trait):
    from planner import make_report_with_candidates
    rows=[ready(1,8,species="喵喵",gender="F",ivs=[31,1,1,1,1,1],reviewed=False,**trait),
          ready(2,9,species="喵喵",gender="M",ivs=[1,31,1,1,1,1],reviewed=False)]
    inventory,ids=prepare_inventory(BulkResult(rows),"rare","主账号",6,[1,2],[],False)
    _report,candidates=make_report_with_candidates(inventory,"猫老大","F","","31/31/x/x/x/x",["陆上"],allow_ditto=False)
    assert all(ids[0] not in candidate.root.used_ids for candidate in candidates)


def test_unknown_nature_is_not_assumed_and_can_be_added_later_for_a_nature_target():
    from planner import make_report_with_candidates
    row=ready(species="伊布",gender="F",ivs=[31,31,1,1,1,1],reviewed=False,nature=None)
    inventory,ids=prepare_inventory(BulkResult([row]),"nature","主账号",6,[1],[],False)
    _report,before=make_report_with_candidates(inventory,"伊布","F","固执","31/31/x/x/x/x",["陆上"],allow_ditto=False,nature_strategy="chain")
    assert not any(candidate.root.purchases==0 and candidate.root.has_nature for candidate in before)
    filled=patch_inventory_records(inventory,ids,{"nature":"固执"})
    report,after=make_report_with_candidates(filled,"伊布","F","固执","31/31/x/x/x/x",["陆上"],allow_ditto=False,nature_strategy="chain")
    assert after,report
    assert after[0].root.used_ids==frozenset(ids) and after[0].root.purchases==0 and after[0].root.has_nature
    assert not filled[0].verified


def test_import_is_atomic_with_respect_to_validation_and_never_replaces_occupied_positions():
    inventory=[Monster(id="existing",species="伊布",account="主账号",page="6",slot="9")]
    result=BulkResult([ready(1,8),ready(2,9)])
    with pytest.raises(ValueError,match="已有素材"):
        prepare_inventory(result,"test","主账号",6,[1,2],inventory,True)
    assert [row.id for row in inventory]==["existing"]


def test_same_capture_replay_is_idempotent_but_a_new_capture_has_distinct_identity():
    result=BulkResult([ready()])
    combined,ids=prepare_inventory(result,"test","主账号",6,[1],[],True)
    replay=BulkResult.from_dict(json.loads(json.dumps(result.to_dict())))
    repeated,repeated_ids=prepare_inventory(replay,"test","主账号",6,[1],combined,True)
    assert len(repeated)==1 and ids==repeated_ids
    changed=BulkResult([ready()])
    assert changed.capture_id!=result.capture_id
    with pytest.raises(ValueError,match="已有素材"):prepare_inventory(changed,"test","主账号",6,[1],combined,True)
    result.rows[0].ivs=[0]*6
    with pytest.raises(ValueError,match="资料发生变化"):prepare_inventory(result,"test","主账号",6,[1],combined,True)


def test_known_particle_without_catalogue_name_stays_protected_in_imported_record():
    result=BulkResult([ready(has_particles=True,particles=[])])
    combined,_=prepare_inventory(result,"test","主账号",6,[1],[],True)
    assert combined[0].has_particles and combined[0].verified


def test_draft_store_roundtrip_and_previous_batch_keep_unknowns_and_image_evidence(tmp_path):
    store=BulkSessionStore(tmp_path)
    first=str(uuid.uuid4());second=str(uuid.uuid4())
    result=BulkResult([BulkRow(1)])
    state={"schema_version":1,"session_id":first,"result":result.to_dict()}
    store.save_image(first,"warehouse",Image.new("RGB",(300,150)))
    store.save(state)
    store.save({**state,"session_id":second})
    assert store.previous(second)==state
    assert store.load()["session_id"]==second
    restored=BulkResult.from_dict(store.load(first)["result"])
    assert restored.rows[0].has_particles is None and not restored.rows[0].reviewed
    assert Image.open(store.image_path(first,"warehouse")).size==(300,150)
    with pytest.raises(ValueError):store.directory("../escape")
    with pytest.raises(ValueError):store.image_path(first,"../escape")


def test_roi_stays_within_the_supplied_image():
    image=Image.new("RGB",(600,400))
    assert validate_roi(image,(1,2,500,350))==(1,2,500,350)
    for bounds in ((-1,0,500,300),(0,0,601,300),(0,0,20,20)):
        with pytest.raises(ValueError):validate_roi(image,bounds)


def test_warehouse_blank_tiles_do_not_invent_sex_or_levels():
    class EmptyOCR:
        def recognize(self,_image):return []
    cells=read_warehouse(Image.new("RGB",(800,400),(30,35,40)),EmptyOCR(),[8,9])
    assert all(cell["gender"]=="" and cell["level"] is None for cell in cells)
