from __future__ import annotations

import itertools
import re
from dataclasses import dataclass

from chain_planner import find_chain_candidates
from models import Monster, normalize_gender
from reference_data import get_reference_database
from species_data import get_species_database


STAT_NAMES = ("HP", "攻击", "防御", "特攻", "特防", "速度")

NATURE_ALIASES = {
    "adamant": "adamant", "固执": "adamant",
    "bashful": "bashful", "害羞": "bashful",
    "bold": "bold", "大胆": "bold",
    "brave": "brave", "勇敢": "brave",
    "calm": "calm", "温和": "calm", "沉着": "calm",
    "careful": "careful", "慎重": "careful",
    "docile": "docile", "坦率": "docile",
    "gentle": "gentle", "温顺": "gentle",
    "hardy": "hardy", "勤奋": "hardy",
    "hasty": "hasty", "急躁": "hasty",
    "impish": "impish", "淘气": "impish",
    "jolly": "jolly", "爽朗": "jolly",
    "lax": "lax", "乐天": "lax", "松懈": "lax",
    "lonely": "lonely", "孤独": "lonely", "怕寂寞": "lonely",
    "mild": "mild", "慢吞吞": "mild",
    "modest": "modest", "内敛": "modest",
    "naive": "naive", "天真": "naive",
    "naughty": "naughty", "顽皮": "naughty",
    "quiet": "quiet", "冷静": "quiet",
    "rash": "rash", "马虎": "rash",
    "relaxed": "relaxed", "悠闲": "relaxed",
    "sassy": "sassy", "自大": "sassy",
    "serious": "serious", "认真": "serious",
    "timid": "timid", "胆小": "timid",
    "quirky": "quirky", "浮躁": "quirky",
    "neutral": "neutral", "无修正": "neutral", "无修正（任一）": "neutral", "无属性增减": "neutral",
}

NEUTRAL_NATURE_KEYS = {"hardy", "docile", "serious", "bashful", "quirky"}


def parse_iv_requirements(value: str) -> list[int | None]:
    parts = re.split(r"[/,，\s]+", (value or "").strip())
    result: list[int | None] = []
    for part in parts[:6]:
        token = part.strip().lower()
        if token in {"", "x", "any", "任意", "-", "—", "?"}:
            result.append(None)
        else:
            try:
                number = int(token)
            except ValueError:
                result.append(None)
            else:
                result.append(number if 0 <= number <= 31 else None)
    return result + [None] * max(0, 6 - len(result))


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip().lower())


def normalize_nature(value: str) -> str:
    compact = normalize_text(value)
    if not compact:
        return ""
    if compact in NATURE_ALIASES:
        return NATURE_ALIASES[compact]
    for alias, canonical in NATURE_ALIASES.items():
        if alias in compact:
            return canonical
    return compact


def nature_matches(target_key: str, candidate: str) -> bool:
    candidate_key = normalize_nature(candidate)
    if target_key == "neutral":
        return candidate_key in NEUTRAL_NATURE_KEYS
    return bool(target_key) and candidate_key == target_key


def shares_egg_group(a: Monster, b: Monster, target_groups: list[str]) -> bool:
    a_groups = {normalize_text(x) for x in a.egg_groups}
    b_groups = {normalize_text(x) for x in b.egg_groups}
    ditto_names = {"ditto", "百变怪"}
    if normalize_text(a.species) in ditto_names or normalize_text(b.species) in ditto_names:
        return not (normalize_text(a.species) in ditto_names and normalize_text(b.species) in ditto_names)
    if not a_groups or not b_groups:
        if target_groups:
            return bool(a_groups & {normalize_text(x) for x in target_groups}) or bool(
                b_groups & {normalize_text(x) for x in target_groups}
            )
        return False
    return bool(a_groups & b_groups)


def target_iv_guaranteed(a: Monster, b: Monster, target: list[int | None], brace_a: int | None, brace_b: int | None) -> list[bool]:
    result: list[bool] = []
    for index, required in enumerate(target):
        if required is None:
            result.append(True)
            continue
        shared = a.ivs[index] == required and b.ivs[index] == required
        braced = (brace_a == index and a.ivs[index] == required) or (brace_b == index and b.ivs[index] == required)
        result.append(shared or braced)
    return result


