from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from itertools import combinations, permutations
from typing import Iterable

from models import Monster, normalize_gender
from species_data import get_species_database


STAT_NAMES = ("HP", "攻击", "防御", "特攻", "特防", "速度")
BRACE_COST = 10_000
DITTO_NAMES = {"ditto", "百变怪"}
NEUTRAL_NATURE_KEYS = {"hardy", "docile", "serious", "bashful", "quirky"}
GENDER_STRATEGY_SMART = "smart"
GENDER_STRATEGY_LOCK_ALL = "lock_all"
GENDER_STRATEGY_MINIMAL = "minimal"


def normalize_text(value: str) -> str:
    return "".join((value or "").strip().lower().split())


def is_ditto(species: str) -> bool:
    return normalize_text(species) in DITTO_NAMES


@dataclass
class ChainAction:
    parent_a: "ChainState"
    parent_b: "ChainState"
    item_a: str = ""
    item_b: str = ""


@dataclass
class ChainState:
    species: str
    gender: str
    egg_groups: tuple[str, ...]
    mask: int
    has_nature: bool
    nature: str
    is_alpha: bool
    used_ids: frozenset[str]
    generation: int
    breeds: int
    braces: int
    everstones: int
    purchases: int = 0
    inventory_breeds: int = 0
    # Number of perfect IVs carried by an original material. ``mask`` only
    # tracks IVs relevant to the requested target, so it cannot detect that a
    # 2V breeder is being consumed as a 1V branch. Generated children use the
    # number of guaranteed target IVs.
    material_v: int = 0
    breeding_species: str = ""
    is_virtual: bool = False
    leaf: Monster | None = None
    action: ChainAction | None = None

    @property
    def item_cost(self) -> int:
        return self.braces * BRACE_COST

    @property
    def existing_leaves(self) -> int:
        return len(self.used_ids) - self.purchases

    @property
    def effective_material_v(self) -> int:
        return max(self.material_v, self.mask.bit_count())


def normalize_intermediate_gender_strategy(value: str) -> str:
    key = normalize_text(value)
    aliases = {
        "smart": GENDER_STRATEGY_SMART,
        "智能": GENDER_STRATEGY_SMART,
        "智能锁定": GENDER_STRATEGY_SMART,
        "lockall": GENDER_STRATEGY_LOCK_ALL,
        "全程锁定": GENDER_STRATEGY_LOCK_ALL,
        "全锁": GENDER_STRATEGY_LOCK_ALL,
        "minimal": GENDER_STRATEGY_MINIMAL,
        "尽量不锁": GENDER_STRATEGY_MINIMAL,
        "最少锁定": GENDER_STRATEGY_MINIMAL,
    }
    return aliases.get(key, GENDER_STRATEGY_LOCK_ALL)


def intermediate_gender_strategy_name(value: str) -> str:
    return {
        GENDER_STRATEGY_SMART: "智能锁定",
        GENDER_STRATEGY_LOCK_ALL: "全程锁定",
        GENDER_STRATEGY_MINIMAL: "尽量不锁",
    }[normalize_intermediate_gender_strategy(value)]


def child_gender_policy(
    state: ChainState,
    root: ChainState,
    target_gender: str,
    strategy: str,
    sibling: ChainState | None = None,
) -> str:
    """Return ``fixed``, ``locked`` or ``random`` for one generated child.

    The search tree keeps a concrete gender so it can prove that a route is
    feasible.  This policy is an execution overlay: a random low-tier child is
    recorded with its actual gender and the remaining route is then rebuilt.
    """
    record = get_species_database().get(state.species, fuzzy=True)
    if record is not None and record.allowed_genders != ("F", "M"):
        return "fixed"
    if state is root:
        return "locked" if normalize_gender(target_gender) in {"F", "M"} else "random"

    normalized = normalize_intermediate_gender_strategy(strategy)
    if normalized == GENDER_STRATEGY_LOCK_ALL:
        return "locked"
    if normalized == GENDER_STRATEGY_MINIMAL:
        return "random"

    # Five-IV and other top-tier bridge nodes are expensive enough that their
    # gender should remain deterministic.  At lower tiers, hatch the first
    # branch at random; once that real child exists in inventory, lock only the
    # counterpart needed to mate with it.
    if state.mask.bit_count() >= 5:
        return "locked"
    if (
        sibling is not None
        and sibling.action is None
        and sibling.leaf is not None
        and not sibling.is_virtual
        and normalize_gender(sibling.leaf.gender) in {"F", "M"}
    ):
        return "locked"
    return "random"


