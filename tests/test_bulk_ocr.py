from dataclasses import replace
import json
import uuid

from PIL import Image, ImageDraw
import pytest

from bulk_ocr import BulkResult, BulkRow, combine, parse_release, prepare_inventory, read_warehouse, slot_range, validate_roi
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
def test_unseen_fields_remain_unknown_and_cannot_enter_verified_inventory(field):
    row=ready(**{field:None})
    result=BulkResult([row])
    with pytest.raises(ValueError):prepare_inventory(result,"test","主账号",6,[1],[],True)


def test_row_confirmation_order_confirmation_and_exact_species_are_required():
    for row,order in ((ready(reviewed=False),True),(ready(species="拉'恶冰"),True),(ready(),False)):
        with pytest.raises(ValueError):prepare_inventory(BulkResult([row]),"test","主账号",6,[1],[],order)


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