@dataclass
class Candidate:
    a: Monster
    b: Monster
    nature_holder: Monster | None
    brace_a: int | None
    brace_b: int | None
    cost: int
    guaranteed: list[bool]

    def description(self, target_gender: str) -> str:
        items: list[str] = []
        if self.nature_holder:
            items.append(f"Everstone → {self.nature_holder.species} {self.nature_holder.gender}")
        if self.brace_a is not None:
            items.append(f"Brace({STAT_NAMES[self.brace_a]}) → {self.a.species}")
        if self.brace_b is not None:
            items.append(f"Brace({STAT_NAMES[self.brace_b]}) → {self.b.species}")
        if target_gender in {"M", "F"}:
            items.append(f"子代选择{'雄性' if target_gender == 'M' else '雌性'}")
        item_text = "；".join(items) if items else "无需强制道具"
        return (
            f"父代 A：{self.a.species} {self.a.gender} {self.a.iv_string} {self.a.nature or '性格未知'}\n"
            f"父代 B：{self.b.species} {self.b.gender} {self.b.iv_string} {self.b.nature or '性格未知'}\n"
            f"操作：{item_text}\n"
            f"保证结果：{self.cost:,} 金币估算；{', '.join(STAT_NAMES[i] for i, ok in enumerate(self.guaranteed) if ok)}"
        )


def find_candidates(
    inventory: list[Monster],
    species: str,
    target_gender: str,
    nature: str,
    iv_string: str,
    egg_groups: list[str],
    max_results: int = 8,
) -> tuple[list[Candidate], list[str]]:
    species_key = normalize_text(species)
    target_gender = normalize_gender(target_gender) or ""
    target_ivs = parse_iv_requirements(iv_string)
    nature_key = normalize_nature(nature)
    missing: list[str] = []

    females = [m for m in inventory if normalize_gender(m.gender) == "F" and normalize_text(m.species) == species_key]
    if not females:
        missing.append(f"目标种类 {species or '未填写'} 的雌性母体")

    possible_males = [m for m in inventory if normalize_gender(m.gender) == "M" or normalize_text(m.species) == "ditto"]
    pairs = [(a, b) for a in females for b in possible_males if a.id != b.id and shares_egg_group(a, b, egg_groups)]
    if not pairs and females:
        missing.append("与目标母体兼容的雄性蛋组素材或 Ditto（请为素材填写蛋组）")

    candidates: list[Candidate] = []
    for a, b in pairs:
        nature_holders: list[Monster | None]
        if nature_key:
            nature_holders = [m for m in (a, b) if nature_matches(nature_key, m.nature)]
            if not nature_holders:
                continue
        else:
            nature_holders = [None]

        for nature_holder in nature_holders:
            allowed_a = [None] if nature_holder is a else [None] + [i for i, value in enumerate(target_ivs) if value is not None and a.ivs[i] == value]
            allowed_b = [None] if nature_holder is b else [None] + [i for i, value in enumerate(target_ivs) if value is not None and b.ivs[i] == value]
            for brace_a, brace_b in itertools.product(allowed_a, allowed_b):
                if brace_a is not None and brace_b is not None and brace_a == brace_b:
                    continue
                guaranteed = target_iv_guaranteed(a, b, target_ivs, brace_a, brace_b)
                if not all(guaranteed):
                    continue
                cost = 10_000 * sum(x is not None for x in (brace_a, brace_b))
                cost += 5_000 if nature_holder else 0
                cost += 5_000 if target_gender in {"M", "F"} else 0
                candidates.append(Candidate(a, b, nature_holder, brace_a, brace_b, cost, guaranteed))

    if nature_key and not candidates and pairs:
        missing.append(f"性格为 {nature or '目标性格'} 且可以携带 Everstone 的兼容素材")

    for index, required in enumerate(target_ivs):
        if required is None or any(candidate.guaranteed[index] for candidate in candidates):
            continue
        missing.append(f"{STAT_NAMES[index]} IV={required} 的可兼容父代素材；或准备两只共享该 IV 的父代")

    candidates.sort(key=lambda item: (item.cost, sum(x is not None for x in (item.brace_a, item.brace_b))))
    return candidates[:max_results], list(dict.fromkeys(missing))