@dataclass
class ChainCandidate:
    root: ChainState
    target_ivs: list[int | None]
    target_nature: str
    target_gender: str
    target_alpha: bool = False
    target_species: str = ""
    offspring_species: str = ""
    breeding_species: str = ""
    nature_strategy: str = "late"
    gender_strategy: str = GENDER_STRATEGY_LOCK_ALL
    inventory_pool_size: int = 0
    inventory_iv_histogram: tuple[int, ...] = ()
    inventory_nature_count: int = 0
    inventory_target_female_count: int = 0
    inventory_compatible_male_count: int = 0
    inventory_other_female_count: int = 0
    inventory_excluded_female_only_count: int = 0

    def inventory_audit_text(self) -> str:
        buckets = [
            f"{index}V {count}只"
            for index, count in enumerate(self.inventory_iv_histogram)
            if count and index > 0
        ]
        bucket_text = "、".join(buckets) if buckets else "没有可计入的满 IV 素材"
        nature_text = f"；其中目标性格 {self.inventory_nature_count}只" if self.target_nature else ""
        roles = (
            f"目标母系 {self.inventory_target_female_count}只、"
            f"兼容雄性父本 {self.inventory_compatible_male_count}只、"
            f"其他同组雌性 {self.inventory_other_female_count}只"
        )
        excluded = (
            f"；已排除非目标纯母 {self.inventory_excluded_female_only_count}只"
            if self.inventory_excluded_female_only_count
            else ""
        )
        return f"同进化线/同组可用 {self.inventory_pool_size}只（{roles}）{excluded}｜{bucket_text}{nature_text}"

    def description(self) -> str:
        steps: list[str] = []
        leaf_numbers: dict[str, int] = {}

        def leaf_label(state: ChainState) -> str:
            assert state.leaf is not None
            key = next(iter(state.used_ids))
            if key not in leaf_numbers:
                leaf_numbers[key] = len(leaf_numbers) + 1
            monster = state.leaf
            alpha_text = "头目 " if monster.is_alpha else "普通 "
            if state.is_virtual:
                groups = "/".join(state.egg_groups) or "蛋组待确认"
                return (
                    f"需补充素材 {leaf_numbers[key]}：{alpha_text}{monster.species} {gender_name(monster.gender)} "
                    f"{monster.iv_string} {monster.nature or ''}（蛋组 {groups}）"
                )
            location = "/".join(x for x in (monster.page, monster.slot) if x)
            where = f"（仓库 {location}）" if location else ""
            return (
                f"素材 {leaf_numbers[key]}：{alpha_text}{monster.species} {monster.gender or '性别未知'} "
                f"{monster.iv_string} {monster.nature or '性格未知'}{where}"
            )

        gender_locks = 0

        def emit(state: ChainState, sibling: ChainState | None = None) -> str:
            nonlocal gender_locks
            if state.action is None:
                return leaf_label(state)
            action = state.action
            left = emit(action.parent_a, action.parent_b)
            right = emit(action.parent_b, action.parent_a)
            number = len(steps) + 1
            item_parts = []
            if action.item_a:
                item_parts.append(f"父母 A 携带 {action.item_a}")
            if action.item_b:
                item_parts.append(f"父母 B 携带 {action.item_b}")
            item_text = "；".join(item_parts) if item_parts else "无需锁定道具"
            guaranteed = _mask_text(state.mask, self.target_ivs)
            nature_text = f"，性格 {state.nature}" if state.has_nature and state.nature else ""
            stage_note = ""
            if state is self.root and self.target_species and self.target_species != state.species:
                stage_note = f"；孵化后进化为最终目标 {self.target_species}"
            elif state is not self.root and self.breeding_species and self.breeding_species != state.species:
                stage_note = f"；再次参与孵化前进化为 {self.breeding_species}"
            gender_policy = child_gender_policy(
                state,
                self.root,
                self.target_gender,
                self.gender_strategy,
                sibling,
            )
            if gender_policy == "locked":
                gender_locks += 1
                gender_text = f"指定{gender_name(state.gender)}"
            elif gender_policy == "fixed":
                gender_text = f"固定{gender_name(state.gender)}"
            else:
                gender_text = "不指定性别（孵出后记录实际结果并重算）"
            steps.append(
                f"步骤 {number}\n"
                f"  父母 A：{left}\n"
                f"  父母 B：{right}\n"
                f"  道具：{item_text}\n"
                f"  子代：{gender_text}，得到 {'头目' if state.is_alpha else '普通'} {state.species}；"
                f"保证 {guaranteed}{nature_text}{stage_note}"
            )
            return f"步骤 {number} 的子代"

        final_ref = emit(self.root)
        if self.root.action is None:
            evolution_text = ""
            if self.root.leaf and self.target_species and self.root.leaf.species != self.target_species:
                evolution_text = f"\n该素材需进化为最终目标 {self.target_species}。"
            return f"库存中已经有满足目标的精灵：\n{final_ref}{evolution_text}"

        summary = (
            f"使用现有素材 {self.root.existing_leaves} 只，需要补充 {self.root.purchases} 只；"
            f"共 {self.root.breeds} 次孵化，{self.root.braces} 个护腕"
            f"（固定费用 {self.root.item_cost:,}），{self.root.everstones} 个不变之石；"
            f"按“{intermediate_gender_strategy_name(self.gender_strategy)}”执行，"
            f"当前路线最多 {gender_locks} 次需要指定子代性别。\n"
            "不变之石市价和不同性别比例的指定费用未计入固定费用。"
        )
        if self.target_species and self.offspring_species and self.target_species != self.offspring_species:
            summary += f"\n最终一代实际孵出 {self.offspring_species}，之后进化为 {self.target_species}。"
        if self.target_nature:
            target_exact = sum(value is not None for value in self.target_ivs)
            target_v = sum(value == 31 for value in self.target_ivs)
            custom_values = [
                f"{STAT_NAMES[index]}={value}"
                for index, value in enumerate(self.target_ivs)
                if value is not None and value != 31
            ]
            if self.nature_strategy == "late" and target_exact >= 2:
                if custom_values:
                    target_label = f"{target_v}V + {'、'.join(custom_values)}（共 {target_exact} 项精确）"
                    summary += (
                        f"\n性格策略：后置性格；顶层按 {target_label} 的无锁性格主线 + "
                        f"少一项精确的 {self.target_nature} 支线合成，最后一步使用不变之石。"
                    )
                else:
                    summary += (
                        f"\n性格策略：后置性格；顶层按 {target_v}V 无锁性格 + "
                        f"{target_v - 1}V {self.target_nature} 合成，最后一步使用不变之石。"
                    )
            else:
                summary += f"\n性格策略：不变石链；沿性格支线逐级锁定 {self.target_nature}。"
        return summary + "\n\n" + "\n\n".join(steps)

    def purchase_requirements(self) -> list[str]:
        counter: Counter[tuple[object, ...]] = Counter()

        def visit(state: ChainState) -> None:
            if state.action is not None:
                visit(state.action.parent_a)
                visit(state.action.parent_b)
                return
            if not state.is_virtual or state.leaf is None:
                return
            monster = state.leaf
            counter[(monster.species, monster.gender, monster.iv_string, monster.nature, tuple(state.egg_groups), monster.is_alpha)] += 1

        visit(self.root)
        result: list[str] = []
        for (species, gender, ivs, nature, groups, is_alpha), count in counter.items():
            nature_text = f"，性格 {nature}" if nature else ""
            group_text = "/".join(groups) or "待确认"
            iv_values = str(ivs).split("/")
            guaranteed = "、".join(
                f"{STAT_NAMES[index]} IV={value}"
                for index, value in enumerate(iv_values[:6])
                if value != "x"
            ) or "无指定 IV"
            result.append(
                f"{count}× {'头目' if is_alpha else '普通'} {species} {gender_name(str(gender))}，"
                f"{guaranteed}{nature_text}（蛋组 {group_text}）"
            )
        return result


@dataclass(frozen=True)
class SpeciesProfile:
    species: str
    species_key: str
    egg_groups: tuple[str, ...]
    genderless: bool = False
    allowed_genders: tuple[str, ...] = ("F", "M")
    material_species: str = ""


def gender_name(gender: str) -> str:
    return {"M": "雄性", "F": "雌性", "N": "无性别"}.get(gender, "任意性别")


def _mask_text(mask: int, target_ivs: list[int | None]) -> str:
    parts = [f"{STAT_NAMES[index]}={value}" for index, value in enumerate(target_ivs) if value is not None and mask & (1 << index)]
    return "、".join(parts) if parts else "目标种类"


def _group_key(groups: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({normalize_text(group) for group in groups if normalize_text(group)}))


def _fits_exact_subproblem(state: ChainState, required_mask: int) -> bool:
    """Whether a state can enter this branch without losing IV value."""
    return (
        state.mask == required_mask
        and state.effective_material_v == required_mask.bit_count()
    )


def _ordered_stats(bits: list[int]) -> tuple[int, ...]:
    if not bits:
        return ()
    return tuple(dict.fromkeys([bits[-1], bits[0], *bits]))


def _ordered_stat_pairs(bits: list[int]) -> tuple[tuple[int, int], ...]:
    """All valid pyramid splits, with the conventional edge split first."""
    if len(bits) < 2:
        return ()
    preferred = [(bits[0], bits[-1]), (bits[-1], bits[0])]
    remaining = [
        (left, right)
        for left in bits
        for right in bits
        if left != right
    ]
    return tuple(dict.fromkeys(preferred + remaining))


def _normalize_strategy(value: str) -> str:
    return "steps" if str(value).strip().lower() in {"steps", "step", "步骤优先", "孵化次数优先"} else "inventory"


def _state_rank(state: ChainState, strategy: str = "inventory") -> tuple[object, ...]:
    if _normalize_strategy(strategy) == "steps":
        return (
            state.breeds,
            state.purchases,
            -state.inventory_breeds,
            -state.existing_leaves,
            state.item_cost,
            tuple(sorted(state.used_ids)),
        )
    return (
        state.purchases,
        state.breeds,
        -state.inventory_breeds,
        -state.existing_leaves,
        state.item_cost,
        tuple(sorted(state.used_ids)),
    )


def _search_rank(
    state: ChainState,
    strategy: str = "inventory",
    required_mask: int | None = None,
    require_nature: bool = False,
) -> tuple[object, ...]:
    if required_mask is None:
        extra_ivs = 0
    else:
        extra_ivs = (state.mask & ~required_mask).bit_count()
    unused_nature = int(state.has_nature and not require_nature)
    if _normalize_strategy(strategy) == "steps":
        return (
            state.breeds,
            state.purchases,
            extra_ivs,
            unused_nature,
            -state.inventory_breeds,
            -state.existing_leaves,
            state.item_cost,
            tuple(sorted(state.used_ids)),
        )
    # Inventory-first planning should not quietly throw a 5V or natured
    # breeder into a 1V subproblem merely because doing so saves one breed.
    # Purchases remain the first priority, then preservation of surplus value.
    return (
        state.purchases,
        extra_ivs,
        unused_nature,
        state.breeds,
        -state.inventory_breeds,
        -state.existing_leaves,
        state.item_cost,
        tuple(sorted(state.used_ids)),
    )


def _is_goal(
    state: ChainState,
    species_key: str,
    target_mask: int,
    need_nature: bool,
    target_gender: str,
    target_alpha: bool,
) -> bool:
    if normalize_text(state.species) != species_key:
        return False
    if state.mask & target_mask != target_mask:
        return False
    if need_nature and not state.has_nature:
        return False
    if state.is_alpha != target_alpha:
        return False
    return not target_gender or state.gender == target_gender


