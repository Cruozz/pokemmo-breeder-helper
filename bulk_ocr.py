"""Bounded two-image capture; save observed data before optional review."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime, timezone
import re
import statistics
import uuid
from typing import Any

from models import Monster
from nature_data import NATURE_BY_CHINESE
from ocr_engine import OCRItem, OCRProcessor
from species_data import get_species_database


@dataclass
class BulkRow:
    index: int
    species: str = ""
    raw_name: str = ""
    candidates: list[str] = field(default_factory=list)
    level: int | None = None
    ivs: list[int | None] = field(default_factory=lambda: [None] * 6)
    hidden_ability: bool | None = None
    slot: int | None = None
    gender: str = ""
    warehouse_level: int | None = None
    source_box: tuple[int, int, int, int] | None = None
    confidence: float = 0.0
    nature: str | None = None
    is_alpha: bool | None = None
    has_particles: bool | None = None
    particles: list[str] = field(default_factory=list)
    is_costume: bool | None = None
    reviewed: bool = False
    position_reviewed: bool = False
    imported: bool = False

    @classmethod
    def from_dict(cls, value: dict) -> BulkRow:
        row = cls(**{key: item for key, item in value.items() if key in {f.name for f in fields(cls)}})
        if type(row.index) is not int or row.index<1 or not isinstance(row.ivs,list) or len(row.ivs)!=6:
            raise ValueError("批量草稿条目无效；原文件已保留。")
        return row

    def problems(self, *, require_review: bool = True) -> list[str]:
        database = get_species_database()
        record = database.get(self.species)
        problems = []
        if record is None:
            problems.append("名字待补全")
        if not isinstance(self.slot, int) or not 1 <= self.slot <= 60:
            problems.append("尚未对应仓位")
        if type(self.level) is not int or not 1 <= self.level <= 100:
            problems.append("等级待核对")
        if not self.position_reviewed and (self.warehouse_level is None or self.warehouse_level != self.level):
            problems.append("仓库等级需核对")
        if not self.gender or (record is not None and self.gender not in record.allowed_genders):
            problems.append("性别待核对")
        if len(self.ivs) != 6 or any(type(value) is not int or not 0 <= value <= 31 for value in self.ivs):
            problems.append("六项个体值需补全")
        if type(self.hidden_ability) is not bool:
            problems.append("梦特待核对")
        if not isinstance(self.nature,str) or (self.nature and self.nature not in NATURE_BY_CHINESE):
            problems.append("性格待核对")
        for value, name in ((self.is_alpha,"头目"),(self.has_particles,"粒子"),(self.is_costume,"时装")):
            if type(value) is not bool:
                problems.append(name + "待核对")
        if require_review and self.reviewed is not True:
            problems.append("资料未确认")
        return problems

    def monster(self, session_id: str, account: str, page: int) -> Monster:
        if type(self.slot) is not int or not 1 <= self.slot <= 60:
            raise ValueError(f"第 {self.index} 条尚未对应仓位，请核对数量和范围。")
        if len(self.ivs)!=6 or any(value is not None and (type(value) is not int or not 0<=value<=31) for value in self.ivs):
            raise ValueError(f"第 {self.index} 条个体值格式无效。")
        from cosmetics import costume_family
        record = get_species_database().get(self.species)
        missing = [name for name,value in (("nature",self.nature),("is_alpha",self.is_alpha),
                   ("has_particles",self.has_particles),("is_costume",self.is_costume),("has_hidden_ability",self.hidden_ability)) if value is None]
        if record is None:missing.append("species")
        if not self.gender:missing.append("gender")
        if any(value is None for value in self.ivs):missing.append("ivs")
        if not self.position_reviewed and (self.level is None or self.warehouse_level!=self.level):missing.append("position")
        return Monster(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"pokemmo-bulk:{session_id}:{self.index}")),
            species=record.display_name if record else self.species or "待识别", gender=self.gender, nature=self.nature or "", ivs=self.ivs,
            egg_groups=list(record.egg_groups) if record else [], is_alpha=bool(self.is_alpha),
            has_hidden_ability=bool(self.hidden_ability), has_particles=bool(self.has_particles),
            particles=list(self.particles), is_costume=bool(self.is_costume),
            costume_id=costume_family(record.display_name) if self.is_costume and record else "",
            account=account, page=str(page), slot=str(self.slot), verified=self.reviewed,
            usable_unreviewed=True,unreviewed_fields=missing,
            source="批量识别：仓库＋确认列表",
            confidence=self.confidence,
            notes=f"批量录入；等级 {self.level or '未读出'}；原名字：{self.raw_name}"
                  + ("；性格未登记" if not self.nature else "")
                  + ("；仓位与等级待核对" if "position" in missing else ""),
        )


@dataclass
class BulkResult:
    rows: list[BulkRow] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    selected_slots: list[int] = field(default_factory=list)
    count: int = 0
    capture_id: str = field(default_factory=lambda:str(uuid.uuid4()))
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> BulkResult:
        return cls([BulkRow.from_dict(row) for row in value.get("rows", [])],
                   list(value.get("blockers", [])), list(value.get("selected_slots", [])), int(value.get("count",0)),
                   str(value.get("capture_id") or uuid.uuid4()),list(value.get("warnings", [])))


def slot_range(page: int, start: int, count: int) -> list[int]:
    if any(type(value) is not int for value in (page,start,count)) or not 1 <= page <= 999 or not 1 <= start <= 60 or not 1 <= count <= 20:
        raise ValueError("仓库页需为 1～999，起始格为 1～60，每批为 1～20 只。")
    if start + count - 1 > 60:
        raise ValueError(f"本页从第 {start} 格起只剩 {61-start} 格，请分两批采集。")
    return list(range(start,start+count))


def next_batch_range(page: int, start: int, count: int, preferred_count: int) -> tuple[int,int,int]:
    previous = slot_range(page,start,count)
    if type(preferred_count) is not int or not 1<=preferred_count<=20:
        raise ValueError("每批数量需为 1～20 只。")
    next_page = page + (previous[-1]//60)
    next_start = previous[-1]%60+1
    next_count = min(preferred_count,61-next_start)
    slot_range(next_page,next_start,next_count)
    return next_page,next_start,next_count


def validate_roi(image: Any, bounds: tuple | list) -> tuple[int,int,int,int]:
    if len(bounds) != 4:
        raise ValueError("请先框选识别范围。")
    left,top,right,bottom = (round(value) for value in bounds)
    if not 0 <= left < right <= image.width or not 0 <= top < bottom <= image.height or right-left < 40 or bottom-top < 30:
        raise ValueError("识别范围无效，请在图片内重新框选。")
    return left,top,right,bottom


def _ordered_rows(entries: list[tuple[BulkRow,float,float]], height: float) -> list[BulkRow]:
    rows: list[list[tuple]] = []
    for entry in sorted(entries,key=lambda item:item[2]):
        row = next((row for row in rows if abs(statistics.mean(item[2] for item in row)-entry[2]) <= height*.6),None)
        if row is None:
            rows.append([entry])
        else:
            row.append(entry)
    ordered = [item[0] for row in rows for item in sorted(row,key=lambda item:item[1])]
    for index,entry in enumerate(ordered,1):
        entry.index = index
    return ordered


def parse_release(image: Any, items: list[OCRItem]) -> list[BulkRow]:
    """Join only a name and IV immediately below it in the same list cell."""
    import numpy as np
    from PIL import Image
    names = OCRProcessor._level_items(items)
    iv_lines = [item for item in items if OCRProcessor._compact(item.text).count("/") >= 4]
    height = statistics.median([OCRProcessor._height(item.box) for item in [*names,*iv_lines]]) if names or iv_lines else 20
    columns: list[list[float]] = []
    for x in sorted(OCRProcessor._left(item.box) for item in names):
        if not columns or x-statistics.median(columns[-1]) > height*2.7:
            columns.append([x])
        else:
            columns[-1].append(x)
    if len(columns)>3:
        raise ValueError("检测到名单以外的名字，请只框选放生确认列表，排除左侧详情与背景。")
    pixels = np.asarray(image.convert("RGB")).copy()
    pixels[pixels[:,:,2].astype(int)-pixels[:,:,1].astype(int) < 8] = 0
    badge_image = Image.fromarray(pixels)
    used: set[int] = set()
    entries = []
    database = get_species_database()
    for anchor in names:
        x,y = OCRProcessor._left(anchor.box),OCRProcessor._center_y(anchor.box)
        column = min(range(len(columns)),key=lambda index:abs(statistics.median(columns[index])-x))
        cell_right = min(columns[column+1])-height*2 if column+1<len(columns) else image.width
        # Do not merge another column's name or its sprite into this record.
        local = [item for item in items if OCRProcessor._left(item.box) < cell_right]
        raw,name = OCRProcessor._species_from_level_item([anchor,*[item for item in local if item is not anchor and item not in names]])
        record,confident,_score = database.resolve_ocr_name(raw)
        options = [(abs(OCRProcessor._left(item.box)-x)+abs(OCRProcessor._center_y(item.box)-y),index,item)
                   for index,item in enumerate(iv_lines) if index not in used
                   and 0 < OCRProcessor._center_y(item.box)-y < height*2.3
                   and abs(OCRProcessor._left(item.box)-x) < height*2.5]
        iv_item = None
        if options:
            _,index,iv_item = min(options,key=lambda item:item[0])
            used.add(index)
        level = int(re.search(r"\d+",anchor.text)[0])
        box = (max(0,round(x-height*2)),max(0,round(y-height*.7)),min(image.width,round(cell_right)),
               min(image.height,round(OCRProcessor._bottom(iv_item.box)+height*.3) if iv_item else round(y+height*1.8)))
        entry = BulkRow(0,species=record.display_name if record and confident else "",raw_name=raw,
                        candidates=[] if record and confident else [r.display_name for r in database.ocr_name_candidates(raw)],
                        level=level if 1 <= level <= 100 else None,
                        ivs=OCRProcessor._iv_values(iv_item.text) if iv_item and OCRProcessor._iv_values(iv_item.text) else [None]*6,
                        hidden_ability=OCRProcessor._hidden_ability_from_image(badge_image.crop((0,0,round(cell_right),image.height)),[name])[0],
                        source_box=box,confidence=min(anchor.score,iv_item.score if iv_item else 0.0))
        entries.append((entry,x,y))
    for index,item in enumerate(iv_lines):
        if index not in used:
            entry = BulkRow(0,ivs=OCRProcessor._iv_values(item.text) or [None]*6,confidence=item.score,
                            source_box=(max(0,round(OCRProcessor._left(item.box)-height*2)),
                                        max(0,round(OCRProcessor._top(item.box)-height*1.5)),
                                        round(OCRProcessor._right(item.box)),round(OCRProcessor._bottom(item.box))))
            entries.append((entry,OCRProcessor._left(item.box),OCRProcessor._center_y(item.box)-height*1.25))
    return _ordered_rows(entries,height)


def selected_slots(image: Any) -> list[int]:
    """Advisory colour/focus hints; user-entered positions stay authoritative."""
    image = image.convert("RGB")
    width,height = image.width/10,image.height/6
    result = []
    for slot in range(1,61):
        row,column = divmod(slot-1,10)
        x,y = column*width,row*height
        points = [(round(x+width*.12),round(y+height*t/20)) for t in range(3,11)]
        points += [(round(x+width*t/20),round(y+height*.12)) for t in range(4,15)]
        colors = [image.getpixel((min(image.width-1,px),min(image.height-1,py))) for px,py in points]
        if sum(g-r>=12 and b-r>=20 and b>=45 for r,g,b in colors)/len(colors) >= .65:
            result.append(slot)
    return result


def read_warehouse(image: Any, processor: OCRProcessor, slots: list[int]) -> list[dict]:
    from PIL import Image,ImageOps
    from warehouse_vision import classify_alpha_icon
    if image.width < 200 or image.height < 120:
        raise ValueError("仓库网格图片太小，请框选完整的 10 列、6 行网格。")
    width,height = image.width/10,image.height/6
    tile_w,tile_h,columns = 144,112,5
    sheet = Image.new("RGB",(columns*tile_w,((len(slots)+columns-1)//columns)*tile_h),(29,36,39))
    cells = []
    for index,slot in enumerate(slots):
        row,column = divmod(slot-1,10)
        x,y = column*width,row*height
        region = image.crop((round(x+width*.06),round(y+height*.58),round(x+width*.27),round(y+height*.89)))
        female,male = OCRProcessor._gender_color_counts(region.convert("RGB").getdata())
        gender = "F" if female>=4 and female>male*1.5 else "M" if male>=4 and male>female*1.5 else ""
        level_crop = image.crop((round(x+width*.46),round(y+height*.53),round(x+width*.94),round(y+height*.94)))
        level_crop = ImageOps.contain(level_crop.resize((level_crop.width*3,level_crop.height*3),Image.Resampling.LANCZOS),(112,80),Image.Resampling.LANCZOS)
        sheet.paste(level_crop,(index%columns*tile_w+10,index//columns*tile_h+10))
        tile = image.crop((round(x),round(y),round(x+width),round(y+height)))
        cells.append({"slot":slot,"gender":gender,"level":None,"is_alpha":classify_alpha_icon(tile),"readings":[]})
    for item in processor.recognize(sheet):
        x = (OCRProcessor._left(item.box)+OCRProcessor._right(item.box))/2
        index = int(OCRProcessor._center_y(item.box)//tile_h)*columns+int(x//tile_w)
        if 0 <= index < len(cells):
            cells[index]["readings"].extend(int(number) for number in re.findall(r"\d+",item.text))
    for cell in cells:
        if len(cell["readings"])==1 and 1 <= cell["readings"][0] <= 100:
            cell["level"] = cell["readings"][0]
    return cells


def combine(rows: list[BulkRow], cells: list[dict], page: int, start: int, count: int,
            highlights: list[int] | None = None) -> BulkResult:
    slots = slot_range(page,start,count)
    blockers = []
    warnings = []
    if len(rows)!=count or len(cells)!=count:
        blockers.append(f"数量不符：列表 {len(rows)} / 仓库 {len(cells)} / 设置 {count}。请修正数量或重新截取。")
    if highlights and highlights!=slots:
        warnings.append(f"仓库高亮仅供参考；已按设置的第 {start}～{slots[-1]} 格对应，不影响入库。")
    result = BulkResult(rows,blockers,list(highlights or []),len(rows),warnings=warnings)
    for row in rows:
        row.slot = None
        row.gender = ""
        row.warehouse_level = None
    if blockers:
        return result
    database = get_species_database()
    for row,cell in zip(rows,cells):
        row.slot,row.gender,row.warehouse_level = cell["slot"],cell["gender"],cell["level"]
        row.is_alpha = cell.get("is_alpha",row.is_alpha)
        record = database.get(row.species)
        if not row.gender and record and record.allowed_genders == ("N",) and row.level==cell["level"]:
            row.gender = "N"
    return result


def recognize_bulk(warehouse: Any, release: Any, page: int, start: int, count: int,
                   processor: OCRProcessor | None = None) -> BulkResult:
    slots = slot_range(page,start,count)
    processor = processor or OCRProcessor()
    rows = parse_release(release,processor.recognize(release))
    cells = read_warehouse(warehouse,processor,slots)
    return combine(rows,cells,page,start,count,selected_slots(warehouse))


def prepare_inventory(result: BulkResult, session_id: str, account: str, page: int,
                      indices: list[int], inventory: list[Monster], order_confirmed: bool) -> tuple[list[Monster],list[str]]:
    """Validate the whole import before any write. Replays use stable IDs."""
    if result.blockers:
        raise ValueError("请先排除数量与格位范围问题。")
    if not account.strip() or not 1 <= page <= 999 or not session_id:
        raise ValueError("账号、仓库页或批次信息无效。")
    by_index = {row.index:row for row in result.rows}
    if not indices or any(index not in by_index for index in indices) or len(set(indices))!=len(indices):
        raise ValueError("请选择要导入的有效条目。")
    additions = [by_index[index].monster(session_id+":"+result.capture_id,account,page) for index in indices]
    existing_ids = {monster.id for monster in inventory}
    existing_by_id = {monster.id:monster for monster in inventory}
    occupied = {(monster.account,monster.page,monster.slot) for monster in inventory}
    new_positions = set()
    for monster in additions:
        if monster.id in existing_ids:
            previous = existing_by_id[monster.id]
            if any(getattr(previous,name)!=getattr(monster,name) for name in
                   ("species","gender","ivs","nature","is_alpha","has_hidden_ability","has_particles","particles","is_costume","account","page","slot")):
                raise ValueError("这一条已入库且资料发生变化，请从库存编辑原记录。")
            continue
        position = (monster.account,monster.page,monster.slot)
        if position in occupied or position in new_positions:
            raise ValueError(f"仓库 {page} 第 {monster.slot} 格已有素材；请先核对库存，未覆盖原记录。")
        new_positions.add(position)
    return [*inventory,*[monster for monster in additions if monster.id not in existing_ids]],[monster.id for monster in additions]


def batch_record_id(session_id: str, capture_id: str, index: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL,f"pokemmo-bulk:{session_id}:{capture_id}:{index}"))


def patch_inventory_records(inventory: list[Monster], identifiers: list[str], changes: dict) -> list[Monster]:
    """Supplement existing stock only; a consumed material must never reappear."""
    by_id = {monster.id:monster for monster in inventory}
    if not identifiers or any(identifier not in by_id for identifier in identifiers):
        raise ValueError("所选素材已不在库存，请先刷新库存；没有重新添加已消耗的素材。")
    allowed = {"species","gender","ivs","nature","hidden_ability","is_alpha","has_particles","particles","is_costume","reviewed","position_reviewed","level"}
    if set(changes)-allowed:
        raise ValueError("不支持的库存补充项目。")
    updated = {}
    database = get_species_database()
    for identifier in identifiers:
        previous = by_id[identifier]
        values = {}
        missing = set(previous.unreviewed_fields)
        for field_name,value in changes.items():
            if field_name=="level":
                continue  # Level evidence remains in the batch draft.
            if field_name=="position_reviewed":
                if value:
                    missing.discard("position")
                    values["notes"] = previous.notes.replace("；仓位与等级待核对", "")
                continue
            target = {"hidden_ability":"has_hidden_ability","reviewed":"verified"}.get(field_name,field_name)
            if target in {"nature","is_alpha","has_particles","is_costume","has_hidden_ability"}:
                if value is None:missing.add(target)
                else:missing.discard(target)
            values[target] = "" if target=="nature" and value is None else bool(value) if target in {"is_alpha","has_particles","is_costume","has_hidden_ability","verified"} else value
        if "ivs" in values:
            ivs = values["ivs"]
            if len(ivs)!=6 or any(value is not None and (type(value) is not int or not 0<=value<=31) for value in ivs):
                raise ValueError("个体值格式无效。")
            if any(value is None for value in ivs):missing.add("ivs")
            else:missing.discard("ivs")
        if "species" in values:
            record = database.get(values["species"])
            if record:
                values.update(species=record.display_name,egg_groups=list(record.egg_groups))
                missing.discard("species")
            else:
                values["egg_groups"] = []
                missing.add("species")
        if "gender" in values:
            if values["gender"]:missing.discard("gender")
            else:missing.add("gender")
        if values.get("has_particles") is False:
            values["particles"] = []
        if "is_costume" in values or ("species" in values and previous.is_costume):
            from cosmetics import costume_family
            is_costume = values.get("is_costume",previous.is_costume)
            values["costume_id"] = costume_family(values.get("species",previous.species)) if is_costume else ""
            values["costume_lineage"] = (previous.costume_lineage or previous.id) if is_costume else ""
        values["unreviewed_fields"] = sorted(missing)
        values["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        updated[identifier] = replace(previous,**values)
    return [updated.get(monster.id,monster) for monster in inventory]