def make_report_with_candidates(
    inventory: list[Monster],
    species: str,
    target_gender: str,
    nature: str,
    iv_string: str,
    egg_groups: list[str],
    target_alpha: bool = False,
    allow_ditto: bool = True,
    strategy: str = "inventory",
    nature_strategy: str = "late",
    allow_alpha_materials: bool = False,
    excluded_ids: set[str] | frozenset[str] | None = None,
    intermediate_gender_strategy: str = "lock_all",
    need_hidden_ability: bool = False,
    target_moves: tuple[str, ...] | list[str] | None = None,
    convert_maternal_with_ditto: bool = False,
    preferred_material_ids: set[str] | frozenset[str] | None = None,
) -> tuple[str, list]:
    if not species.strip():
        return "请先填写目标种类。", []
    species_db = get_species_database()
    target_record = species_db.get(species, fuzzy=True)
    resolved_species = target_record.display_name if target_record else species.strip()
    target_line = species_db.evolution_line(target_record) if target_record else ()
    target_ancestry = species_db.ancestry(target_record) if target_record else ()
    linked_breeding_family = species_db.linked_breeding_family(target_record) if target_record else ()
    breeding_family = linked_breeding_family or tuple(
        record for record in target_line if "未发现" not in record.egg_groups
    )
    breeding_parent = species_db.breeding_parent(target_record) if target_record else None
    offspring_record = species_db.breeding_offspring(target_record) if target_record else None
    linked_gender_offspring = (
        species_db.breeding_offspring_by_gender(target_record)
        if linked_breeding_family and target_record
        else ()
    )

    if normalize_text(resolved_species) in {"百变怪", "ditto"}:
        return "百变怪不能通过孵蛋获得；它只能作为其他精灵的孵化素材。", []
    if target_record and breeding_parent is None:
        return f"{resolved_species} 没有可参与孵化的进化形态，不能作为常规孵化目标。", []
    if target_record and species_db.requires_incense_for_target(target_record):
        return (
            f"{resolved_species} 需要对应熏香才能作为子代孵出；熏香会占用父母的携带道具位，"
            "当前严格规划器尚未安全建模这项冲突，因此暂不生成可能误导你的路线。"
        ), []

    resolved_groups = list(egg_groups)
    if target_record:
        # The final form may be unable to breed (for example a baby Pokemon),
        # while its breeding parent has the actual usable egg groups.
        resolved_groups = list(breeding_parent.egg_groups) if breeding_parent else resolved_groups

    excluded_id_set = {str(value) for value in (excluded_ids or ()) if str(value)}
    planning_inventory = [monster for monster in inventory if monster.id not in excluded_id_set]
    excluded_count = len(inventory) - len(planning_inventory)

    for monster in planning_inventory:
        record = species_db.get(monster.species, fuzzy=True)
        if record is None:
            continue
        monster.species = record.display_name
        if not monster.egg_groups:
            monster.egg_groups = list(record.egg_groups)
        if not monster.gender and record.allowed_genders == ("N",):
            monster.gender = "N"

    family_keys = {
        normalize_text(record.display_name)
        for record in breeding_family
    } or {normalize_text(resolved_species)}
    target_inventory_genders = {
        normalize_gender(monster.gender)
        for monster in planning_inventory
        if monster.verified and normalize_text(monster.species) in family_keys
    }
    resolved_group_keys = {normalize_text(group) for group in resolved_groups if normalize_text(group)}
    protected_alpha_materials = [
        monster
        for monster in planning_inventory
        if (
            monster.verified
            and monster.is_alpha
            and not target_alpha
            and not allow_alpha_materials
            and (
                normalize_text(monster.species) in family_keys
                or (
                    allow_ditto
                    and normalize_text(monster.species) in {"百变怪", "ditto"}
                )
                or bool(resolved_group_keys & {normalize_text(group) for group in monster.egg_groups})
            )
        )
    ]
    eligible_inventory_dittos = [
        monster
        for monster in planning_inventory
        if (
            allow_ditto
            and monster.verified
            and normalize_text(monster.species) in {"百变怪", "ditto"}
            and (
                monster.is_alpha
                if target_alpha
                else allow_alpha_materials or not monster.is_alpha
            )
        )
    ]

    target_ivs = parse_iv_requirements(iv_string)
    nature_key = normalize_nature(nature)
    selected_moves = tuple(str(move).strip() for move in (target_moves or ()) if str(move).strip())
    egg_move_donors: dict[str, tuple[str, ...]] = {}
    if selected_moves and offspring_record is not None:
        routes_by_move = get_reference_database().egg_moves_for_species(offspring_record.id)
        for move in selected_moves:
            donors: list[str] = []
            for route in routes_by_move.get(move, ()):
                direct_name = re.split(r"<=|←", route, maxsplit=1)[0]
                direct_name = re.sub(r"\s*[（(].*$", "", direct_name).strip()
                donor = species_db.get(direct_name, fuzzy=True)
                if donor is not None:
                    donors.append(donor.display_name)
            egg_move_donors[move] = tuple(dict.fromkeys(donors))
    candidates, missing = find_chain_candidates(
        planning_inventory,
        resolved_species,
        target_gender,
        nature_key,
        target_ivs,
        resolved_groups,
        nature,
        target_allowed_genders=(
            tuple(gender for gender, _record in linked_gender_offspring)
            if linked_gender_offspring
            else (offspring_record or target_record).allowed_genders if target_record else None
        ),
        target_gender_species=tuple(
            (gender, record.display_name)
            for gender, record in linked_gender_offspring
        ) or None,
        target_alpha=target_alpha,
        allow_ditto=allow_ditto,
        strategy=strategy,
        target_family_species=tuple(record.display_name for record in breeding_family) or None,
        target_goal_species=tuple(record.display_name for record in target_ancestry) or None,
        offspring_species=offspring_record.display_name if offspring_record else resolved_species,
        breeding_species=breeding_parent.display_name if breeding_parent else resolved_species,
        nature_strategy=nature_strategy,
        allow_alpha_materials=allow_alpha_materials,
        intermediate_gender_strategy=intermediate_gender_strategy,
        need_hidden_ability=need_hidden_ability,
        target_moves=selected_moves,
        egg_move_donors=egg_move_donors,
        prefer_ditto=allow_ditto,
        convert_maternal_with_ditto=convert_maternal_with_ditto,
        preferred_material_ids=frozenset(preferred_material_ids or ()),
    )
    strategy_key = "steps" if str(strategy).strip().lower() in {"steps", "step", "步骤优先", "孵化次数优先"} else "inventory"
    strategy_title = "步骤优先" if strategy_key == "steps" else "库存优先"
    lines: list[str] = []
    if excluded_count:
        lines.append(f"本次规划已排除 {excluded_count} 只受保护库存素材；记录仍保留在素材库存中。")
        lines.append("")
    if target_record:
        ratio = (
            "尼多家族特殊规则：中间代锁母，最终成品锁公"
            if linked_gender_offspring and target_gender == "M"
            else "尼多家族特殊规则：中间代与成品均锁母"
            if linked_gender_offspring and target_gender == "F"
            else "无性别"
            if target_record.female_percent is None
            else f"雌性 {target_record.female_percent:g}%"
        )
        hatch_name = offspring_record.display_name if offspring_record else resolved_species
        selected_form_text = f"｜所选形态 {resolved_species}（孵化后进化）" if hatch_name != resolved_species else ""
        reuse_text = (
            f"｜中间代需先进化为 {breeding_parent.display_name} 再参与下一步"
            if breeding_parent and hatch_name != breeding_parent.display_name
            else ""
        )
        lines.append(
            f"孵蛋目标：{hatch_name}｜{'头目' if target_alpha else '普通'}｜"
            f"蛋组 {' / '.join(resolved_groups)}｜{ratio}{selected_form_text}{reuse_text}"
        )
        if target_alpha:
            lines.append("素材范围：头目目标仅使用头目素材。")
        elif allow_alpha_materials:
            lines.append("素材范围：普通与头目库存均可参与；最终子代仍严格为普通。")
        else:
            lines.append("素材范围：仅使用普通素材；头目库存已保护。")
            if protected_alpha_materials:
                protected_ditto_count = sum(
                    normalize_text(monster.species) in {"百变怪", "ditto"}
                    for monster in protected_alpha_materials
                )
                ditto_text = f"，其中百变怪 {protected_ditto_count} 只" if protected_ditto_count else ""
                lines.append(
                    f"库存保护提示：检测到 {len(protected_alpha_materials)} 只可关联本路线的头目素材"
                    f"{ditto_text}，本次不会使用。若确实要消耗它们，请勾选“普通目标允许使用头目素材”。"
                )
        if allow_ditto:
            used_dittos = [
                monster
                for monster in eligible_inventory_dittos
                if candidates and monster.id in candidates[0].root.used_ids
            ]
            if used_dittos:
                used_text = "；".join(
                    f"{monster.account or '账号未记录'} {monster.position_label or '未定位'} "
                    f"{monster.iv_string}"
                    for monster in used_dittos
                )
                lines.append(
                    f"百变怪策略：已把消耗库存百变怪作为优先约束，并在这些路线中继续优化采购与孵化次数；"
                    f"本方案使用 {used_text}。"
                )
            elif eligible_inventory_dittos:
                lines.append(
                    "百变怪策略：已检查符合素材类别的库存百变怪，但当前 IV 重叠无法在不降级素材、"
                    "不放弃目标保底的前提下接入最佳路线。"
                )
            else:
                lines.append("百变怪策略：已启用，但当前素材类别内没有已确认的库存百变怪可供规划。")
        else:
            lines.append(
                "百变怪支线策略：除一次性母体转换外，其他支线不使用百变怪。"
                if convert_maternal_with_ditto
                else "百变怪策略：本次不使用百变怪。"
            )
        if convert_maternal_with_ditto:
            if candidates and candidates[0].root.maternal_conversion:
                lines.append(
                    "母体转换：库存没有目标母体，已单独使用目标公体＋百变怪锁母建立母系；"
                    "该权限独立于其他支线的百变怪开关。"
                )
            elif candidates and not target_inventory_genders.intersection({"F", "M"}):
                lines.append(
                    "母体来源：库存没有目标公体或母体，因此不绕行购买公体＋百变怪；"
                    + (
                        "步骤优先已直接采购较高档目标母体。"
                        if strategy_key == "steps"
                        else "库存优先会从最低实用档目标母体开始采购。"
                    )
                )
            elif candidates:
                lines.append(
                    "母体转换：当前已有可用目标母体，或库存没有可转换的目标公体；未额外消耗百变怪。"
                )
        if need_hidden_ability:
            lines.append("梦特约束：成品必须保留梦特潜力；仅同进化线的梦特父母可以向该子代传递。")
        if selected_moves:
            lines.append(f"遗传技能：{'、'.join(selected_moves)}（库存携带者优先，缺失时按内置遗传链补购）")
        lines.append("")
    if candidates:
        lines.append(f"库存预检：{candidates[0].inventory_audit_text()}")
        if candidates[0].root.purchases:
            lines.append(
                "仅用库存无法严格完成目标；以下路线先最大化使用库存。"
                "交易行素材购买后可直接执行对应步骤，无需 OCR 扫描入库。"
            )
        else:
            lines.append("库存预检通过：该路线可以完全使用现有已确认素材完成。")
        lines.append("")
        lines.append(f"找到 {len(candidates)} 个方案，方案 1 为当前{strategy_title}的最佳路线：")
        lines.append("")
        for index, candidate in enumerate(candidates, 1):
            lines.append(f"方案 {index}")
            lines.append(candidate.description())
            lines.append("")
    else:
        lines.append("当前库存没有找到能严格保证目标结果的完整孵化链。")
        lines.append("")

    if missing:
        lines.append("需要补充或核对的素材：")
        lines.extend(f"- {item}" for item in missing)
    else:
        lines.append("没有发现额外缺口。")

    lines.append("")
    lines.append("提示：当前规划覆盖种类、普通/头目、性别、IV、性格、蛋组、梦特潜力与所选遗传技能；特殊性别比例费用仍需人工确认。")
    return "\n".join(lines), candidates


def make_report(
    inventory: list[Monster],
    species: str,
    target_gender: str,
    nature: str,
    iv_string: str,
    egg_groups: list[str],
    target_alpha: bool = False,
    allow_ditto: bool = True,
    strategy: str = "inventory",
    nature_strategy: str = "late",
    allow_alpha_materials: bool = False,
    excluded_ids: set[str] | frozenset[str] | None = None,
    intermediate_gender_strategy: str = "lock_all",
    need_hidden_ability: bool = False,
    target_moves: tuple[str, ...] | list[str] | None = None,
    convert_maternal_with_ditto: bool = False,
    preferred_material_ids: set[str] | frozenset[str] | None = None,
) -> str:
    report, _candidates = make_report_with_candidates(
        inventory,
        species,
        target_gender,
        nature,
        iv_string,
        egg_groups,
        target_alpha,
        allow_ditto,
        strategy,
        nature_strategy,
        allow_alpha_materials,
        excluded_ids,
        intermediate_gender_strategy,
        need_hidden_ability,
        target_moves,
        convert_maternal_with_ditto,
        preferred_material_ids,
    )
    return report