def _forced_child(
    parent_a: ChainState,
    parent_b: ChainState,
    profile: SpeciesProfile,
    output_gender: str,
    brace_a: int | None = None,
    brace_b: int | None = None,
    everstone_a: bool = False,
    everstone_b: bool = False,
) -> ChainState | None:
    if parent_a.used_ids & parent_b.used_ids:
        return None
    if brace_a is not None and not parent_a.mask & (1 << brace_a):
        return None
    if brace_b is not None and not parent_b.mask & (1 << brace_b):
        return None
    mask = parent_a.mask & parent_b.mask
    if brace_a is not None:
        mask |= 1 << brace_a
    if brace_b is not None:
        mask |= 1 << brace_b
    item_a = "不变之石" if everstone_a else (f"{STAT_NAMES[brace_a]}护腕" if brace_a is not None else "")
    item_b = "不变之石" if everstone_b else (f"{STAT_NAMES[brace_b]}护腕" if brace_b is not None else "")
    child = ChainState(
        species=profile.species,
        gender=output_gender,
        egg_groups=profile.egg_groups,
        mask=mask,
        has_nature=everstone_a or everstone_b,
        nature=parent_a.nature if everstone_a else (parent_b.nature if everstone_b else ""),
        is_alpha=parent_a.is_alpha and parent_b.is_alpha,
        used_ids=parent_a.used_ids | parent_b.used_ids,
        generation=max(parent_a.generation, parent_b.generation) + 1,
        breeds=parent_a.breeds + parent_b.breeds + 1,
        braces=parent_a.braces + parent_b.braces + int(brace_a is not None) + int(brace_b is not None),
        everstones=parent_a.everstones + parent_b.everstones + int(everstone_a) + int(everstone_b),
        purchases=parent_a.purchases + parent_b.purchases,
        inventory_breeds=(
            parent_a.inventory_breeds
            + parent_b.inventory_breeds
            + int(parent_a.purchases + parent_b.purchases == 0)
        ),
        material_v=mask.bit_count(),
        breeding_species=profile.material_species or profile.species,
    )
    child.action = ChainAction(parent_a, parent_b, item_a, item_b)
    return child


def _structured_search(
    leaves: list[ChainState],
    target_profile: SpeciesProfile,
    target_mask: int,
    need_nature: bool,
    target_gender: str,
    beam: int,
    strategy: str = "inventory",
) -> list[ChainState]:
    species_db = get_species_database()
    profile_map: dict[tuple[object, ...], SpeciesProfile] = {}
    for state in leaves:
        if is_ditto(state.species):
            continue
        key = (normalize_text(state.species), _group_key(state.egg_groups))
        existing = profile_map.get(key)
        # Never infer that a species can produce both sexes merely because the
        # box contains one female or one male. Female-only lines such as Jynx
        # can never create the male bridge needed to leave their maternal line;
        # male-only lines such as Tauros/Hitmon remain valid father material.
        record = species_db.get(state.species, fuzzy=True)
        if record is not None:
            allowed = record.allowed_genders
        else:
            observed = set(existing.allowed_genders if existing else ())
            if state.gender in {"F", "M", "N"}:
                observed.add(state.gender)
            allowed = tuple(gender for gender in ("F", "M", "N") if gender in observed) or (state.gender,)
        genderless = allowed == ("N",)
        profile_map[key] = SpeciesProfile(
            state.species,
            key[0],
            tuple(state.egg_groups),
            genderless,
            allowed,
            state.breeding_species or state.species,
        )
    profile_map[(target_profile.species_key, _group_key(target_profile.egg_groups))] = target_profile
    profiles = list(profile_map.values())
    ditto_leaves = [state for state in leaves if is_ditto(state.species)]
    memo: dict[tuple[object, ...], list[ChainState]] = {}
    visiting: set[tuple[object, ...]] = set()

    def rank(state: ChainState, required_mask: int, require_nature: bool) -> tuple[object, ...]:
        return _search_rank(state, strategy, required_mask, require_nature)

    def trim(candidates: list[ChainState], required_mask: int, require_nature: bool) -> list[ChainState]:
        unique: dict[tuple[object, ...], ChainState] = {}
        for state in candidates:
            if not _fits_exact_subproblem(state, required_mask):
                continue
            if require_nature and not state.has_nature:
                continue
            key = (state.used_ids, state.mask, state.has_nature, state.is_alpha)
            current = unique.get(key)
            if current is None or rank(state, required_mask, require_nature) < rank(current, required_mask, require_nature):
                unique[key] = state
        return sorted(
            unique.values(),
            key=lambda state: rank(state, required_mask, require_nature),
        )[:beam]

    def leaf_candidates(profile: SpeciesProfile, gender: str, required_mask: int, require_nature: bool) -> list[ChainState]:
        return [
            state
            for state in leaves
            if not is_ditto(state.species)
            and normalize_text(state.species) == profile.species_key
            and _group_key(state.egg_groups) == _group_key(profile.egg_groups)
            and state.gender == gender
            and _fits_exact_subproblem(state, required_mask)
            and (not require_nature or state.has_nature)
        ]

    def compatible_profiles(profile: SpeciesProfile) -> list[SpeciesProfile]:
        groups = set(_group_key(profile.egg_groups))
        if not groups:
            return []
        return [
            candidate for candidate in profiles
            if "M" in candidate.allowed_genders and groups & set(_group_key(candidate.egg_groups))
        ]

    def ditto_candidates(required_mask: int, require_nature: bool) -> list[ChainState]:
        return [
            state for state in ditto_leaves
            if _fits_exact_subproblem(state, required_mask) and (not require_nature or state.has_nature)
        ]

    def mate_candidates(profile: SpeciesProfile, required_mask: int, require_nature: bool) -> list[ChainState]:
        result = ditto_candidates(required_mask, require_nature)
        for mate_profile in compatible_profiles(profile):
            result.extend(build(mate_profile, "M", required_mask, require_nature))
        return trim(result, required_mask, require_nature)

    def combine_regular(
        profile: SpeciesProfile,
        output_gender: str,
        req_a: int,
        nature_a: bool,
        req_b: int,
        nature_b: bool,
        brace_a: int | None,
        brace_b: int | None,
    ) -> list[ChainState]:
        results: list[ChainState] = []
        if "F" not in profile.allowed_genders or output_gender not in profile.allowed_genders:
            return results
        for parent_a in build(profile, "F", req_a, nature_a):
            for parent_b in mate_candidates(profile, req_b, nature_b):
                child = _forced_child(
                    parent_a,
                    parent_b,
                    profile,
                    output_gender,
                    brace_a,
                    brace_b,
                    nature_a,
                    nature_b,
                )
                if child is not None:
                    results.append(child)
        return results

    def combine_with_ditto(
        profile: SpeciesProfile,
        output_gender: str,
        req_a: int,
        nature_a: bool,
        req_b: int,
        nature_b: bool,
        brace_a: int | None,
        brace_b: int | None,
    ) -> list[ChainState]:
        results: list[ChainState] = []
        if output_gender not in profile.allowed_genders:
            return results
        source_genders = profile.allowed_genders
        for source_gender in source_genders:
            for parent_a in build(profile, source_gender, req_a, nature_a):
                for parent_b in ditto_candidates(req_b, nature_b):
                    child = _forced_child(
                        parent_a,
                        parent_b,
                        profile,
                        output_gender,
                        brace_a,
                        brace_b,
                        nature_a,
                        nature_b,
                    )
                    if child is not None:
                        results.append(child)
        return results

    def build(profile: SpeciesProfile, gender: str, required_mask: int, require_nature: bool) -> list[ChainState]:
        if gender not in profile.allowed_genders:
            return []
        key = (profile.species_key, _group_key(profile.egg_groups), gender, required_mask, require_nature)
        if key in memo:
            return memo[key]
        base = leaf_candidates(profile, gender, required_mask, require_nature)
        if key in visiting:
            return trim(base, required_mask, require_nature)
        visiting.add(key)
        candidates = list(base)
        bits = [index for index in range(6) if required_mask & (1 << index)]

        if require_nature:
            if not bits:
                candidates.extend(combine_regular(profile, gender, 0, True, 0, False, None, None))
                candidates.extend(combine_regular(profile, gender, 0, False, 0, True, None, None))
                candidates.extend(combine_with_ditto(profile, gender, 0, True, 0, False, None, None))
                candidates.extend(combine_with_ditto(profile, gender, 0, False, 0, True, None, None))
            else:
                for stat in bits:
                    holder_mask = required_mask & ~(1 << stat)
                    candidates.extend(combine_regular(profile, gender, holder_mask, True, required_mask, False, None, stat))
                    candidates.extend(combine_regular(profile, gender, required_mask, False, holder_mask, True, stat, None))
                    candidates.extend(combine_with_ditto(profile, gender, holder_mask, True, required_mask, False, None, stat))
                    candidates.extend(combine_with_ditto(profile, gender, required_mask, False, holder_mask, True, stat, None))
        elif len(bits) == 1:
            stat = bits[0]
            candidates.extend(combine_regular(profile, gender, 0, False, required_mask, False, None, stat))
            candidates.extend(combine_regular(profile, gender, required_mask, False, 0, False, stat, None))
            candidates.extend(combine_with_ditto(profile, gender, 0, False, required_mask, False, None, stat))
            candidates.extend(combine_with_ditto(profile, gender, required_mask, False, 0, False, stat, None))
        elif len(bits) >= 2:
            # Explore every valid overlap so an existing non-adjacent 2V/3V
            # material can enter at its real level instead of being projected
            # down to one of the conventional edge branches.
            for stat_a, stat_b in _ordered_stat_pairs(bits):
                req_a = required_mask & ~(1 << stat_b)
                req_b = required_mask & ~(1 << stat_a)
                candidates.extend(combine_regular(profile, gender, req_a, False, req_b, False, stat_a, stat_b))
                candidates.extend(combine_with_ditto(profile, gender, req_a, False, req_b, False, stat_a, stat_b))

        visiting.remove(key)
        memo[key] = trim(candidates, required_mask, require_nature)
        return memo[key]

    desired_genders = (target_gender,) if target_gender else target_profile.allowed_genders
    goals: list[ChainState] = []
    for gender in desired_genders:
        goals.extend(build(target_profile, gender, target_mask, need_nature))
    return trim(goals, target_mask, need_nature)


def _same_species_pyramid(
    leaves: list[ChainState],
    target_profile: SpeciesProfile,
    target_mask: int,
    need_nature: bool,
    target_gender: str,
    max_results: int,
    strategy: str = "inventory",
) -> list[ChainState]:
    """Fast exact allocator for one evolution-line IV pyramid."""
    species_leaves = [
        state for state in leaves
        if normalize_text(state.species) == target_profile.species_key
        and _group_key(state.egg_groups) == _group_key(target_profile.egg_groups)
    ]
    if not species_leaves:
        return []

    branch_limit = max(4, max_results * 2)
    memo: dict[tuple[int, bool, str, frozenset[str]], list[ChainState]] = {}

    def split_pairs(required_mask: int, used: frozenset[str]) -> tuple[tuple[int, int], ...]:
        bits = [index for index in range(6) if required_mask & (1 << index)]
        pairs = list(_ordered_stat_pairs(bits))

        def usefulness(pair: tuple[int, int]) -> int:
            stat_a, stat_b = pair
            req_a = required_mask & ~(1 << stat_b)
            req_b = required_mask & ~(1 << stat_a)
            score = 0
            for state in species_leaves:
                if state.is_virtual or state.used_ids & used:
                    continue
                # Only genuinely reusable multi-V stock should widen the
                # conventional search. A 2V with one irrelevant target stat
                # must not pull the route toward a 1V branch.
                if state.effective_material_v < 2 or state.effective_material_v != state.mask.bit_count():
                    continue
                branch = req_a if state.gender in {"F", "N"} else req_b
                if state.mask == branch:
                    score += 4
                elif state.mask & branch == state.mask:
                    score += 1
            return score

        return tuple(sorted(pairs, key=lambda pair: -usefulness(pair)))

    def rank(state: ChainState, required_mask: int, require_nature: bool) -> tuple[object, ...]:
        return _search_rank(state, strategy, required_mask, require_nature)

    def trim(candidates: list[ChainState], required_mask: int, require_nature: bool) -> list[ChainState]:
        unique: dict[tuple[object, ...], ChainState] = {}
        for state in candidates:
            if not _fits_exact_subproblem(state, required_mask):
                continue
            if require_nature and not state.has_nature:
                continue
            key = (state.used_ids, state.mask, state.has_nature, state.is_alpha)
            current = unique.get(key)
            if current is None or rank(state, required_mask, require_nature) < rank(current, required_mask, require_nature):
                unique[key] = state
        return sorted(
            unique.values(),
            key=lambda state: rank(state, required_mask, require_nature),
        )[:branch_limit]

    def build(required_mask: int, require_nature: bool, gender: str, used: frozenset[str]) -> list[ChainState]:
        memo_key = (required_mask, require_nature, gender, used)
        if memo_key in memo:
            return memo[memo_key]
        direct = [
            state for state in species_leaves
            if not state.used_ids & used
            and state.gender == gender
            and _fits_exact_subproblem(state, required_mask)
            and (not require_nature or state.has_nature)
        ]
        candidates = sorted(
            direct,
            key=lambda state: rank(state, required_mask, require_nature),
        )[:branch_limit]
        bits = [index for index in range(6) if required_mask & (1 << index)]

        if require_nature and bits:
            for stat in _ordered_stats(bits):
                holder_mask = required_mask & ~(1 << stat)
                if target_profile.genderless:
                    for holder in build(holder_mask, True, "N", used):
                        for donor in build(required_mask, False, "N", used | holder.used_ids):
                            child = _forced_child(holder, donor, target_profile, "N", brace_b=stat, everstone_a=True)
                            if child is not None and child.mask & required_mask == required_mask:
                                candidates.append(child)
                    for donor in build(required_mask, False, "N", used):
                        for holder in build(holder_mask, True, "N", used | donor.used_ids):
                            child = _forced_child(donor, holder, target_profile, "N", brace_a=stat, everstone_b=True)
                            if child is not None and child.mask & required_mask == required_mask:
                                candidates.append(child)
                else:
                    # Try both parent-sex orientations. The user's valuable
                    # full-IV breeder may exist on only one side.
                    for holder in build(holder_mask, True, "F", used):
                        for donor in build(required_mask, False, "M", used | holder.used_ids):
                            child = _forced_child(holder, donor, target_profile, gender, brace_b=stat, everstone_a=True)
                            if child is not None and child.mask & required_mask == required_mask:
                                candidates.append(child)
                    for donor in build(required_mask, False, "F", used):
                        for holder in build(holder_mask, True, "M", used | donor.used_ids):
                            child = _forced_child(donor, holder, target_profile, gender, brace_a=stat, everstone_b=True)
                            if child is not None and child.mask & required_mask == required_mask:
                                candidates.append(child)
                if len(candidates) >= branch_limit:
                    result = trim(candidates, required_mask, require_nature)
                    memo[memo_key] = result
                    return result
        elif not require_nature and len(bits) >= 2:
            for stat_a, stat_b in split_pairs(required_mask, used):
                req_a = required_mask & ~(1 << stat_b)
                req_b = required_mask & ~(1 << stat_a)
                parent_gender_a = "N" if target_profile.genderless else "F"
                parent_gender_b = "N" if target_profile.genderless else "M"
                for parent_a in build(req_a, False, parent_gender_a, used):
                    for parent_b in build(req_b, False, parent_gender_b, used | parent_a.used_ids):
                        child = _forced_child(parent_a, parent_b, target_profile, gender, stat_a, stat_b)
                        if child is not None and child.mask & required_mask == required_mask:
                            candidates.append(child)
                            if len(candidates) >= branch_limit:
                                result = trim(candidates, required_mask, require_nature)
                                memo[memo_key] = result
                                return result

        result = trim(candidates, required_mask, require_nature)
        memo[memo_key] = result
        return result

    genders = (target_gender,) if target_gender else target_profile.allowed_genders
    goals: list[ChainState] = []
    for gender in genders:
        goals.extend(build(target_mask, need_nature, gender, frozenset()))
    return sorted(
        goals,
        key=lambda state: rank(state, target_mask, need_nature),
    )[:max_results]


def _canonical_six_iv_pyramid(
    leaves: list[ChainState],
    target_profile: SpeciesProfile,
    target_mask: int,
    need_nature: bool,
    target_gender: str,
    target_alpha: bool,
    max_results: int,
    strategy: str = "inventory",
) -> list[ChainState]:
    """Build a six-value IV route without the combinatorial generic search.

    Six explicitly requested IV values use the same 32-leaf pyramid whether
    the values are 31, 0, 16, or any other exact number.  The generic planner
    deliberately protects exact multi-IV materials and therefore becomes
    expensive when it explores every equivalent market-copy permutation.  A
    six-stat target has only 720 meaningful stat orders, so this allocator
    evaluates those deterministic pyramids while still preferring exact-level
    inventory leaves over purchases.
    """
    if target_mask.bit_count() != 6:
        return []

    target_key = target_profile.species_key
    target_groups = set(_group_key(target_profile.egg_groups))
    Role = tuple[str, str]

    if target_profile.allowed_genders == ("N",):
        parent_roles: tuple[Role, Role] = (("line", "N"), ("ditto", "N"))
    elif target_profile.allowed_genders == ("M",):
        parent_roles = (("line", "M"), ("ditto", "N"))
    else:
        parent_roles = (("line", "F"), ("compatible", "M"))

    def role_matches(state: ChainState, role: Role) -> bool:
        kind, gender = role
        if state.gender != gender:
            return False
        if kind == "ditto":
            return is_ditto(state.species)
        if kind == "line":
            return normalize_text(state.species) == target_key
        if kind == "compatible":
            return (
                normalize_text(state.species) == target_key
                or bool(target_groups & set(_group_key(state.egg_groups)))
            )
        return False

    desired_genders = (target_gender,) if target_gender else target_profile.allowed_genders
    roles: set[Role] = set(parent_roles)
    roles.update(("line", gender) for gender in desired_genders)
    indexed: dict[tuple[Role, int], list[ChainState]] = {}
    for role in roles:
        for state in leaves:
            if not role_matches(state, role):
                continue
            if state.effective_material_v != state.mask.bit_count():
                continue
            indexed.setdefault((role, state.mask), []).append(state)

    def state_rank(state: ChainState, required_mask: int, require_nature: bool) -> tuple[object, ...]:
        return _search_rank(state, strategy, required_mask, require_nature)

    def direct_variants(
        stats: tuple[int, ...],
        role: Role,
        require_nature: bool,
        used: frozenset[str],
    ) -> dict[bool, ChainState]:
        required_mask = sum(1 << stat for stat in stats)
        result: dict[bool, ChainState] = {}
        for state in indexed.get((role, required_mask), []):
            if state.used_ids & used:
                continue
            if require_nature and not state.has_nature:
                continue
            current = result.get(state.is_alpha)
            if current is None or state_rank(state, required_mask, require_nature) < state_rank(
                current, required_mask, require_nature
            ):
                result[state.is_alpha] = state
        return result

    def keep_best(
        result: dict[bool, ChainState],
        state: ChainState | None,
        required_mask: int,
        require_nature: bool,
    ) -> None:
        if state is None:
            return
        current = result.get(state.is_alpha)
        if current is None or state_rank(state, required_mask, require_nature) < state_rank(
            current, required_mask, require_nature
        ):
            result[state.is_alpha] = state

    def can_generate(role: Role) -> bool:
        kind, gender = role
        if kind == "ditto":
            return False
        return gender in target_profile.allowed_genders

    def build_plain(
        stats: tuple[int, ...],
        role: Role,
        used: frozenset[str],
    ) -> dict[bool, ChainState]:
        required_mask = sum(1 << stat for stat in stats)
        result = direct_variants(stats, role, False, used)
        if len(stats) < 2 or not can_generate(role):
            return result

        stat_a, stat_b = stats[0], stats[-1]
        left_variants = build_plain(stats[:-1], parent_roles[0], used)
        for left in left_variants.values():
            right_variants = build_plain(stats[1:], parent_roles[1], used | left.used_ids)
            for right in right_variants.values():
                child = _forced_child(
                    left,
                    right,
                    target_profile,
                    role[1],
                    brace_a=stat_a,
                    brace_b=stat_b,
                )
                keep_best(result, child, required_mask, False)
        return result

    def build_nature(
        stats: tuple[int, ...],
        role: Role,
        used: frozenset[str],
    ) -> dict[bool, ChainState]:
        required_mask = sum(1 << stat for stat in stats)
        result = direct_variants(stats, role, True, used)
        if not stats or not can_generate(role):
            return result

        missing_stat = stats[-1]
        holder_stats = stats[:-1]

        holders_a = build_nature(holder_stats, parent_roles[0], used)
        for holder in holders_a.values():
            donors_b = build_plain(stats, parent_roles[1], used | holder.used_ids)
            for donor in donors_b.values():
                child = _forced_child(
                    holder,
                    donor,
                    target_profile,
                    role[1],
                    brace_b=missing_stat,
                    everstone_a=True,
                )
                keep_best(result, child, required_mask, True)

        donors_a = build_plain(stats, parent_roles[0], used)
        for donor in donors_a.values():
            holders_b = build_nature(holder_stats, parent_roles[1], used | donor.used_ids)
            for holder in holders_b.values():
                child = _forced_child(
                    donor,
                    holder,
                    target_profile,
                    role[1],
                    brace_a=missing_stat,
                    everstone_b=True,
                )
                keep_best(result, child, required_mask, True)
        return result

    all_orders = list(permutations(tuple(range(6))))
    actual_states = [state for state in leaves if not state.is_virtual]
    if not actual_states:
        candidate_orders = [tuple(range(6))]
    else:
        actual_masks = Counter(state.mask for state in actual_states)
        nature_masks = Counter(state.mask for state in actual_states if state.has_nature)

        def order_score(order: tuple[int, ...]) -> tuple[int, int]:
            segment_masks = {
                sum(1 << stat for stat in order[start:end])
                for start in range(6)
                for end in range(start + 1, 7)
            }
            inventory_score = sum(
                actual_masks[mask] * max(1, mask.bit_count()) ** 2
                for mask in segment_masks
            )
            nature_score = sum(
                nature_masks[sum(1 << stat for stat in order[:end])] * end ** 2
                for end in range(7)
            ) if need_nature else 0
            return nature_score, inventory_score

        candidate_orders = sorted(all_orders, key=order_score, reverse=True)[:48]

    goals: list[ChainState] = []
    for stat_order in candidate_orders:
        for gender in desired_genders:
            root_role = ("line", gender)
            variants = (
                build_nature(stat_order, root_role, frozenset())
                if need_nature
                else build_plain(stat_order, root_role, frozenset())
            )
            goal = variants.get(target_alpha)
            if goal is not None:
                goals.append(goal)

    goals.sort(key=lambda state: _state_rank(state, strategy))
    unique: list[ChainState] = []
    seen: set[tuple[object, ...]] = set()
    for goal in goals:
        signature = (
            tuple(sorted(goal.used_ids)),
            goal.gender,
            goal.is_alpha,
            goal.has_nature,
        )
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(goal)
        if len(unique) >= max_results:
            break
    return unique


def _virtual_materials(
    target_profile: SpeciesProfile,
    target_ivs: list[int | None],
    need_nature: bool,
    nature_label: str,
    is_alpha: bool,
    allow_ditto: bool = True,
    existing_leaves: list[ChainState] | None = None,
) -> list[ChainState]:
    """Create conservative purchase placeholders.

    Normal routes start with 1V/nature-only material. Alpha routes start with
    actual 2V material because PokeMMO alpha encounters have a 2V floor; they
    must never be represented as 1V leaves. A complementary multi-IV nature
    holder is added only when the user already owns a full target-IV breeder.
    """
    required_stats = [index for index, value in enumerate(target_ivs) if value is not None]
    target_mask = sum(1 << index for index in required_stats)
    copies = max(4, 2 ** max(0, len(required_stats) - 1))
    alpha_copies = max(2, 2 ** max(0, len(required_stats) - 4))
    base_shapes = (
        [tuple(shape) for shape in combinations(required_stats, 2)]
        if is_alpha and len(required_stats) >= 2
        else [(stat_index,) for stat_index in required_stats]
    )
    result: list[ChainState] = []
    sequence = 0

    def add_material(
        species: str,
        gender: str,
        groups: tuple[str, ...],
        stat_indices: tuple[int, ...],
        has_nature: bool,
        material_copies: int | None = None,
        state_species: str | None = None,
        state_breeding_species: str | None = None,
    ) -> None:
        nonlocal sequence
        for _copy in range(copies if material_copies is None else material_copies):
            sequence += 1
            ivs: list[int | None] = [None] * 6
            mask = 0
            for stat_index in stat_indices:
                ivs[stat_index] = target_ivs[stat_index]
                mask |= 1 << stat_index
            shape = "-".join(str(index) for index in stat_indices) or "none"
            role = "nature" if has_nature else "plain"
            monster = Monster(
                id=f"buy:{sequence}:{species}:{gender}:{shape}:{role}",
                species=species,
                gender=gender,
                nature=nature_label if has_nature else "",
                ivs=ivs,
                egg_groups=list(groups),
                is_alpha=is_alpha,
                source="需要补充",
                verified=True,
            )
            result.append(
                ChainState(
                    species=state_species or species,
                    gender=gender,
                    egg_groups=groups,
                    mask=mask,
                    has_nature=has_nature,
                    nature=nature_label if has_nature else "",
                    is_alpha=is_alpha,
                    used_ids=frozenset({monster.id}),
                    generation=0,
                    breeds=0,
                    braces=0,
                    everstones=0,
                    purchases=1,
                    material_v=mask.bit_count(),
                    breeding_species=state_breeding_species or state_species or species,
                    is_virtual=True,
                    leaf=monster,
                )
            )

    target_material_species = target_profile.material_species or target_profile.species
    generic_male_name = f"{'/'.join(target_profile.egg_groups)}组兼容雄性"

    def market_identity(gender: str) -> tuple[str, str, str]:
        if gender == "M" and target_profile.allowed_genders == ("F", "M"):
            # The label remains species-agnostic, while the planning state is
            # projected onto the target maternal line: paired with a target
            # female, this compatible male produces the target egg species.
            return generic_male_name, target_profile.species, target_material_species
        return target_material_species, target_profile.species, target_material_species

    for gender in target_profile.allowed_genders:
        material_name, state_name, breeding_name = market_identity(gender)
        for shape in base_shapes:
            add_material(
                material_name,
                gender,
                target_profile.egg_groups,
                shape,
                False,
                material_copies=alpha_copies if is_alpha else None,
                state_species=state_name,
                state_breeding_species=breeding_name,
            )
        if need_nature:
            nature_shapes = base_shapes if is_alpha else [()]
            for shape in nature_shapes:
                add_material(
                    material_name,
                    gender,
                    target_profile.egg_groups,
                    shape,
                    True,
                    material_copies=alpha_copies if is_alpha else None,
                    state_species=state_name,
                    state_breeding_species=breeding_name,
                )

    # A full-target IV breeder with the wrong nature should be paired directly
    # with a complementary nature holder from the market.  The holder omits one
    # edge stat so the existing breeder can lock that stat while the holder
    # carries the Everstone, guaranteeing the requested child in one breed.
    has_full_target_breeder = any(
        normalize_text(state.species) == target_profile.species_key
        and _fits_exact_subproblem(state, target_mask)
        and not state.has_nature
        for state in (existing_leaves or [])
    )
    if need_nature and len(required_stats) >= 2 and has_full_target_breeder:
        for missing_stat in dict.fromkeys((required_stats[-1], required_stats[0])):
            complementary_stats = tuple(index for index in required_stats if index != missing_stat)
            if is_alpha and len(complementary_stats) < 2:
                continue
            for gender in target_profile.allowed_genders:
                material_name, state_name, breeding_name = market_identity(gender)
                add_material(
                    material_name,
                    gender,
                    target_profile.egg_groups,
                    complementary_stats,
                    True,
                    material_copies=1,
                    state_species=state_name,
                    state_breeding_species=breeding_name,
                )

    # Genderless and male-only species require Ditto. Female-only species need
    # a male from a compatible egg group; the exact species can be chosen after
    # consulting the user's market/box and does not affect the child species.
    if allow_ditto and target_profile.allowed_genders in {("N",), ("M",)}:
        for shape in base_shapes:
            add_material(
                "百变怪", "N", (), shape, False,
                material_copies=alpha_copies if is_alpha else None,
            )
        if need_nature:
            for shape in (base_shapes if is_alpha else [()]):
                add_material(
                    "百变怪", "N", (), shape, True,
                    material_copies=alpha_copies if is_alpha else None,
                )
    elif target_profile.allowed_genders == ("F",):
        generic_name = f"{'/'.join(target_profile.egg_groups)}组兼容雄性"
        for shape in base_shapes:
            add_material(
                generic_name, "M", target_profile.egg_groups, shape, False,
                material_copies=alpha_copies if is_alpha else None,
            )
        if need_nature:
            for shape in (base_shapes if is_alpha else [()]):
                add_material(
                    generic_name, "M", target_profile.egg_groups, shape, True,
                    material_copies=alpha_copies if is_alpha else None,
                )
    return result


def _direct_market_complements(
    existing_leaves: list[ChainState],
    purchase_leaves: list[ChainState],
    target_profile: SpeciesProfile,
    target_mask: int,
    target_gender: str,
    target_alpha: bool,
    strategy: str,
    max_results: int,
) -> list[ChainState]:
    """Pair a full-IV inventory breeder with a one-stat-short nature holder."""
    desired_genders = (target_gender,) if target_gender else target_profile.allowed_genders
    goals: list[ChainState] = []
    for existing in existing_leaves:
        if normalize_text(existing.species) != target_profile.species_key:
            continue
        if existing.gender not in {"F", "M"} or not _fits_exact_subproblem(existing, target_mask):
            continue
        for purchase in purchase_leaves:
            if not purchase.is_virtual or not purchase.has_nature:
                continue
            if {existing.gender, purchase.gender} != {"F", "M"}:
                continue
            if not set(_group_key(existing.egg_groups)) & set(_group_key(purchase.egg_groups)):
                continue
            # The female determines the egg species. A target-line female may
            # use any compatible male; a target-line male still needs a
            # target-line female from the market.
            if existing.gender == "M" and normalize_text(purchase.species) != target_profile.species_key:
                continue
            missing_stats = [
                index
                for index in range(6)
                if target_mask & (1 << index) and not purchase.mask & (1 << index)
            ]
            if len(missing_stats) != 1:
                continue
            missing_stat = missing_stats[0]
            for output_gender in desired_genders:
                if output_gender not in target_profile.allowed_genders:
                    continue
                if existing.gender == "F":
                    child = _forced_child(
                        existing,
                        purchase,
                        target_profile,
                        output_gender,
                        brace_a=missing_stat,
                        everstone_b=True,
                    )
                else:
                    child = _forced_child(
                        purchase,
                        existing,
                        target_profile,
                        output_gender,
                        brace_b=missing_stat,
                        everstone_a=True,
                    )
                if child is not None and _is_goal(
                    child,
                    target_profile.species_key,
                    target_mask,
                    True,
                    target_gender,
                    target_alpha,
                ):
                    goals.append(child)
    goals.sort(key=lambda state: _state_rank(state, strategy))
    return goals[:max_results]


def find_chain_candidates(
    inventory: list[Monster],
    species: str,
    target_gender: str,
    nature_key: str,
    target_ivs: list[int | None],
    egg_groups: list[str],
    nature_label: str = "",
    max_results: int = 3,
    beam_per_signature: int = 64,
    target_allowed_genders: tuple[str, ...] | None = None,
    target_alpha: bool = False,
    allow_ditto: bool = True,
    strategy: str = "inventory",
    target_family_species: tuple[str, ...] | None = None,
    target_goal_species: tuple[str, ...] | None = None,
    offspring_species: str = "",
    breeding_species: str = "",
    nature_strategy: str = "late",
    allow_alpha_materials: bool = False,
    intermediate_gender_strategy: str = GENDER_STRATEGY_LOCK_ALL,
) -> tuple[list[ChainCandidate], list[str]]:
    strategy = _normalize_strategy(strategy)
    requested_species = species.strip()
    planning_species = offspring_species.strip() or requested_species
    species_key = normalize_text(planning_species)
    family_keys = {
        normalize_text(value)
        for value in (target_family_species or (requested_species,))
        if normalize_text(value)
    }
    goal_keys = {
        normalize_text(value)
        for value in (target_goal_species or (requested_species,))
        if normalize_text(value)
    }
    target_gender = normalize_gender(target_gender)
    target_mask = sum(1 << index for index, value in enumerate(target_ivs) if value is not None)
    need_nature = bool(nature_key)
    species_db = get_species_database()

    def breeding_output_genders(monster: Monster) -> tuple[str, ...]:
        record = species_db.get(monster.species, fuzzy=True)
        if record is None:
            return ()
        offspring = species_db.breeding_offspring(record)
        return offspring.allowed_genders if offspring is not None else ()

    def reusable_outside_target_line(monster: Monster) -> bool:
        gender = normalize_gender(monster.gender)
        if is_ditto(monster.species):
            return allow_ditto
        if gender == "M":
            return True
        if gender != "F":
            return False
        output_genders = breeding_output_genders(monster)
        # Unknown imported species retain the previous permissive behavior;
        # built-in 1-649 data is strict. A female is a reusable bridge only if
        # her offspring line can actually produce a male for the target chain.
        return not output_genders or "M" in output_genders

    inferred_groups = list(egg_groups)
    if not inferred_groups:
        for monster in inventory:
            if normalize_text(monster.species) in family_keys:
                inferred_groups.extend(monster.egg_groups)
    inferred_groups = list(dict.fromkeys(group.strip() for group in inferred_groups if group.strip()))

    confirmed_inventory = [
        monster for monster in inventory
        if monster.verified
        and (
            monster.is_alpha
            if target_alpha
            else allow_alpha_materials or not monster.is_alpha
        )
        and (allow_ditto or not is_ditto(monster.species))
    ]
    target_group_keys = set(_group_key(inferred_groups))
    audit_scope = [
        monster for monster in confirmed_inventory
        if (
            normalize_text(monster.species) in family_keys
            or (allow_ditto and is_ditto(monster.species))
            or bool(target_group_keys & set(_group_key(monster.egg_groups)))
        )
    ]
    audit_inventory = [
        monster for monster in audit_scope
        if normalize_text(monster.species) in family_keys
        or (allow_ditto and is_ditto(monster.species))
        or reusable_outside_target_line(monster)
    ]
    audit_excluded_female_only_count = sum(
        normalize_gender(monster.gender) == "F"
        and normalize_text(monster.species) not in family_keys
        and breeding_output_genders(monster) == ("F",)
        for monster in audit_scope
    )
    audit_histogram = [0] * 7
    for monster in audit_inventory:
        actual_v = sum(value == 31 for value in monster.ivs if value is not None)
        audit_histogram[max(2 if monster.is_alpha else 0, actual_v)] += 1
    audit_nature_count = sum(
        _nature_matches(nature_key, monster.nature)
        for monster in audit_inventory
    ) if need_nature else 0
    audit_target_female_count = sum(
        normalize_gender(monster.gender) == "F" and normalize_text(monster.species) in family_keys
        for monster in audit_inventory
    )
    audit_compatible_male_count = sum(
        normalize_gender(monster.gender) == "M"
        for monster in audit_inventory
    )
    audit_other_female_count = sum(
        normalize_gender(monster.gender) == "F" and normalize_text(monster.species) not in family_keys
        for monster in audit_inventory
    )
    all_leaf_states: list[ChainState] = []
    for index, monster in enumerate(confirmed_inventory):
        mask = 0
        for stat_index, required in enumerate(target_ivs):
            if required is not None and monster.ivs[stat_index] == required:
                mask |= 1 << stat_index
        has_nature = need_nature and _nature_matches(nature_key, monster.nature)
        monster_key = normalize_text(monster.species)
        is_target_family = monster_key in family_keys
        is_goal_form = monster_key in goal_keys
        if not is_target_family and not is_goal_form and not reusable_outside_target_line(monster):
            continue
        if not (mask or has_nature or is_target_family or is_goal_form or is_ditto(monster.species)):
            continue
        state_species = planning_species if is_target_family else monster.species
        state_breeding_species = (
            breeding_species.strip() or planning_species
            if is_target_family
            else monster.species
        )
        groups = tuple(inferred_groups if is_target_family and inferred_groups else monster.egg_groups)
        if not is_target_family and not is_ditto(monster.species):
            record = species_db.get(monster.species, fuzzy=True)
            breedable = species_db.breeding_parent(record) if record else None
            offspring = species_db.breeding_offspring(record) if record else None
            if breedable is None or offspring is None:
                continue
            state_species = offspring.display_name
            state_breeding_species = breedable.display_name
            groups = tuple(breedable.egg_groups)
        leaf_id = monster.id or f"inventory-{index}"
        state = ChainState(
            species=state_species,
            gender=normalize_gender(monster.gender),
            egg_groups=groups,
            mask=mask,
            has_nature=has_nature,
            nature=monster.nature if has_nature else "",
            is_alpha=monster.is_alpha,
            used_ids=frozenset({leaf_id}),
            generation=0,
            breeds=0,
            braces=0,
            everstones=0,
            purchases=0,
            material_v=max(
                2 if monster.is_alpha else 0,
                mask.bit_count(),
                sum(value == 31 for value in monster.ivs if value is not None),
            ),
            breeding_species=state_breeding_species,
            is_virtual=False,
            leaf=monster,
        )
        all_leaf_states.append(state)

    # Large breeder boxes often contain dozens of mechanically identical 1V
    # materials. Keep enough interchangeable copies for a full 5V pyramid but
    # avoid making the recursive search compare hundreds of equivalent IDs.
    per_signature_limit = max(8, 2 ** max(0, target_mask.bit_count() - 1))
    pruned: list[ChainState] = []
    signature_counts: Counter[tuple[object, ...]] = Counter()
    for state in all_leaf_states:
        signature = (
            normalize_text(state.species),
            state.gender,
            _group_key(state.egg_groups),
            state.mask,
            state.has_nature,
            state.is_alpha,
            is_ditto(state.species),
        )
        if signature_counts[signature] >= per_signature_limit:
            continue
        signature_counts[signature] += 1
        pruned.append(state)
    all_leaf_states = pruned

    existing_goals = [
        state for state in all_leaf_states
        if state.leaf is not None
        and normalize_text(state.leaf.species) in goal_keys
        and state.mask & target_mask == target_mask
        and (not need_nature or state.has_nature)
        and state.is_alpha == target_alpha
        and (not target_gender or state.gender == target_gender)
    ]
    target_states = [state for state in all_leaf_states if normalize_text(state.species) == species_key]
    target_genderless = bool(target_states) and all(state.gender == "N" for state in target_states)
    allowed_genders = target_allowed_genders or (("N",) if target_genderless else ("F", "M"))
    target_profile = SpeciesProfile(
        planning_species,
        species_key,
        tuple(inferred_groups),
        allowed_genders == ("N",),
        allowed_genders,
        breeding_species.strip() or planning_species,
    )
    if existing_goals:
        goals = existing_goals
    elif target_mask.bit_count() == 6:
        goals = _canonical_six_iv_pyramid(
            all_leaf_states,
            target_profile,
            target_mask,
            need_nature,
            target_gender,
            target_alpha,
            max_results,
            strategy,
        )
        if not goals:
            purchase_leaves = _virtual_materials(
                target_profile,
                target_ivs,
                need_nature,
                nature_label.strip() or nature_key,
                target_alpha,
                allow_ditto,
                all_leaf_states,
            )
            goals = _canonical_six_iv_pyramid(
                all_leaf_states + purchase_leaves,
                target_profile,
                target_mask,
                need_nature,
                target_gender,
                target_alpha,
                max_results,
                strategy,
            )
    else:
        goals = _same_species_pyramid(
            all_leaf_states,
            target_profile,
            target_mask,
            need_nature,
            target_gender,
            max_results,
            strategy,
        )
        goals = [goal for goal in goals if goal.is_alpha == target_alpha]
        if not goals:
            goals = _structured_search(
                all_leaf_states,
                target_profile,
                target_mask,
                need_nature,
                target_gender,
                beam_per_signature,
                strategy,
            )
            goals = [goal for goal in goals if goal.is_alpha == target_alpha]

        if not goals:
            purchase_leaves = _virtual_materials(
                target_profile,
                target_ivs,
                need_nature,
                nature_label.strip() or nature_key,
                target_alpha,
                allow_ditto,
                all_leaf_states,
            )
            leaves_with_purchases = all_leaf_states + purchase_leaves
            goals = _direct_market_complements(
                all_leaf_states,
                purchase_leaves,
                target_profile,
                target_mask,
                target_gender,
                target_alpha,
                strategy,
                max_results,
            ) if need_nature else []
            if not goals:
                goals = _same_species_pyramid(
                    leaves_with_purchases,
                    target_profile,
                    target_mask,
                    need_nature,
                    target_gender,
                    max_results,
                    strategy,
                )
                goals = [goal for goal in goals if goal.is_alpha == target_alpha]
                target_group_key = set(_group_key(target_profile.egg_groups))
                has_compatible_actual = any(
                    is_ditto(state.species)
                    or (
                        normalize_text(state.species) != target_profile.species_key
                        and bool(target_group_key & set(_group_key(state.egg_groups)))
                    )
                    for state in all_leaf_states
                )
                has_compatible_market_parent = any(
                    state.is_virtual
                    and normalize_text(state.species) != target_profile.species_key
                    and (
                        is_ditto(state.species)
                        or bool(target_group_key & set(_group_key(state.egg_groups)))
                    )
                    for state in purchase_leaves
                )
                if (
                    has_compatible_actual
                    or has_compatible_market_parent
                    or target_profile.allowed_genders != ("F", "M")
                ):
                    goals.extend(_structured_search(
                        leaves_with_purchases,
                        target_profile,
                        target_mask,
                        need_nature,
                        target_gender,
                        beam_per_signature,
                        strategy,
                    ))
                    goals = [goal for goal in goals if goal.is_alpha == target_alpha]

    goals = [goal for goal in goals if goal.is_alpha == target_alpha]
    goals.sort(key=lambda state: _state_rank(state, strategy))
    unique: list[ChainState] = []
    seen_signatures: set[tuple[object, ...]] = set()
    for goal in goals:
        actual_ids = tuple(sorted(identifier for identifier in goal.used_ids if not identifier.startswith("buy:")))
        virtual_shapes = Counter(
            ":".join(identifier.split(":", 2)[2:])
            for identifier in goal.used_ids
            if identifier.startswith("buy:")
        )
        signature = (
            actual_ids,
            tuple(sorted(virtual_shapes.items())),
            goal.mask,
            goal.has_nature,
            goal.is_alpha,
            goal.gender,
        )
        if signature in seen_signatures:
            continue
        unique.append(goal)
        seen_signatures.add(signature)
        if len(unique) >= max_results:
            break

    missing = _missing_requirements(
        all_leaf_states,
        confirmed_inventory,
        requested_species,
        species_key,
        family_keys,
        nature_label.strip() or nature_key,
        target_ivs,
        inferred_groups,
        target_alpha,
        allow_ditto,
        allow_alpha_materials,
    )
    if not unique and not allow_ditto and allowed_genders == ("M",):
        missing.append("该目标的当前孵化规则需要百变怪；请勾选“允许使用百变怪”")
    if not unique and not missing:
        missing.append("现有素材数量或性别/蛋组组合不足；需要补充可兼容素材，或检查库存中的性别和蛋组是否填写完整")
    candidates = [
        ChainCandidate(
            root=state,
            target_ivs=target_ivs,
            target_nature=nature_label.strip() or nature_key,
            target_gender=target_gender,
            target_alpha=target_alpha,
            target_species=requested_species,
            offspring_species=planning_species,
            breeding_species=breeding_species.strip() or planning_species,
            nature_strategy="chain" if str(nature_strategy).strip().lower() == "chain" else "late",
            gender_strategy=normalize_intermediate_gender_strategy(intermediate_gender_strategy),
            inventory_pool_size=len(audit_inventory),
            inventory_iv_histogram=tuple(audit_histogram),
            inventory_nature_count=audit_nature_count,
            inventory_target_female_count=audit_target_female_count,
            inventory_compatible_male_count=audit_compatible_male_count,
            inventory_other_female_count=audit_other_female_count,
            inventory_excluded_female_only_count=audit_excluded_female_only_count,
        )
        for state in unique
    ]
    if candidates and candidates[0].root.purchases:
        missing = candidates[0].purchase_requirements()
    return candidates, missing


def _normalize_nature_for_chain(value: str) -> str:
    # Kept local to avoid a circular import with planner.py.
    aliases = {
        "固执": "adamant", "大胆": "bold", "勇敢": "brave", "温和": "calm", "沉着": "calm",
        "慎重": "careful", "坦率": "docile", "温顺": "gentle",
        "勤奋": "hardy", "急躁": "hasty", "淘气": "impish", "爽朗": "jolly",
        "乐天": "lax", "松懈": "lax", "孤独": "lonely", "怕寂寞": "lonely", "慢吞吞": "mild",
        "内敛": "modest", "天真": "naive", "顽皮": "naughty", "冷静": "quiet",
        "马虎": "rash", "悠闲": "relaxed", "自大": "sassy", "认真": "serious",
        "胆小": "timid", "浮躁": "quirky", "害羞": "bashful",
        "无修正": "neutral", "无修正（任一）": "neutral", "无属性增减": "neutral",
    }
    compact = normalize_text(value)
    return aliases.get(compact, compact)


def _nature_matches(target_key: str, value: str) -> bool:
    candidate_key = _normalize_nature_for_chain(value)
    if target_key == "neutral":
        return candidate_key in NEUTRAL_NATURE_KEYS
    return bool(target_key) and candidate_key == target_key


def _missing_requirements(
    leaves: list[ChainState],
    inventory: list[Monster],
    species: str,
    species_key: str,
    family_keys: set[str],
    nature_key: str,
    target_ivs: list[int | None],
    groups: list[str],
    target_alpha: bool = False,
    allow_ditto: bool = True,
    allow_alpha_materials: bool = False,
) -> list[str]:
    missing: list[str] = []
    if not any(normalize_text(monster.species) in family_keys for monster in inventory):
        kind = "头目" if target_alpha else ("普通或头目" if allow_alpha_materials else "普通")
        missing.append(f"至少一只{kind}目标种类 {species}，用于保留子代种类")
    if not groups and not (allow_ditto and any(is_ditto(monster.species) for monster in inventory)):
        missing.append("目标种类的蛋组信息" + ("，或一只百变怪" if allow_ditto else ""))
    for index, required in enumerate(target_ivs):
        if required is not None and not any(state.mask & (1 << index) for state in leaves):
            missing.append(f"{STAT_NAMES[index]} IV={required} 的素材")
    if nature_key and not any(state.has_nature for state in leaves):
        missing.append(f"性格为 {nature_key} 的素材")
    if inventory and not any(normalize_gender(monster.gender) in {"M", "F", "N"} for monster in inventory):
        missing.append("素材性别信息")
    return missing
