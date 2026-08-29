from __future__ import annotations

from dataclasses import dataclass, field
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
    has_hidden_ability: bool = False
    inherited_moves: frozenset[str] = field(default_factory=frozenset)
    # Selected egg moves that enter the target maternal line at this breed.
    # This is presentation metadata for the mind map, not an extra mechanic.
    introduced_moves: frozenset[str] = field(default_factory=frozenset)
    # Certain staged nature-hand children must be a specific sex even when
    # the user's general intermediate-gender strategy allows random results.
    force_gender_lock: bool = False
    # True once this branch was bootstrapped from a target-line male + Ditto
    # specifically to establish the female maternal spine.
    maternal_conversion: bool = False
    # PokeMMO has gender-linked families whose child species name changes with
    # the chosen gender (currently Nidoran♀/Nidoran♂). ``species`` remains the
    # canonical planner identity; this mapping is the real hatch result.
    gender_species: tuple[tuple[str, str], ...] = ()

    @property
    def output_species(self) -> str:
        return dict(self.gender_species).get(self.gender, self.species)

    @property
    def item_cost(self) -> int:
        return self.braces * BRACE_COST

    @property
    def existing_leaves(self) -> int:
        return len(self.used_ids) - self.purchases

    @property
    def effective_material_v(self) -> int:
        return max(self.material_v, self.mask.bit_count())

    def to_dict(self) -> dict[str, object]:
        return {
            "species": self.species,
            "gender": self.gender,
            "egg_groups": list(self.egg_groups),
            "mask": self.mask,
            "has_nature": self.has_nature,
            "nature": self.nature,
            "is_alpha": self.is_alpha,
            "used_ids": sorted(self.used_ids),
            "generation": self.generation,
            "breeds": self.breeds,
            "braces": self.braces,
            "everstones": self.everstones,
            "purchases": self.purchases,
            "inventory_breeds": self.inventory_breeds,
            "material_v": self.material_v,
            "breeding_species": self.breeding_species,
            "is_virtual": self.is_virtual,
            "leaf": self.leaf.to_dict() if self.leaf is not None else None,
            "action": (
                {
                    "parent_a": self.action.parent_a.to_dict(),
                    "parent_b": self.action.parent_b.to_dict(),
                    "item_a": self.action.item_a,
                    "item_b": self.action.item_b,
                }
                if self.action is not None
                else None
            ),
            "has_hidden_ability": self.has_hidden_ability,
            "inherited_moves": sorted(self.inherited_moves),
            "introduced_moves": sorted(self.introduced_moves),
            "force_gender_lock": self.force_gender_lock,
            "maternal_conversion": self.maternal_conversion,
            "gender_species": [list(item) for item in self.gender_species],
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "ChainState":
        leaf_value = value.get("leaf")
        state = cls(
            species=str(value.get("species", "")),
            gender=str(value.get("gender", "")),
            egg_groups=tuple(str(item) for item in value.get("egg_groups", []) or []),
            mask=int(value.get("mask", 0) or 0),
            has_nature=bool(value.get("has_nature", False)),
            nature=str(value.get("nature", "")),
            is_alpha=bool(value.get("is_alpha", False)),
            used_ids=frozenset(str(item) for item in value.get("used_ids", []) or []),
            generation=int(value.get("generation", 0) or 0),
            breeds=int(value.get("breeds", 0) or 0),
            braces=int(value.get("braces", 0) or 0),
            everstones=int(value.get("everstones", 0) or 0),
            purchases=int(value.get("purchases", 0) or 0),
            inventory_breeds=int(value.get("inventory_breeds", 0) or 0),
            material_v=int(value.get("material_v", 0) or 0),
            breeding_species=str(value.get("breeding_species", "")),
            is_virtual=bool(value.get("is_virtual", False)),
            leaf=Monster.from_dict(leaf_value) if isinstance(leaf_value, dict) else None,
            has_hidden_ability=bool(value.get("has_hidden_ability", False)),
            inherited_moves=frozenset(str(item) for item in value.get("inherited_moves", []) or []),
            introduced_moves=frozenset(str(item) for item in value.get("introduced_moves", []) or []),
            force_gender_lock=bool(value.get("force_gender_lock", False)),
            maternal_conversion=bool(value.get("maternal_conversion", False)),
            gender_species=tuple(
                (str(item[0]), str(item[1]))
                for item in value.get("gender_species", []) or []
                if isinstance(item, (list, tuple)) and len(item) >= 2
            ),
        )
        action_value = value.get("action")
        if isinstance(action_value, dict):
            parent_a = action_value.get("parent_a")
            parent_b = action_value.get("parent_b")
            if isinstance(parent_a, dict) and isinstance(parent_b, dict):
                state.action = ChainAction(
                    cls.from_dict(parent_a),
                    cls.from_dict(parent_b),
                    str(action_value.get("item_a", "")),
                    str(action_value.get("item_b", "")),
                )
        return state


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
    """Return ``fixed``, ``locked``, ``random`` or ``irrelevant``.

    The search tree keeps a concrete gender so it can prove that a route is
    feasible.  This policy is an execution overlay: a random low-tier child is
    recorded with its actual gender and the remaining route is then rebuilt.
    """
    # If this child feeds directly into Ditto, either sex is mechanically
    # valid.  Recording a made-up proof-state gender here used to trigger an
    # unnecessary global replan and could discard the child just produced.
    if sibling is not None and is_ditto(sibling.species):
        return "irrelevant"
    if state.force_gender_lock:
        return "locked"
    if state is root:
        return "locked" if normalize_gender(target_gender) in {"F", "M"} else "random"

    record = get_species_database().get(state.output_species, fuzzy=True)
    if not state.gender_species and record is not None and record.allowed_genders != ("F", "M"):
        return "fixed"

    # A normal two-sex target is raised through one maternal spine.  Every
    # intermediate child on that spine must remain female so the next
    # same-egg-group male donor still produces the requested species.  Donor
    # branches can continue to use the selected smart/minimal locking policy.
    if (
        normalize_text(state.species) == normalize_text(root.species)
        and normalize_gender(state.gender) == "F"
    ):
        return "locked"

    # The direct donor half that joins a normal female branch must be male.
    # This applies even under the smart/minimal overlays: leaving it random
    # would make the already-built female spine unusable half of the time.
    if (
        sibling is not None
        and not is_ditto(sibling.species)
        and normalize_gender(sibling.gender) == "F"
        and normalize_gender(state.gender) == "M"
    ):
        return "locked"

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
    # The IV-first phase may deliberately keep a female breeding body even
    # when the finished Pokemon has no requested gender (or must eventually
    # be male).  ``target_gender`` remains the user's final requirement;
    # ``working_gender`` controls only this candidate's generated root.
    working_gender: str = ""
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
    target_hidden_ability: bool = False
    target_moves: tuple[str, ...] = ()
    # ``maternal`` raises the target female body. ``gamble_upper`` and
    # ``gamble_lower`` are conditional nature-hand attempts. ``promote`` and
    # ``guarantee`` finish an already resolved nature branch with Everstones.
    nature_phase: str = ""
    nature_attempt_level: int = 0
    nature_target_key: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "root": self.root.to_dict(),
            "target_ivs": self.target_ivs,
            "target_nature": self.target_nature,
            "target_gender": self.target_gender,
            "working_gender": self.working_gender,
            "target_alpha": self.target_alpha,
            "target_species": self.target_species,
            "offspring_species": self.offspring_species,
            "breeding_species": self.breeding_species,
            "nature_strategy": self.nature_strategy,
            "gender_strategy": self.gender_strategy,
            "inventory_pool_size": self.inventory_pool_size,
            "inventory_iv_histogram": list(self.inventory_iv_histogram),
            "inventory_nature_count": self.inventory_nature_count,
            "inventory_target_female_count": self.inventory_target_female_count,
            "inventory_compatible_male_count": self.inventory_compatible_male_count,
            "inventory_other_female_count": self.inventory_other_female_count,
            "inventory_excluded_female_only_count": self.inventory_excluded_female_only_count,
            "target_hidden_ability": self.target_hidden_ability,
            "target_moves": list(self.target_moves),
            "nature_phase": self.nature_phase,
            "nature_attempt_level": self.nature_attempt_level,
            "nature_target_key": self.nature_target_key,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "ChainCandidate":
        root_value = value.get("root")
        if not isinstance(root_value, dict):
            raise ValueError("孵化路线快照缺少根节点。")
        return cls(
            root=ChainState.from_dict(root_value),
            target_ivs=[item if item is None else int(item) for item in value.get("target_ivs", []) or []],
            target_nature=str(value.get("target_nature", "")),
            target_gender=str(value.get("target_gender", "")),
            working_gender=str(value.get("working_gender", "")),
            target_alpha=bool(value.get("target_alpha", False)),
            target_species=str(value.get("target_species", "")),
            offspring_species=str(value.get("offspring_species", "")),
            breeding_species=str(value.get("breeding_species", "")),
            nature_strategy=str(value.get("nature_strategy", "late")),
            gender_strategy=str(value.get("gender_strategy", GENDER_STRATEGY_LOCK_ALL)),
            inventory_pool_size=int(value.get("inventory_pool_size", 0) or 0),
            inventory_iv_histogram=tuple(int(item) for item in value.get("inventory_iv_histogram", []) or []),
            inventory_nature_count=int(value.get("inventory_nature_count", 0) or 0),
            inventory_target_female_count=int(value.get("inventory_target_female_count", 0) or 0),
            inventory_compatible_male_count=int(value.get("inventory_compatible_male_count", 0) or 0),
            inventory_other_female_count=int(value.get("inventory_other_female_count", 0) or 0),
            inventory_excluded_female_only_count=int(value.get("inventory_excluded_female_only_count", 0) or 0),
            target_hidden_ability=bool(value.get("target_hidden_ability", False)),
            target_moves=tuple(str(item) for item in value.get("target_moves", []) or []),
            nature_phase=str(value.get("nature_phase", "")),
            nature_attempt_level=int(value.get("nature_attempt_level", 0) or 0),
            nature_target_key=str(value.get("nature_target_key", "")),
        )

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
            where = f"（{monster.position_label}）" if monster.position_label else ""
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
            output_species = state.output_species
            if state is self.root and self.target_species and self.target_species != output_species:
                stage_note = f"；孵化后进化为最终目标 {self.target_species}"
            elif state is not self.root and state.breeding_species and state.breeding_species != output_species:
                stage_note = f"；再次参与孵化前进化为 {state.breeding_species}"
            gender_policy = child_gender_policy(
                state,
                self.root,
                self.working_gender or self.target_gender,
                self.gender_strategy,
                sibling,
            )
            if gender_policy == "locked":
                gender_locks += 1
                gender_text = f"指定{gender_name(state.gender)}"
            elif gender_policy == "fixed":
                gender_text = f"固定{gender_name(state.gender)}"
            elif gender_policy == "irrelevant":
                gender_text = "无需确认性别（下一步与百变怪孵化）"
            else:
                gender_text = "不指定性别（孵出后记录实际结果并重算）"
            steps.append(
                f"步骤 {number}\n"
                f"  父母 A：{left}\n"
                f"  父母 B：{right}\n"
                f"  道具：{item_text}\n"
                f"  子代：{gender_text}，得到 {'头目' if state.is_alpha else '普通'} {output_species}；"
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
                checkpoint = target_exact - 1
                target_label = (
                    f"{target_v}V + {'、'.join(custom_values)}（共 {target_exact} 项精确）"
                    if custom_values
                    else f"{target_v}V"
                )
                if self.nature_phase == "gamble_upper":
                    summary += (
                        f"\n性格策略：主动赌性格手第 1 轮；{target_label} 雌性母体已经完成但未命中"
                        f" {self.target_nature}，本轮先制作 {self.nature_attempt_level} 项精确的雄性性格手，"
                        "孵出后必须确认性格，再决定是否继续降级。"
                    )
                elif self.nature_phase == "gamble_lower":
                    summary += (
                        f"\n性格策略：主动赌性格手第 2 轮；上一档雄性性格手未命中，"
                        f"本轮制作 {self.nature_attempt_level} 项精确的雌性性格手并再次确认。"
                    )
                elif self.nature_phase == "promote":
                    summary += (
                        "\n性格策略：低一档雌性性格手已经命中；用不变之石逐级升档，"
                        f"最后与 {target_label} 母体合成目标性格成品。"
                    )
                elif self.nature_phase == "guarantee":
                    summary += (
                        "\n性格策略：可制造的逐级随机性格手均未命中，或已经到达头目 2V/普通最低档；"
                        "现进入最终保底。仅在这一阶段购买最低档对性素材或百变怪，"
                        "再用不变之石逐级升档。"
                    )
                elif self.nature_phase == "maternal" or not self.root.has_nature:
                    summary += (
                        f"\n性格策略：母体优先；先完成 {target_label} 雌性母体主线，"
                        f"仅从 {checkpoint} 项精确起记录是否爆出 {self.target_nature}。"
                        "命中后立即重算；最终仍未命中时，再按雄性、雌性、最低档保底逐级赌性格手。"
                    )
                elif custom_values:
                    summary += (
                        f"\n性格策略：后置性格收尾；使用现有 {target_label} 主线 + "
                        f"少一项精确的 {self.target_nature} 性格手合成，最后一步使用不变之石。"
                    )
                else:
                    summary += (
                        f"\n性格策略：已经命中可用的 {self.target_nature} 性格素材；"
                        f"与现有 {target_v}V 母体主线逐级合成，后续只使用不变之石保留性格。"
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
    gender_species: tuple[tuple[str, str], ...] = ()

    def species_for_gender(self, gender: str) -> str:
        return dict(self.gender_species).get(gender, self.species)

    def breeding_species_for_gender(self, gender: str) -> str:
        if self.gender_species:
            return self.species_for_gender(gender)
        return self.material_species or self.species


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


def _material_usage_signature(used_ids: frozenset[str]) -> tuple[object, ...]:
    """Collapse interchangeable market copies without merging real inventory.

    Virtual material IDs contain a sequence number so separate copies can be
    consumed safely. That sequence is not mechanically meaningful when the
    beam search deduplicates candidate routes; keeping it there lets dozens of
    equivalent purchase permutations crowd out a distinct inventory route.
    """
    actual_ids = tuple(sorted(identifier for identifier in used_ids if not identifier.startswith("buy:")))
    virtual_shapes = Counter(
        ":".join(identifier.split(":", 2)[2:])
        for identifier in used_ids
        if identifier.startswith("buy:")
    )
    return actual_ids, tuple(sorted(virtual_shapes.items()))


def _is_goal(
    state: ChainState,
    species_key: str,
    target_mask: int,
    need_nature: bool,
    target_gender: str,
    target_alpha: bool,
    need_hidden_ability: bool = False,
    target_moves: frozenset[str] = frozenset(),
) -> bool:
    if normalize_text(state.species) != species_key:
        return False
    if state.mask & target_mask != target_mask:
        return False
    if need_nature and not state.has_nature:
        return False
    if state.is_alpha != target_alpha:
        return False
    if need_hidden_ability and not state.has_hidden_ability:
        return False
    if not target_moves.issubset(state.inherited_moves):
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
    inherited_moves = parent_a.inherited_moves | parent_b.inherited_moves
    target_line_moves = frozenset().union(*(
        parent.inherited_moves
        for parent in (parent_a, parent_b)
        if normalize_text(parent.species) == profile.species_key
    ))
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
        breeding_species=profile.breeding_species_for_gender(output_gender),
        # HA potential only passes from a parent on the child's evolution line.
        # A random same-egg-group father carrying HA is not sufficient.
        has_hidden_ability=any(
            parent.has_hidden_ability
            and normalize_text(parent.species) == profile.species_key
            for parent in (parent_a, parent_b)
        ),
        inherited_moves=inherited_moves,
        introduced_moves=inherited_moves - target_line_moves,
        maternal_conversion=parent_a.maternal_conversion or parent_b.maternal_conversion,
        gender_species=profile.gender_species,
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
    preferred_ditto_ids: frozenset[str] = frozenset(),
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
        if state.gender_species:
            allowed = tuple(gender for gender, _species in state.gender_species)
        elif record is not None:
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
            state.gender_species,
        )
    profile_map[(target_profile.species_key, _group_key(target_profile.egg_groups))] = target_profile
    profiles = list(profile_map.values())
    ditto_leaves = [state for state in leaves if is_ditto(state.species)]
    memo: dict[tuple[object, ...], list[ChainState]] = {}
    visiting: set[tuple[object, ...]] = set()

    def rank(state: ChainState, required_mask: int, require_nature: bool) -> tuple[object, ...]:
        # Treat an explicitly preferred inventory Ditto as a planning
        # constraint.  This preserves multi-stage bridges such as
        # 2V same-group -> 3V -> Ditto -> 4V during beam pruning.
        ditto_penalty = int(
            bool(preferred_ditto_ids)
            and not bool(state.used_ids & preferred_ditto_ids)
        )
        return (
            ditto_penalty,
            *_search_rank(state, strategy, required_mask, require_nature),
        )

    def trim(candidates: list[ChainState], required_mask: int, require_nature: bool) -> list[ChainState]:
        unique: dict[tuple[object, ...], ChainState] = {}
        for state in candidates:
            if not _fits_exact_subproblem(state, required_mask):
                continue
            if require_nature and not state.has_nature:
                continue
            key = (
                _material_usage_signature(state.used_ids),
                normalize_text(state.species),
                state.gender,
                _group_key(state.egg_groups),
                state.mask,
                state.has_nature,
                state.is_alpha,
                state.has_hidden_ability,
                state.inherited_moves,
            )
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

    def direct_compatible_males(
        profile: SpeciesProfile,
        required_mask: int,
        require_nature: bool,
    ) -> list[ChainState]:
        groups = set(_group_key(profile.egg_groups))
        if not groups:
            return []
        return [
            state for state in leaves
            if not is_ditto(state.species)
            and state.gender == "M"
            and bool(groups & set(_group_key(state.egg_groups)))
            and _fits_exact_subproblem(state, required_mask)
            and (not require_nature or state.has_nature)
        ]

    def mate_candidates(profile: SpeciesProfile, required_mask: int, require_nature: bool) -> list[ChainState]:
        # A target child follows its female parent.  Existing target-line males
        # may be used directly, but recursively manufacturing every donor as
        # another target-line male creates several unnecessary target maternal
        # pyramids.  Recurse only through non-target compatible lines; this
        # leaves one target female spine and builds the other branches from any
        # compatible egg-group species.
        result = ditto_candidates(required_mask, require_nature)
        result.extend(direct_compatible_males(profile, required_mask, require_nature))
        for mate_profile in compatible_profiles(profile):
            if mate_profile.species_key == target_profile.species_key:
                continue
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


def _genderless_line_pyramid(
    leaves: list[ChainState],
    target_profile: SpeciesProfile,
    target_mask: int,
    need_nature: bool,
    max_results: int,
    strategy: str = "inventory",
) -> list[ChainState]:
    """Fast deterministic allocator for genderless same-line parents."""
    species_leaves = [
        state for state in leaves
        if normalize_text(state.species) == target_profile.species_key
        and state.gender == "N"
    ]
    if not species_leaves:
        return []
    bits = tuple(index for index in range(6) if target_mask & (1 << index))
    orders = list(permutations(bits))[:48]
    goals: list[ChainState] = []

    for order in orders:
        memo: dict[tuple[tuple[int, ...], bool, frozenset[str]], ChainState | None] = {}

        def build(stats: tuple[int, ...], require_nature: bool, used: frozenset[str]) -> ChainState | None:
            key = (stats, require_nature, used)
            if key in memo:
                return memo[key]
            required_mask = sum(1 << stat for stat in stats)
            direct = sorted(
                (
                    state for state in species_leaves
                    if not state.used_ids & used
                    and _fits_exact_subproblem(state, required_mask)
                    and (not require_nature or state.has_nature)
                ),
                key=lambda state: _search_rank(state, strategy, required_mask, require_nature),
            )
            options: list[ChainState] = direct[:1]
            if require_nature and stats:
                missing_stat = stats[-1]
                holder = build(stats[:-1], True, used)
                if holder is not None:
                    donor = build(stats, False, used | holder.used_ids)
                    if donor is not None:
                        child = _forced_child(
                            holder,
                            donor,
                            target_profile,
                            "N",
                            brace_b=missing_stat,
                            everstone_a=True,
                        )
                        if child is not None:
                            options.append(child)
            elif not require_nature and len(stats) >= 2:
                stat_a, stat_b = stats[0], stats[-1]
                left = build(stats[:-1], False, used)
                if left is not None:
                    right = build(stats[1:], False, used | left.used_ids)
                    if right is not None:
                        child = _forced_child(
                            left, right, target_profile, "N", stat_a, stat_b
                        )
                        if child is not None:
                            options.append(child)
            result = min(
                options,
                key=lambda state: _search_rank(state, strategy, required_mask, require_nature),
                default=None,
            )
            memo[key] = result
            return result

        goal = build(order, need_nature, frozenset())
        if goal is not None:
            goals.append(goal)

    goals.sort(key=lambda state: _state_rank(state, strategy))
    unique: list[ChainState] = []
    seen: set[tuple[object, ...]] = set()
    for goal in goals:
        signature = (tuple(sorted(goal.used_ids)), goal.has_nature, goal.is_alpha)
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(goal)
        if len(unique) >= max_results:
            break
    return unique


def _same_species_pyramid(
    leaves: list[ChainState],
    target_profile: SpeciesProfile,
    target_mask: int,
    need_nature: bool,
    target_gender: str,
    max_results: int,
    strategy: str = "inventory",
    preferred_ditto_ids: frozenset[str] = frozenset(),
) -> list[ChainState]:
    """Build one target maternal spine plus compatible donor branches.

    For two-sex species the target line is always carried by a female parent.
    Every recursively manufactured mate belongs to a compatible egg-group
    line, so the tree does not incorrectly duplicate the target species across
    both halves.  Direct target-line males already in inventory remain usable.
    """
    target_groups = set(_group_key(target_profile.egg_groups))
    target_key = target_profile.species_key
    if not any(normalize_text(state.species) == target_key for state in leaves):
        return []
    # Inventory-only combinations are handled by the generic beam search,
    # which is better at sparse boxes.  This allocator is the deterministic
    # market-completion path where reusable virtual copies are available.
    if not any(state.is_virtual for state in leaves):
        return []

    species_db = get_species_database()
    # Two alternatives per recursive subproblem are enough to preserve an
    # inventory-first and a purchase fallback route.  Larger beams multiply
    # rapidly because each branch carries a distinct used-material set.
    branch_limit = 2
    memo: dict[tuple[str, int, bool, str, frozenset[str]], list[ChainState]] = {}

    def groups_overlap(left: ChainState, right: ChainState) -> bool:
        return bool(set(_group_key(left.egg_groups)) & set(_group_key(right.egg_groups)))

    def profile_for_maternal_state(state: ChainState) -> SpeciesProfile:
        record = species_db.get(state.species, fuzzy=True)
        allowed = (
            tuple(gender for gender, _species in state.gender_species)
            if state.gender_species
            else record.allowed_genders if record is not None else ("F", "M")
        )
        return SpeciesProfile(
            state.species,
            normalize_text(state.species),
            tuple(state.egg_groups),
            allowed == ("N",),
            allowed,
            state.breeding_species or state.species,
            state.gender_species,
        )

    def rank(state: ChainState, required_mask: int, require_nature: bool) -> tuple[object, ...]:
        ditto_penalty = int(
            bool(preferred_ditto_ids)
            and not bool(state.used_ids & preferred_ditto_ids)
        )
        return (
            ditto_penalty,
            *_search_rank(state, strategy, required_mask, require_nature),
        )

    def split_pairs(required_mask: int, role: str, used: frozenset[str]) -> tuple[tuple[int, int], ...]:
        bits = [index for index in range(6) if required_mask & (1 << index)]
        pairs = list(_ordered_stat_pairs(bits))

        def usefulness(pair: tuple[int, int]) -> int:
            stat_a, stat_b = pair
            req_a = required_mask & ~(1 << stat_b)
            req_b = required_mask & ~(1 << stat_a)
            score = 0
            for state in leaves:
                if state.is_virtual or state.used_ids & used:
                    continue
                if state.mask not in {req_a, req_b} or state.effective_material_v != state.mask.bit_count():
                    continue
                state_key = normalize_text(state.species)
                if role == "line" and state_key == target_key:
                    score += 8
                elif is_ditto(state.species):
                    score += 10 if state.used_ids & preferred_ditto_ids else 5
                elif target_groups & set(_group_key(state.egg_groups)):
                    score += 6
            return score

        return tuple(sorted(pairs, key=lambda pair: -usefulness(pair)))

    def trim(candidates: list[ChainState], required_mask: int, require_nature: bool) -> list[ChainState]:
        unique: dict[tuple[object, ...], ChainState] = {}
        for state in candidates:
            if not _fits_exact_subproblem(state, required_mask):
                continue
            if require_nature and not state.has_nature:
                continue
            key = (
                state.used_ids,
                normalize_text(state.species),
                state.gender,
                state.has_nature,
                state.is_alpha,
                state.has_hidden_ability,
                state.inherited_moves,
            )
            current = unique.get(key)
            if current is None or rank(state, required_mask, require_nature) < rank(
                current, required_mask, require_nature
            ):
                unique[key] = state
        return sorted(
            unique.values(),
            key=lambda state: rank(state, required_mask, require_nature),
        )[:branch_limit]

    def direct(
        role: str,
        required_mask: int,
        require_nature: bool,
        gender: str,
        used: frozenset[str],
    ) -> list[ChainState]:
        result: list[ChainState] = []
        for state in leaves:
            if state.used_ids & used or is_ditto(state.species):
                continue
            if state.gender != gender or not _fits_exact_subproblem(state, required_mask):
                continue
            if require_nature and not state.has_nature:
                continue
            state_key = normalize_text(state.species)
            if role == "line":
                if state_key != target_key:
                    continue
            else:
                if not target_groups & set(_group_key(state.egg_groups)):
                    continue
                # The only recursively preserved target maternal line belongs
                # to role=line.  A target male already in the box is still a
                # perfectly valid direct donor.
                if gender == "F" and state_key == target_key:
                    continue
            result.append(state)
        return result

    def direct_ditto(
        required_mask: int,
        require_nature: bool,
        used: frozenset[str],
    ) -> list[ChainState]:
        return [
            state for state in leaves
            if is_ditto(state.species)
            and not state.used_ids & used
            and _fits_exact_subproblem(state, required_mask)
            and (not require_nature or state.has_nature)
        ]

    def regular_child(
        role: str,
        parent_a: ChainState,
        parent_b: ChainState,
        output_gender: str,
        brace_a: int | None = None,
        brace_b: int | None = None,
        everstone_a: bool = False,
        everstone_b: bool = False,
    ) -> ChainState | None:
        if parent_a.gender != "F" or parent_b.gender != "M" or not groups_overlap(parent_a, parent_b):
            return None
        profile = target_profile if role == "line" else profile_for_maternal_state(parent_a)
        if output_gender not in profile.allowed_genders:
            return None
        return _forced_child(
            parent_a,
            parent_b,
            profile,
            output_gender,
            brace_a,
            brace_b,
            everstone_a,
            everstone_b,
        )

    def ditto_child(
        source: ChainState,
        ditto: ChainState,
        output_gender: str,
        brace_source: int | None = None,
        brace_ditto: int | None = None,
        everstone_source: bool = False,
        everstone_ditto: bool = False,
    ) -> ChainState | None:
        profile = target_profile if normalize_text(source.species) == target_key else profile_for_maternal_state(source)
        if output_gender not in profile.allowed_genders:
            return None
        return _forced_child(
            source,
            ditto,
            profile,
            output_gender,
            brace_source,
            brace_ditto,
            everstone_source,
            everstone_ditto,
        )

    def build(
        role: str,
        required_mask: int,
        require_nature: bool,
        gender: str,
        used: frozenset[str],
    ) -> list[ChainState]:
        memo_key = (role, required_mask, require_nature, gender, used)
        if memo_key in memo:
            return memo[memo_key]
        candidates = trim(
            direct(role, required_mask, require_nature, gender, used),
            required_mask,
            require_nature,
        )
        if len(candidates) >= branch_limit:
            memo[memo_key] = candidates
            return candidates
        bits = [index for index in range(6) if required_mask & (1 << index)]

        if require_nature and bits:
            for stat in _ordered_stats(bits):
                holder_mask = required_mask & ~(1 << stat)
                if role == "line" and target_profile.allowed_genders in {("N",), ("M",)}:
                    source_genders = target_profile.allowed_genders
                    for source_gender in source_genders:
                        for holder in build("line", holder_mask, True, source_gender, used):
                            for ditto in direct_ditto(required_mask, False, used | holder.used_ids):
                                child = ditto_child(
                                    holder, ditto, gender, brace_ditto=stat, everstone_source=True
                                )
                                if child is not None:
                                    candidates.append(child)
                                    if len(candidates) >= branch_limit:
                                        result = trim(candidates, required_mask, require_nature)
                                        memo[memo_key] = result
                                        return result
                        for source in build("line", required_mask, False, source_gender, used):
                            for ditto in direct_ditto(holder_mask, True, used | source.used_ids):
                                child = ditto_child(
                                    source, ditto, gender, brace_source=stat, everstone_ditto=True
                                )
                                if child is not None:
                                    candidates.append(child)
                                    if len(candidates) >= branch_limit:
                                        result = trim(candidates, required_mask, require_nature)
                                        memo[memo_key] = result
                                        return result
                else:
                    left_role = role
                    for holder in build(left_role, holder_mask, True, "F", used):
                        for donor in build("donor", required_mask, False, "M", used | holder.used_ids):
                            child = regular_child(
                                role, holder, donor, gender, brace_b=stat, everstone_a=True
                            )
                            if child is not None:
                                candidates.append(child)
                                if len(candidates) >= branch_limit:
                                    result = trim(candidates, required_mask, require_nature)
                                    memo[memo_key] = result
                                    return result
                    for source in build(left_role, required_mask, False, "F", used):
                        for holder in build("donor", holder_mask, True, "M", used | source.used_ids):
                            child = regular_child(
                                role, source, holder, gender, brace_a=stat, everstone_b=True
                            )
                            if child is not None:
                                candidates.append(child)
                                if len(candidates) >= branch_limit:
                                    result = trim(candidates, required_mask, require_nature)
                                    memo[memo_key] = result
                                    return result

                    # Ditto can convert either sex of a compatible line into
                    # the requested donor sex while preserving the same IV
                    # overlap and nature rules.
                    if role == "donor":
                        for source_gender in ("F", "M"):
                            for holder in build("donor", holder_mask, True, source_gender, used):
                                for ditto in direct_ditto(required_mask, False, used | holder.used_ids):
                                    child = ditto_child(
                                        holder, ditto, gender, brace_ditto=stat, everstone_source=True
                                    )
                                    if child is not None:
                                        candidates.append(child)
                                        if len(candidates) >= branch_limit:
                                            result = trim(candidates, required_mask, require_nature)
                                            memo[memo_key] = result
                                            return result
                            for source in build("donor", required_mask, False, source_gender, used):
                                for ditto in direct_ditto(holder_mask, True, used | source.used_ids):
                                    child = ditto_child(
                                        source, ditto, gender, brace_source=stat, everstone_ditto=True
                                    )
                                    if child is not None:
                                        candidates.append(child)
                                        if len(candidates) >= branch_limit:
                                            result = trim(candidates, required_mask, require_nature)
                                            memo[memo_key] = result
                                            return result
        elif not require_nature and len(bits) >= 2:
            for stat_a, stat_b in split_pairs(required_mask, role, used):
                req_a = required_mask & ~(1 << stat_b)
                req_b = required_mask & ~(1 << stat_a)
                left_role = role
                for parent_a in build(left_role, req_a, False, "F", used):
                    for parent_b in build("donor", req_b, False, "M", used | parent_a.used_ids):
                        child = regular_child(role, parent_a, parent_b, gender, stat_a, stat_b)
                        if child is not None:
                            candidates.append(child)
                            if len(candidates) >= branch_limit:
                                result = trim(candidates, required_mask, require_nature)
                                memo[memo_key] = result
                                return result

                source_role = "line" if role == "line" else "donor"
                source_genders = target_profile.allowed_genders if role == "line" else ("F", "M")
                for source_gender in source_genders:
                    for source in build(source_role, req_a, False, source_gender, used):
                        for ditto in direct_ditto(req_b, False, used | source.used_ids):
                            child = ditto_child(source, ditto, gender, stat_a, stat_b)
                            if child is not None:
                                candidates.append(child)
                                if len(candidates) >= branch_limit:
                                    result = trim(candidates, required_mask, require_nature)
                                    memo[memo_key] = result
                                    return result
                    for source in build(source_role, req_b, False, source_gender, used):
                        for ditto in direct_ditto(req_a, False, used | source.used_ids):
                            child = ditto_child(source, ditto, gender, stat_b, stat_a)
                            if child is not None:
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
        goals.extend(build("line", target_mask, need_nature, gender, frozenset()))
    return sorted(
        goals,
        key=lambda state: rank(state, target_mask, need_nature),
    )[:max_results]


def _maternal_spine_pyramid(
    leaves: list[ChainState],
    target_profile: SpeciesProfile,
    target_mask: int,
    need_nature: bool,
    target_gender: str,
    max_results: int,
    strategy: str = "inventory",
    preferred_ditto_ids: frozenset[str] = frozenset(),
    need_hidden_ability: bool = False,
) -> list[ChainState]:
    """Deterministically build one target-female spine and donor pyramids.

    A finite set of stat orders is evaluated instead of recursively comparing
    every equivalent purchase-copy permutation.  Each donor route stays in one
    shared egg group, so arbitrary compatible inventory species can be used
    without pretending that their offspring are already the target species.
    """
    if "F" not in target_profile.allowed_genders or not any(state.is_virtual for state in leaves):
        return []
    target_key = target_profile.species_key
    stat_bits = tuple(index for index in range(6) if target_mask & (1 << index))
    if not stat_bits:
        return []
    route_groups = tuple(dict.fromkeys(group for group in target_profile.egg_groups if group.strip()))
    if not route_groups:
        return []
    species_db = get_species_database()
    line_index: dict[tuple[str, int], list[ChainState]] = {}
    donor_index: dict[tuple[str, str, int], list[ChainState]] = {}
    ditto_index: dict[int, list[ChainState]] = {}
    route_group_keys = {normalize_text(group) for group in route_groups}
    for state in leaves:
        if is_ditto(state.species):
            ditto_index.setdefault(state.mask, []).append(state)
            continue
        state_key = normalize_text(state.species)
        if state_key == target_key:
            line_index.setdefault((state.gender, state.mask), []).append(state)
        for group_key in route_group_keys & set(_group_key(state.egg_groups)):
            if state.gender == "F" and state_key == target_key and state.is_virtual:
                continue
            donor_index.setdefault((group_key, state.gender, state.mask), []).append(state)

    def state_rank(state: ChainState, required_mask: int, require_nature: bool) -> tuple[object, ...]:
        ditto_penalty = int(
            bool(preferred_ditto_ids)
            and not bool(state.used_ids & preferred_ditto_ids)
        )
        return (
            ditto_penalty,
            *_search_rank(state, strategy, required_mask, require_nature),
        )

    actual_states = [state for state in leaves if not state.is_virtual]
    all_orders = list(permutations(stat_bits))

    def order_score(order: tuple[int, ...]) -> tuple[int, int, int]:
        segment_masks = {
            sum(1 << stat for stat in order[start:end])
            for start in range(len(order))
            for end in range(start + 1, len(order) + 1)
        }
        preferred_ditto_score = sum(
            20 * state.mask.bit_count()
            for state in actual_states
            if state.used_ids & preferred_ditto_ids and state.mask in segment_masks
        )
        nature_score = sum(
            state.mask.bit_count() ** 2
            for state in actual_states
            if state.has_nature and state.mask in segment_masks
        ) if need_nature else 0
        inventory_score = sum(
            max(1, state.mask.bit_count()) ** 2
            for state in actual_states
            if state.mask in segment_masks
        )
        return preferred_ditto_score, nature_score, inventory_score

    candidate_orders = sorted(all_orders, key=order_score, reverse=True)[:120]
    goals: list[ChainState] = []

    for route_group in route_groups:
        route_group_key = normalize_text(route_group)
        memo: dict[tuple[str, tuple[int, ...], bool, str, frozenset[str]], ChainState | None] = {}

        def in_route_group(state: ChainState) -> bool:
            return route_group_key in _group_key(state.egg_groups)

        def profile_for_source(state: ChainState) -> SpeciesProfile:
            if state.gender_species:
                allowed = tuple(gender for gender, _species in state.gender_species)
            elif state.species.endswith("组兼容素材"):
                allowed = ("F", "M")
            else:
                record = species_db.get(state.species, fuzzy=True)
                allowed = record.allowed_genders if record is not None else ("F", "M")
            return SpeciesProfile(
                state.species,
                normalize_text(state.species),
                tuple(state.egg_groups),
                allowed == ("N",),
                allowed,
                state.breeding_species or state.species,
                state.gender_species,
            )

        def direct_candidates(
            role: str,
            stats: tuple[int, ...],
            require_nature: bool,
            gender: str,
            used: frozenset[str],
        ) -> list[ChainState]:
            required_mask = sum(1 << stat for stat in stats)
            source = (
                line_index.get((gender, required_mask), [])
                if role == "line"
                else donor_index.get((route_group_key, gender, required_mask), [])
            )
            result: list[ChainState] = []
            for state in source:
                if state.used_ids & used or not _fits_exact_subproblem(state, required_mask):
                    continue
                if require_nature and not state.has_nature:
                    continue
                if role == "line" and need_hidden_ability and not state.has_hidden_ability:
                    continue
                result.append(state)
            return sorted(
                result,
                key=lambda state: state_rank(state, required_mask, require_nature),
            )

        def direct_dittos(
            stats: tuple[int, ...],
            require_nature: bool,
            used: frozenset[str],
        ) -> list[ChainState]:
            required_mask = sum(1 << stat for stat in stats)
            result = [
                state for state in ditto_index.get(required_mask, [])
                if not state.used_ids & used
                and _fits_exact_subproblem(state, required_mask)
                and (not require_nature or state.has_nature)
            ]
            return sorted(
                result,
                key=lambda state: state_rank(state, required_mask, require_nature),
            )

        def make_regular(
            role: str,
            female: ChainState,
            male: ChainState,
            output_gender: str,
            brace_female: int | None = None,
            brace_male: int | None = None,
            everstone_female: bool = False,
            everstone_male: bool = False,
        ) -> ChainState | None:
            if female.gender != "F" or male.gender != "M":
                return None
            if not set(_group_key(female.egg_groups)) & set(_group_key(male.egg_groups)):
                return None
            profile = target_profile if role == "line" else profile_for_source(female)
            if output_gender not in profile.allowed_genders:
                return None
            return _forced_child(
                female,
                male,
                profile,
                output_gender,
                brace_female,
                brace_male,
                everstone_female,
                everstone_male,
            )

        def make_with_ditto(
            role: str,
            source: ChainState,
            ditto: ChainState,
            output_gender: str,
            brace_source: int | None = None,
            brace_ditto: int | None = None,
            everstone_source: bool = False,
            everstone_ditto: bool = False,
        ) -> ChainState | None:
            profile = target_profile if role == "line" else profile_for_source(source)
            if output_gender not in profile.allowed_genders:
                return None
            return _forced_child(
                source,
                ditto,
                profile,
                output_gender,
                brace_source,
                brace_ditto,
                everstone_source,
                everstone_ditto,
            )

        def choose(
            candidates: list[ChainState | None],
            role: str,
            stats: tuple[int, ...],
            require_nature: bool,
        ) -> ChainState | None:
            required_mask = sum(1 << stat for stat in stats)
            valid = [
                state for state in candidates
                if state is not None
                and _fits_exact_subproblem(state, required_mask)
                and (not require_nature or state.has_nature)
                and (role != "line" or not need_hidden_ability or state.has_hidden_ability)
            ]
            return min(
                valid,
                key=lambda state: state_rank(state, required_mask, require_nature),
                default=None,
            )

        def build(
            role: str,
            stats: tuple[int, ...],
            require_nature: bool,
            gender: str,
            used: frozenset[str],
        ) -> ChainState | None:
            key = (role, stats, require_nature, gender, used)
            if key in memo:
                return memo[key]
            options: list[ChainState | None] = direct_candidates(
                role, stats, require_nature, gender, used
            )[:2]

            if require_nature and stats:
                missing_stat = stats[-1]
                holder_stats = stats[:-1]
                holder = build(role, holder_stats, True, "F", used)
                if holder is not None:
                    donor = build("donor", stats, False, "M", used | holder.used_ids)
                    if donor is not None:
                        options.append(make_regular(
                            role,
                            holder,
                            donor,
                            gender,
                            brace_male=missing_stat,
                            everstone_female=True,
                        ))
                source = build(role, stats, False, "F", used)
                if source is not None:
                    nature_donor = build("donor", holder_stats, True, "M", used | source.used_ids)
                    if nature_donor is not None:
                        options.append(make_regular(
                            role,
                            source,
                            nature_donor,
                            gender,
                            brace_female=missing_stat,
                            everstone_male=True,
                        ))
                if role == "donor":
                    for source_gender in ("F", "M"):
                        holder = build("donor", holder_stats, True, source_gender, used)
                        if holder is not None:
                            for ditto in direct_dittos(stats, False, used | holder.used_ids)[:2]:
                                options.append(make_with_ditto(
                                    role,
                                    holder,
                                    ditto,
                                    gender,
                                    brace_ditto=missing_stat,
                                    everstone_source=True,
                                ))
                        source = build("donor", stats, False, source_gender, used)
                        if source is not None:
                            for ditto in direct_dittos(holder_stats, True, used | source.used_ids)[:2]:
                                options.append(make_with_ditto(
                                    role,
                                    source,
                                    ditto,
                                    gender,
                                    brace_source=missing_stat,
                                    everstone_ditto=True,
                                ))
            elif not require_nature and len(stats) >= 2:
                stat_a, stat_b = stats[0], stats[-1]
                left_stats = stats[:-1]
                right_stats = stats[1:]
                female = build(role, left_stats, False, "F", used)
                if female is not None:
                    male = build("donor", right_stats, False, "M", used | female.used_ids)
                    if male is not None:
                        options.append(make_regular(
                            role, female, male, gender, stat_a, stat_b
                        ))

                source_role = role
                source_genders = target_profile.allowed_genders if role == "line" else ("F", "M")
                for source_gender in source_genders:
                    source = build(source_role, left_stats, False, source_gender, used)
                    if source is not None:
                        for ditto in direct_dittos(right_stats, False, used | source.used_ids)[:2]:
                            options.append(make_with_ditto(
                                role, source, ditto, gender, stat_a, stat_b
                            ))
                    source = build(source_role, right_stats, False, source_gender, used)
                    if source is not None:
                        for ditto in direct_dittos(left_stats, False, used | source.used_ids)[:2]:
                            options.append(make_with_ditto(
                                role, source, ditto, gender, stat_b, stat_a
                            ))

            result = choose(options, role, stats, require_nature)
            memo[key] = result
            return result

        for order in candidate_orders:
            desired_genders = (target_gender,) if target_gender else target_profile.allowed_genders
            for gender in desired_genders:
                goal = build("line", order, need_nature, gender, frozenset())
                if goal is not None:
                    goals.append(goal)

    goals.sort(key=lambda state: state_rank(state, target_mask, need_nature))
    unique: list[ChainState] = []
    seen: set[tuple[object, ...]] = set()
    for goal in goals:
        signature = (
            tuple(sorted(goal.used_ids)),
            goal.gender,
            goal.is_alpha,
            goal.has_nature,
            goal.has_hidden_ability,
            goal.inherited_moves,
        )
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(goal)
        if len(unique) >= max_results:
            break
    return unique


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
    ) -> dict[tuple[bool, bool, frozenset[str]], ChainState]:
        required_mask = sum(1 << stat for stat in stats)
        result: dict[tuple[bool, bool, frozenset[str]], ChainState] = {}
        for state in indexed.get((role, required_mask), []):
            if state.used_ids & used:
                continue
            if require_nature and not state.has_nature:
                continue
            variant_key = (state.is_alpha, state.has_hidden_ability, state.inherited_moves)
            current = result.get(variant_key)
            if current is None or state_rank(state, required_mask, require_nature) < state_rank(
                current, required_mask, require_nature
            ):
                result[variant_key] = state
        return result

    def keep_best(
        result: dict[tuple[bool, bool, frozenset[str]], ChainState],
        state: ChainState | None,
        required_mask: int,
        require_nature: bool,
    ) -> None:
        if state is None:
            return
        variant_key = (state.is_alpha, state.has_hidden_ability, state.inherited_moves)
        current = result.get(variant_key)
        if current is None or state_rank(state, required_mask, require_nature) < state_rank(
            current, required_mask, require_nature
        ):
            result[variant_key] = state

    def can_generate(role: Role) -> bool:
        kind, gender = role
        if kind == "ditto":
            return False
        return gender in target_profile.allowed_genders

    def build_plain(
        stats: tuple[int, ...],
        role: Role,
        used: frozenset[str],
    ) -> dict[tuple[bool, bool, frozenset[str]], ChainState]:
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
    ) -> dict[tuple[bool, bool, frozenset[str]], ChainState]:
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
            goals.extend(
                state for key, state in variants.items()
                if key[0] == target_alpha
            )

    goals.sort(key=lambda state: _state_rank(state, strategy))
    unique: list[ChainState] = []
    seen: set[tuple[object, ...]] = set()
    for goal in goals:
        signature = (
            tuple(sorted(goal.used_ids)),
            goal.gender,
            goal.is_alpha,
            goal.has_nature,
            goal.has_hidden_ability,
            goal.inherited_moves,
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
    need_hidden_ability: bool = False,
    target_moves: frozenset[str] = frozenset(),
    egg_move_donors: dict[str, tuple[str, ...]] | None = None,
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
        state_gender_species: tuple[tuple[str, str], ...] = (),
        has_hidden_ability: bool = False,
        inherited_moves: frozenset[str] = frozenset(),
        role_suffix: str = "",
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
            if role_suffix:
                role = f"{role}-{role_suffix}"
            monster = Monster(
                id=f"buy:{sequence}:{species}:{gender}:{shape}:{role}",
                species=species,
                gender=gender,
                nature=nature_label if has_nature else "",
                ivs=ivs,
                egg_groups=list(groups),
                is_alpha=is_alpha,
                has_hidden_ability=has_hidden_ability,
                moves=sorted(inherited_moves),
                account="待采购",
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
                    has_hidden_ability=has_hidden_ability,
                    inherited_moves=inherited_moves,
                    gender_species=state_gender_species,
                )
            )

    generic_profiles = [
        (f"{group}组兼容素材", (group,))
        for group in target_profile.egg_groups
        if group.strip()
    ]

    # For ordinary two-sex species, only the female purchase belongs to the
    # target maternal line.  The donor side is a separate compatible egg-group
    # line and may use either sex while it is being raised to the required IV
    # level.  Male-only and genderless targets still use their own line with
    # Ditto, handled below.
    line_genders = (
        ("F",)
        if "F" in target_profile.allowed_genders
        else target_profile.allowed_genders
    )
    for gender in line_genders:
        target_material_species = target_profile.breeding_species_for_gender(gender)
        for shape in base_shapes:
            add_material(
                target_material_species,
                gender,
                target_profile.egg_groups,
                shape,
                False,
                material_copies=alpha_copies if is_alpha else None,
                state_species=target_profile.species,
                state_breeding_species=target_material_species,
                state_gender_species=target_profile.gender_species,
                # A market placeholder for a requested HA route represents a
                # target-line parent whose HA has already been verified.  For
                # alpha targets this is also the normal game state: alpha
                # parents carry their hidden-ability potential by default.
                has_hidden_ability=need_hidden_ability,
            )
        if need_nature:
            nature_shapes = base_shapes if is_alpha else [()]
            for shape in nature_shapes:
                add_material(
                    target_material_species,
                    gender,
                    target_profile.egg_groups,
                    shape,
                    True,
                    material_copies=alpha_copies if is_alpha else None,
                    state_species=target_profile.species,
                    state_breeding_species=target_material_species,
                    state_gender_species=target_profile.gender_species,
                    has_hidden_ability=need_hidden_ability,
                )

    if "F" in target_profile.allowed_genders:
        for generic_name, generic_groups in generic_profiles:
            for gender in ("F", "M"):
                material_label = (
                    f"{'/'.join(target_profile.egg_groups)}组兼容雄性"
                    if gender == "M"
                    else f"{'/'.join(target_profile.egg_groups)}组兼容雌性"
                )
                for shape in base_shapes:
                    add_material(
                        material_label,
                        gender,
                        generic_groups,
                        shape,
                        False,
                        material_copies=alpha_copies if is_alpha else None,
                        state_species=generic_name,
                        state_breeding_species=generic_name,
                        role_suffix="egg-group-branch",
                    )
                if need_nature:
                    for shape in (base_shapes if is_alpha else [()]):
                        add_material(
                            material_label,
                            gender,
                            generic_groups,
                            shape,
                            True,
                            material_copies=alpha_copies if is_alpha else None,
                            state_species=generic_name,
                            state_breeding_species=generic_name,
                            role_suffix="egg-group-branch",
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
            if "F" in target_profile.allowed_genders:
                target_material_species = target_profile.breeding_species_for_gender("F")
                add_material(
                    target_material_species,
                    "F",
                    target_profile.egg_groups,
                    complementary_stats,
                    True,
                    material_copies=1,
                    state_species=target_profile.species,
                    state_breeding_species=target_material_species,
                    state_gender_species=target_profile.gender_species,
                    has_hidden_ability=need_hidden_ability,
                )
                for generic_name, generic_groups in generic_profiles:
                    add_material(
                        f"{'/'.join(target_profile.egg_groups)}组兼容雄性",
                        "M",
                        generic_groups,
                        complementary_stats,
                        True,
                        material_copies=1,
                        state_species=generic_name,
                        state_breeding_species=generic_name,
                        role_suffix="egg-group-branch",
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
    if need_hidden_ability:
        feature_shape = base_shapes[0] if base_shapes else ()
        feature_genders = (
            ("F",)
            if "F" in target_profile.allowed_genders
            else tuple(
                gender for gender in target_profile.allowed_genders if gender in {"M", "N"}
            )
        ) or ("F",)
        for gender in feature_genders:
            target_material_species = target_profile.breeding_species_for_gender(gender)
            add_material(
                target_material_species,
                gender,
                target_profile.egg_groups,
                feature_shape,
                False,
                material_copies=max(2, alpha_copies if is_alpha else 2),
                state_species=target_profile.species,
                state_breeding_species=target_material_species,
                state_gender_species=target_profile.gender_species,
                has_hidden_ability=need_hidden_ability,
                role_suffix="hidden-ability",
            )
    if target_moves:
        species_db = get_species_database()
        donor_map = egg_move_donors or {}
        for move in sorted(target_moves):
            donor_names = donor_map.get(move, ())
            added = False
            for donor_name in donor_names:
                donor_record = species_db.get(donor_name, fuzzy=True)
                donor_parent = species_db.breeding_parent(donor_record) if donor_record else None
                donor_offspring = species_db.breeding_offspring(donor_record) if donor_record else None
                if donor_parent is None or donor_offspring is None or "M" not in donor_offspring.allowed_genders:
                    continue
                donor_groups = tuple(donor_parent.egg_groups)
                if not set(_group_key(donor_groups)) & set(_group_key(target_profile.egg_groups)):
                    continue
                for shape in (base_shapes or [()]):
                    add_material(
                        donor_parent.display_name,
                        "M",
                        donor_groups,
                        shape,
                        False,
                        material_copies=1,
                        state_species=donor_offspring.display_name,
                        state_breeding_species=donor_parent.display_name,
                        inherited_moves=frozenset({move}),
                        role_suffix=f"egg-move-{move}",
                    )
                added = True
            if not added:
                generic_donor = f"携带{move}的{'/'.join(target_profile.egg_groups)}组雄性"
                for shape in (base_shapes or [()]):
                    add_material(
                        generic_donor,
                        "M",
                        target_profile.egg_groups,
                        shape,
                        False,
                        material_copies=1,
                        inherited_moves=frozenset({move}),
                        role_suffix=f"egg-move-{move}",
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


def _direct_ditto_complements(
    leaves: list[ChainState],
    target_profile: SpeciesProfile,
    target_mask: int,
    need_nature: bool,
    target_gender: str,
    target_alpha: bool,
    target_moves: frozenset[str],
    need_hidden_ability: bool,
) -> list[ChainState]:
    """Surface one-breed target-line + Ditto routes explicitly.

    The general pyramid search aggressively deduplicates equivalent IV states;
    without this pass an enabled inventory Ditto can disappear behind an
    otherwise identical female/male pair before the final preference sort.
    """
    target_leaves = [
        state for state in leaves
        if normalize_text(state.species) == target_profile.species_key and not is_ditto(state.species)
    ]
    dittos = [state for state in leaves if is_ditto(state.species)]
    desired_genders = (target_gender,) if target_gender else target_profile.allowed_genders
    goals: list[ChainState] = []
    stats = [index for index in range(6) if target_mask & (1 << index)]
    for target_parent in target_leaves:
        for ditto in dittos:
            if target_parent.used_ids & ditto.used_ids or target_parent.is_alpha != ditto.is_alpha:
                continue
            for output_gender in desired_genders:
                for brace_target in [None, *stats]:
                    for brace_ditto in [None, *stats]:
                        if brace_target is not None and brace_ditto == brace_target:
                            continue
                        everstone_target = bool(need_nature and target_parent.has_nature)
                        everstone_ditto = bool(need_nature and not everstone_target and ditto.has_nature)
                        if need_nature and not (everstone_target or everstone_ditto):
                            continue
                        selected_target_brace = None if everstone_target else brace_target
                        selected_ditto_brace = None if everstone_ditto else brace_ditto
                        child = _forced_child(
                            target_parent,
                            ditto,
                            target_profile,
                            output_gender,
                            brace_a=selected_target_brace,
                            brace_b=selected_ditto_brace,
                            everstone_a=everstone_target,
                            everstone_b=everstone_ditto,
                        )
                        if child is not None and _is_goal(
                            child,
                            target_profile.species_key,
                            target_mask,
                            need_nature,
                            target_gender,
                            target_alpha,
                            need_hidden_ability,
                            target_moves,
                        ):
                            goals.append(child)
    return goals


def _nature_target_signature(
    species_key: str,
    nature_key: str,
    target_ivs: list[int | None],
    target_alpha: bool,
    need_hidden_ability: bool,
    target_moves: frozenset[str],
) -> str:
    """Stable key used to resume one staged nature-hand route."""
    iv_key = "/".join("x" if value is None else str(value) for value in target_ivs)
    move_key = ",".join(sorted(normalize_text(move) for move in target_moves))
    return "|".join(
        (
            species_key,
            normalize_text(nature_key),
            iv_key,
            "alpha" if target_alpha else "normal",
            "ha" if need_hidden_ability else "regular",
            move_key,
        )
    )


def _profile_for_hand_state(state: ChainState) -> SpeciesProfile:
    """Return a breeding profile for a concrete or generic compatible hand."""
    if state.gender_species:
        allowed = tuple(gender for gender, _species in state.gender_species)
        return SpeciesProfile(
            state.species,
            normalize_text(state.species),
            tuple(state.egg_groups),
            False,
            allowed,
            state.breeding_species or state.output_species,
            state.gender_species,
        )
    record = get_species_database().get(state.species, fuzzy=True)
    if record is not None:
        offspring = get_species_database().breeding_offspring(record)
        parent = get_species_database().breeding_parent(record)
        allowed = offspring.allowed_genders if offspring is not None else record.allowed_genders
        species = offspring.display_name if offspring is not None else state.species
        material_species = parent.display_name if parent is not None else (state.breeding_species or state.species)
    else:
        allowed = ("F", "M") if state.gender in {"F", "M"} else (state.gender,)
        species = state.species
        material_species = state.breeding_species or state.species
    return SpeciesProfile(
        species,
        normalize_text(species),
        tuple(state.egg_groups),
        allowed == ("N",),
        allowed,
        material_species,
    )


def _plain_nature_hand_goals(
    existing_leaves: list[ChainState],
    target_profile: SpeciesProfile,
    target_ivs: list[int | None],
    candidate_masks: Iterable[int],
    output_gender: str,
    target_alpha: bool,
    allow_ditto: bool,
    strategy: str,
    beam: int,
    preferred_ditto_ids: frozenset[str],
) -> list[ChainState]:
    """Build a random-nature compatible hand without consuming a nature hit.

    The current goal is intentionally a donor branch, not the final species.
    Existing same-group lines are considered first; conservative virtual
    materials supply any missing base layer.
    """
    purchase_leaves = _virtual_materials(
        target_profile,
        target_ivs,
        False,
        "",
        target_alpha,
        allow_ditto,
        existing_leaves,
    )
    pool = [state for state in existing_leaves if not state.has_nature] + purchase_leaves
    target_groups = set(_group_key(target_profile.egg_groups))
    profiles: dict[tuple[object, ...], tuple[int, SpeciesProfile]] = {}
    for state in pool:
        if is_ditto(state.species) or not target_groups & set(_group_key(state.egg_groups)):
            continue
        profile = _profile_for_hand_state(state)
        if output_gender not in profile.allowed_genders or not {"F", "M"}.issubset(profile.allowed_genders):
            continue
        key = (profile.species_key, _group_key(profile.egg_groups))
        actual_priority = 0 if state.leaf is not None and not state.is_virtual else 1
        target_penalty = int(profile.species_key == target_profile.species_key)
        priority = actual_priority * 2 + target_penalty
        current = profiles.get(key)
        if current is None or priority < current[0]:
            profiles[key] = (priority, profile)

    ordered_profiles = [
        profile
        for _priority, profile in sorted(
            profiles.values(),
            key=lambda value: (value[0], value[1].species_key, value[1].egg_groups),
        )[:10]
    ]
    goals: list[ChainState] = []
    for mask in dict.fromkeys(int(value) for value in candidate_masks if int(value)):
        for profile in ordered_profiles:
            for goal in _structured_search(
                pool,
                profile,
                mask,
                False,
                output_gender,
                max(12, min(beam, 32)),
                strategy,
                preferred_ditto_ids,
            ):
                # A direct inventory leaf has a known nature already and is
                # not a new gamble. Staged attempts must end in an actual egg.
                if goal.action is None or goal.is_alpha != target_alpha:
                    continue
                goal.force_gender_lock = True
                goals.append(goal)

    def rank(state: ChainState) -> tuple[object, ...]:
        ditto_penalty = int(
            bool(preferred_ditto_ids)
            and not bool(state.used_ids & preferred_ditto_ids)
        )
        target_penalty = int(normalize_text(state.species) == target_profile.species_key)
        base = _state_rank(state, strategy)
        return (ditto_penalty, base[0], base[1], target_penalty, *base[2:])

    unique: list[ChainState] = []
    seen: set[tuple[object, ...]] = set()
    for goal in sorted(goals, key=rank):
        signature = (
            _material_usage_signature(goal.used_ids),
            normalize_text(goal.species),
            goal.gender,
            goal.mask,
            goal.is_alpha,
        )
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(goal)
        if len(unique) >= 12:
            break
    return unique


def _nature_floor_parents(
    leaves: list[ChainState],
    lower_state: ChainState,
    target_ivs: list[int | None],
    target_nature: str,
    floor_count: int,
    allow_ditto: bool,
    target_alpha: bool,
    strategy: str,
    regular_gender: str = "M",
) -> list[ChainState]:
    """Find or create the final low-tier desired-nature parent."""
    lower_bits = [index for index in range(6) if lower_state.mask & (1 << index)]
    floor_count = min(max(1, floor_count), len(lower_bits))
    masks = [sum(1 << stat for stat in shape) for shape in combinations(lower_bits, floor_count)]
    lower_groups = set(_group_key(lower_state.egg_groups))
    candidates: list[ChainState] = []
    for state in leaves:
        if not state.has_nature or state.mask not in masks:
            continue
        if state.effective_material_v != state.mask.bit_count():
            continue
        if target_alpha and not state.is_alpha:
            continue
        if is_ditto(state.species):
            if allow_ditto:
                candidates.append(state)
            continue
        if state.gender == regular_gender and lower_groups & set(_group_key(state.egg_groups)):
            candidates.append(state)

    group = next(iter(lower_state.egg_groups), "兼容")
    sequence = 0
    for mask in masks:
        sequence += 1
        ivs = [target_ivs[index] if mask & (1 << index) else None for index in range(6)]
        monster = Monster(
            id=f"buy:nature-floor:{sequence}:{group}:{regular_gender}:{mask}",
            species=f"{group}组对性{gender_name(regular_gender)}",
            gender=regular_gender,
            nature=target_nature,
            ivs=ivs,
            egg_groups=[group],
            is_alpha=target_alpha,
            account="待采购",
            source="性格手最终保底",
            verified=True,
        )
        candidates.append(
            ChainState(
                species=monster.species,
                gender=regular_gender,
                egg_groups=(group,),
                mask=mask,
                has_nature=True,
                nature=target_nature,
                is_alpha=target_alpha,
                used_ids=frozenset({monster.id}),
                generation=0,
                breeds=0,
                braces=0,
                everstones=0,
                purchases=1,
                material_v=max(2 if target_alpha else 0, mask.bit_count()),
                breeding_species=monster.species,
                is_virtual=True,
                leaf=monster,
            )
        )
        if allow_ditto:
            ditto = Monster(
                id=f"buy:nature-floor:{sequence}:百变怪:N:{mask}",
                species="百变怪",
                gender="N",
                nature=target_nature,
                ivs=ivs,
                is_alpha=target_alpha,
                account="待采购",
                source="性格手最终保底",
                verified=True,
            )
            candidates.append(
                ChainState(
                    species="百变怪",
                    gender="N",
                    egg_groups=(),
                    mask=mask,
                    has_nature=True,
                    nature=target_nature,
                    is_alpha=target_alpha,
                    used_ids=frozenset({ditto.id}),
                    generation=0,
                    breeds=0,
                    braces=0,
                    everstones=0,
                    purchases=1,
                    material_v=max(2 if target_alpha else 0, mask.bit_count()),
                    breeding_species="百变怪",
                    is_virtual=True,
                    leaf=ditto,
                )
            )

    candidates.sort(
        key=lambda state: (
            state.purchases,
            int(is_ditto(state.species)),
            *_state_rank(state, strategy),
        )
    )
    return candidates


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
    target_gender_species: tuple[tuple[str, str], ...] | None = None,
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
    need_hidden_ability: bool = False,
    target_moves: tuple[str, ...] | list[str] | None = None,
    egg_move_donors: dict[str, tuple[str, ...]] | None = None,
    prefer_ditto: bool = False,
    convert_maternal_with_ditto: bool = False,
    preferred_material_ids: frozenset[str] = frozenset(),
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
    requested_need_nature = bool(nature_key)
    nature_strategy_key = "chain" if str(nature_strategy).strip().lower() == "chain" else "late"
    # Leaves keep their real target-nature marker even when the first planning
    # phase intentionally ignores nature and raises the IV mother first.
    need_nature = requested_need_nature
    required_moves = frozenset(str(move).strip() for move in (target_moves or ()) if str(move).strip())
    species_db = get_species_database()
    gender_species = tuple(target_gender_species or ())

    def breeding_output_genders(monster: Monster) -> tuple[str, ...]:
        record = species_db.get(monster.species, fuzzy=True)
        return species_db.breeding_output_genders(record) if record is not None else ()

    def reusable_outside_target_line(monster: Monster) -> bool:
        gender = normalize_gender(monster.gender)
        if is_ditto(monster.species):
            return allow_ditto or convert_maternal_with_ditto
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
        and not monster.gender_unconfirmed
        and (
            monster.is_alpha
            if target_alpha
            else allow_alpha_materials or not monster.is_alpha
        )
        and (allow_ditto or convert_maternal_with_ditto or not is_ditto(monster.species))
    ]
    target_group_keys = set(_group_key(inferred_groups))
    audit_scope = [
        monster for monster in confirmed_inventory
        if (
            normalize_text(monster.species) in family_keys
            or ((allow_ditto or convert_maternal_with_ditto) and is_ditto(monster.species))
            or bool(target_group_keys & set(_group_key(monster.egg_groups)))
        )
    ]
    audit_inventory = [
        monster for monster in audit_scope
        if normalize_text(monster.species) in family_keys
        or ((allow_ditto or convert_maternal_with_ditto) and is_ditto(monster.species))
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
        carries_required_move = bool(required_moves & set(monster.moves))
        monster_key = normalize_text(monster.species)
        is_target_family = monster_key in family_keys
        is_goal_form = monster_key in goal_keys
        if not is_target_family and not is_goal_form and not reusable_outside_target_line(monster):
            continue
        if not (mask or has_nature or carries_required_move or is_target_family or is_goal_form or is_ditto(monster.species)):
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
                # Generic same-group children produced by a planner purchase
                # placeholder do not have a Pokédex species ID. Keep them as a
                # compatible breeding line so staged nature-hand replans can
                # resume after the app is closed or the gender/nature changes.
                if not (
                    monster.egg_groups
                    and (
                        monster.breeding_role == "nature_hand"
                        or monster.source.startswith("孵化方案 ")
                    )
                ):
                    continue
            else:
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
            has_hidden_ability=monster.has_hidden_ability,
            inherited_moves=frozenset(move for move in monster.moves if move in required_moves),
            gender_species=gender_species if is_target_family else (),
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
            state.has_hidden_ability,
            state.inherited_moves,
            is_ditto(state.species),
        )
        if signature_counts[signature] >= per_signature_limit:
            continue
        signature_counts[signature] += 1
        pruned.append(state)
    all_leaf_states = pruned
    preferred_inventory_ditto_ids = (
        frozenset(
            identifier
            for state in all_leaf_states
            if state.leaf is not None and not state.is_virtual and is_ditto(state.species)
            for identifier in state.used_ids
        )
        if prefer_ditto
        else frozenset()
    )

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
        gender_species,
    )

    # Optional one-time maternal bootstrap.  Raw Ditto leaves are removed
    # again when the global Ditto switch is off, so only the explicit
    # target-male + Ditto -> target-female action can consume one.
    actual_target_states = [
        state
        for state in all_leaf_states
        if not state.is_virtual and normalize_text(state.species) == species_key
    ]
    actual_target_females = [state for state in actual_target_states if state.gender == "F"]
    actual_target_males = [state for state in actual_target_states if state.gender == "M"]
    conversion_requested = bool(
        convert_maternal_with_ditto
        and target_profile.allowed_genders == ("F", "M")
        and not actual_target_females
        and actual_target_males
    )
    conversion_states: list[ChainState] = []

    def virtual_conversion_dittos() -> list[ChainState]:
        required_stats = [index for index in range(6) if target_mask & (1 << index)]
        floor = 2 if target_alpha else 1
        width = min(len(required_stats), floor)
        shapes = list(combinations(required_stats, width)) if width else [()]
        result: list[ChainState] = []
        for sequence, shape in enumerate(shapes, 1):
            mask = sum(1 << stat for stat in shape)
            ivs = [target_ivs[index] if mask & (1 << index) else None for index in range(6)]
            monster = Monster(
                id=f"buy:mother-conversion:{sequence}:百变怪:N:{mask}",
                species="百变怪",
                gender="N",
                ivs=ivs,
                is_alpha=target_alpha,
                account="待采购",
                source="仅用于百变怪转换母体",
                verified=True,
            )
            result.append(
                ChainState(
                    species="百变怪",
                    gender="N",
                    egg_groups=(),
                    mask=mask,
                    has_nature=False,
                    nature="",
                    is_alpha=target_alpha,
                    used_ids=frozenset({monster.id}),
                    generation=0,
                    breeds=0,
                    braces=0,
                    everstones=0,
                    purchases=1,
                    material_v=max(floor, mask.bit_count()),
                    breeding_species="百变怪",
                    is_virtual=True,
                    leaf=monster,
                )
            )
        return result

    if conversion_requested:
        ditto_sources = [
            state
            for state in all_leaf_states
            if is_ditto(state.species) and state.is_alpha == target_alpha
        ]
        if not ditto_sources:
            ditto_sources = virtual_conversion_dittos()
        male_sources = sorted(
            actual_target_males,
            key=lambda state: _search_rank(state, strategy, target_mask, False),
        )[:12]
        ditto_sources = sorted(
            ditto_sources,
            key=lambda state: _search_rank(state, strategy, target_mask, False),
        )[:12]
        required_stats = [index for index in range(6) if target_mask & (1 << index)]
        for male in male_sources:
            male_braces = [None, *(stat for stat in required_stats if male.mask & (1 << stat))]
            for ditto in ditto_sources:
                ditto_braces = [None, *(stat for stat in required_stats if ditto.mask & (1 << stat))]
                for brace_male in male_braces:
                    for brace_ditto in ditto_braces:
                        if brace_male is not None and brace_male == brace_ditto:
                            continue
                        child = _forced_child(
                            male,
                            ditto,
                            target_profile,
                            "F",
                            brace_a=brace_male,
                            brace_b=brace_ditto,
                        )
                        if child is None:
                            continue
                        child.force_gender_lock = True
                        child.maternal_conversion = True
                        conversion_states.append(child)
        conversion_states.sort(
            key=lambda state: _search_rank(state, strategy, target_mask, False)
        )
        unique_conversion_states: list[ChainState] = []
        seen_conversion: set[tuple[object, ...]] = set()
        for state in conversion_states:
            signature = (state.used_ids, state.mask, state.has_hidden_ability, state.inherited_moves)
            if signature in seen_conversion:
                continue
            seen_conversion.add(signature)
            unique_conversion_states.append(state)
            if len(unique_conversion_states) >= 64:
                break
        conversion_states = unique_conversion_states
        if conversion_states:
            if not allow_ditto:
                all_leaf_states = [state for state in all_leaf_states if not is_ditto(state.species)]
            all_leaf_states.extend(conversion_states)

    if not allow_ditto:
        # Merely enabling the one-time conversion option must never leak raw
        # Ditto leaves into unrelated donor/nature branches.
        all_leaf_states = [state for state in all_leaf_states if not is_ditto(state.species)]

    conversion_required = bool(conversion_states)

    # If neither sex of the target line exists, buying a target female is the
    # only sensible way to establish species inheritance.  Steps-first may
    # buy it near the top of the IV pyramid; inventory-first keeps the regular
    # low-tier market leaves generated later.
    if (
        target_profile.allowed_genders == ("F", "M")
        and not actual_target_females
        and not actual_target_males
        and strategy == "steps"
        and target_mask
    ):
        required_stats = [index for index in range(6) if target_mask & (1 << index)]
        useful_tier = max(2 if target_alpha else 1, len(required_stats) - 1)
        useful_tier = min(len(required_stats), useful_tier)
        female_material_species = target_profile.breeding_species_for_gender("F")
        for sequence, shape in enumerate(combinations(required_stats, useful_tier), 1):
            mask = sum(1 << stat for stat in shape)
            ivs = [target_ivs[index] if mask & (1 << index) else None for index in range(6)]
            monster = Monster(
                id=f"buy:direct-mother:{sequence}:{planning_species}:F:{mask}",
                species=female_material_species,
                gender="F",
                ivs=ivs,
                egg_groups=list(target_profile.egg_groups),
                is_alpha=target_alpha,
                has_hidden_ability=need_hidden_ability,
                account="待采购",
                source="步骤优先直接采购目标母体",
                verified=True,
            )
            all_leaf_states.append(
                ChainState(
                    species=planning_species,
                    gender="F",
                    egg_groups=target_profile.egg_groups,
                    mask=mask,
                    has_nature=False,
                    nature="",
                    is_alpha=target_alpha,
                    used_ids=frozenset({monster.id}),
                    generation=0,
                    breeds=0,
                    braces=0,
                    everstones=0,
                    purchases=1,
                    material_v=max(2 if target_alpha else 0, mask.bit_count()),
                    breeding_species=female_material_species,
                    is_virtual=True,
                    leaf=monster,
                    has_hidden_ability=need_hidden_ability,
                    gender_species=target_profile.gender_species,
                )
            )

    available_preferred_material_ids = frozenset(
        preferred_material_ids
        & frozenset(identifier for state in all_leaf_states for identifier in state.used_ids)
    )

    nature_target_key = _nature_target_signature(
        species_key,
        nature_key,
        target_ivs,
        target_alpha,
        need_hidden_ability,
        required_moves,
    )

    # Late nature planning is a persisted state machine:
    #   maternal -> gamble N-1 male -> gamble N-2 female -> guaranteed floor.
    # Incidental low-tier natures on the maternal pyramid remain ignored;
    # lower tiers are checked only after the full-IV mother has missed and the
    # user is deliberately manufacturing a nature hand.
    exact_target_count = target_mask.bit_count()
    nature_checkpoint = max(1, exact_target_count - 1)
    full_body_states = [
        state
        for state in all_leaf_states
        if (
        normalize_text(state.species) == species_key
        and state.mask & target_mask == target_mask
        and state.is_alpha == target_alpha
        and (not need_hidden_ability or state.has_hidden_ability)
        and required_moves.issubset(state.inherited_moves)
        )
    ]
    female_full_bodies = [state for state in full_body_states if state.gender == "F"]
    checkpoint_nature_states = [
        state
        for state in all_leaf_states
        if state.has_nature and state.mask.bit_count() >= nature_checkpoint
    ]

    upper_level = max(1, exact_target_count - 1)
    lower_level = max(1, exact_target_count - 2)

    def attempt_states(level: int, result: str, gender: str) -> list[ChainState]:
        return [
            state
            for state in all_leaf_states
            if state.leaf is not None
            and state.leaf.breeding_target_key == nature_target_key
            and state.leaf.breeding_role == "nature_hand"
            and state.leaf.nature_attempt_level == level
            and state.leaf.nature_attempt_result == result
            and state.gender == gender
            and state.mask.bit_count() == level
            and state.is_alpha == target_alpha
        ]

    failed_upper_states = attempt_states(upper_level, "miss", "M")
    failed_lower_states = attempt_states(lower_level, "miss", "F")
    hit_lower_states = attempt_states(lower_level, "hit", "F")
    available_upper_plain_states = list(failed_upper_states)
    available_upper_plain_states.extend(
        state
        for state in all_leaf_states
        if state.gender == "M"
        and not state.has_nature
        and state.mask.bit_count() == upper_level
        and state.effective_material_v == upper_level
        and state.is_alpha == target_alpha
        and state not in available_upper_plain_states
    )
    available_lower_nature_states = list(hit_lower_states)
    available_lower_nature_states.extend(
        state
        for state in all_leaf_states
        if state.gender == "F"
        and state.has_nature
        and state.mask.bit_count() == lower_level
        and state.effective_material_v == lower_level
        and state.is_alpha == target_alpha
        and state not in available_lower_nature_states
    )
    available_lower_plain_states = list(failed_lower_states)
    available_lower_plain_states.extend(
        state
        for state in all_leaf_states
        if state.gender == "F"
        and not state.has_nature
        and state.mask.bit_count() == lower_level
        and state.effective_material_v == lower_level
        and state.is_alpha == target_alpha
        and state not in available_lower_plain_states
    )
    nature_floor_level = max(2 if target_alpha else 1, exact_target_count - 3)
    upper_can_be_gambled = upper_level > nature_floor_level
    lower_can_be_gambled = lower_level > nature_floor_level
    nature_phase = ""
    nature_attempt_level = 0
    custom_goals: list[ChainState] | None = None
    staged_supported = (
        requested_need_nature
        and nature_strategy_key == "late"
        and "F" in allowed_genders
        and exact_target_count >= 3
    )

    if requested_need_nature and nature_strategy_key == "late":
        if checkpoint_nature_states:
            nature_phase = "finish"
            need_nature = True
        elif staged_supported and female_full_bodies:
            if available_upper_plain_states and available_lower_nature_states:
                nature_phase = "promote"
                need_nature = True
            elif available_upper_plain_states:
                if lower_can_be_gambled and not available_lower_plain_states:
                    nature_phase = "gamble_lower"
                    nature_attempt_level = lower_level
                    need_nature = False
                else:
                    # Either the lower random hand has already missed, or the
                    # alpha/material floor has been reached. Only now may the
                    # planner buy the lowest useful desired-nature material.
                    nature_phase = "guarantee"
                    need_nature = True
            elif upper_can_be_gambled:
                nature_phase = "gamble_upper"
                nature_attempt_level = upper_level
                need_nature = False
            else:
                # Example: a 3V alpha target. Its N-1 tier is already the 2V
                # alpha floor, so manufacturing a random 2V egg is impossible
                # and wasteful; go straight to the 2V nature guarantee.
                nature_phase = "guarantee"
                need_nature = True
        elif full_body_states:
            # Male-only/genderless and very low-IV targets keep the previous
            # strict finish because they do not have a normal female spine.
            nature_phase = "finish"
            need_nature = True
        else:
            nature_phase = "maternal"
            need_nature = False
    else:
        nature_phase = "strict" if requested_need_nature else ""
        need_nature = requested_need_nature

    # During the IV-first phase the 5V/4V body is still breeding stock rather
    # than the final product. Keep it female so it can accept the later nature
    # hand; an explicit final-gender request is enforced by the next replan.
    search_target_gender = target_gender
    if nature_phase == "maternal" and "F" in allowed_genders:
        search_target_gender = "F"
    elif nature_phase == "gamble_upper":
        search_target_gender = "M"
    elif nature_phase == "gamble_lower":
        search_target_gender = "F"

    required_stats = [index for index in range(6) if target_mask & (1 << index)]

    if nature_phase == "gamble_upper":
        upper_masks = [
            sum(1 << stat for stat in shape)
            for shape in combinations(required_stats, upper_level)
        ]
        custom_goals = _plain_nature_hand_goals(
            all_leaf_states,
            target_profile,
            target_ivs,
            upper_masks,
            "M",
            target_alpha,
            allow_ditto,
            strategy,
            beam_per_signature,
            preferred_inventory_ditto_ids,
        )
    elif nature_phase == "gamble_lower":
        lower_masks = [
            sum(1 << stat for stat in shape)
            for upper in available_upper_plain_states
            for shape in combinations(
                [index for index in range(6) if upper.mask & (1 << index)],
                lower_level,
            )
        ]
        custom_goals = _plain_nature_hand_goals(
            all_leaf_states,
            target_profile,
            target_ivs,
            lower_masks,
            "F",
            target_alpha,
            allow_ditto,
            strategy,
            beam_per_signature,
            preferred_inventory_ditto_ids,
        )

    desired_final_genders = (
        (target_gender,)
        if target_gender in target_profile.allowed_genders
        else tuple(gender for gender in target_profile.allowed_genders if gender in {"F", "M"})
    ) or ("F",)

    def finish_from_lower_nature(
        lower_nature: ChainState,
        upper_plain: ChainState,
        body: ChainState,
    ) -> list[ChainState]:
        if lower_nature.gender != "F" or upper_plain.gender != "M" or body.gender != "F":
            return []
        if not set(_group_key(lower_nature.egg_groups)) & set(_group_key(upper_plain.egg_groups)):
            return []
        if lower_nature.mask & ~upper_plain.mask:
            return []
        missing_upper = [
            index
            for index in range(6)
            if upper_plain.mask & (1 << index) and not lower_nature.mask & (1 << index)
        ]
        if len(missing_upper) != 1:
            return []
        lower_profile = _profile_for_hand_state(lower_nature)
        if "M" not in lower_profile.allowed_genders:
            return []
        nature_upper = _forced_child(
            lower_nature,
            upper_plain,
            lower_profile,
            "M",
            brace_b=missing_upper[0],
            everstone_a=True,
        )
        if nature_upper is None:
            return []
        nature_upper.force_gender_lock = True
        return finish_from_nature_upper(nature_upper, body)

    def finish_from_nature_upper(
        nature_upper: ChainState,
        body: ChainState,
    ) -> list[ChainState]:
        if nature_upper.gender != "M" or body.gender != "F":
            return []
        if not set(_group_key(body.egg_groups)) & set(_group_key(nature_upper.egg_groups)):
            return []
        missing_final = [
            index
            for index in range(6)
            if target_mask & (1 << index) and not nature_upper.mask & (1 << index)
        ]
        if len(missing_final) != 1:
            return []
        roots: list[ChainState] = []
        for output_gender in desired_final_genders:
            root = _forced_child(
                body,
                nature_upper,
                target_profile,
                output_gender,
                brace_a=missing_final[0],
                everstone_b=True,
            )
            if root is not None:
                roots.append(root)
        return roots

    if nature_phase == "promote":
        custom_goals = []
        for lower_nature in available_lower_nature_states:
            for upper_plain in available_upper_plain_states:
                for body in female_full_bodies:
                    custom_goals.extend(finish_from_lower_nature(lower_nature, upper_plain, body))
    elif nature_phase == "guarantee":
        custom_goals = []
        if available_upper_plain_states and lower_can_be_gambled and available_lower_plain_states:
            # Normal staged finish: N-2 female already missed, so buy only the
            # N-3 desired-nature male/Ditto, promote it twice, then finish.
            for lower_plain in available_lower_plain_states:
                lower_profile = _profile_for_hand_state(lower_plain)
                for nature_parent in _nature_floor_parents(
                    all_leaf_states,
                    lower_plain,
                    target_ivs,
                    nature_label.strip() or nature_key,
                    nature_floor_level,
                    allow_ditto,
                    target_alpha,
                    strategy,
                ):
                    if nature_parent.mask & ~lower_plain.mask:
                        continue
                    missing_lower = [
                        index
                        for index in range(6)
                        if lower_plain.mask & (1 << index) and not nature_parent.mask & (1 << index)
                    ]
                    if len(missing_lower) != 1:
                        continue
                    nature_lower = _forced_child(
                        lower_plain,
                        nature_parent,
                        lower_profile,
                        "F",
                        brace_a=missing_lower[0],
                        everstone_b=True,
                    )
                    if nature_lower is None:
                        continue
                    nature_lower.force_gender_lock = True
                    for upper_plain in available_upper_plain_states:
                        for body in female_full_bodies:
                            custom_goals.extend(finish_from_lower_nature(nature_lower, upper_plain, body))
        elif available_upper_plain_states:
            # The next lower tier is already the minimum useful tier (notably
            # 4V alpha -> 3V male -> 2V floor). Buy a desired-nature female or
            # Ditto at that floor and promote directly to the saved upper hand.
            for upper_plain in available_upper_plain_states:
                upper_profile = _profile_for_hand_state(upper_plain)
                for nature_parent in _nature_floor_parents(
                    all_leaf_states,
                    upper_plain,
                    target_ivs,
                    nature_label.strip() or nature_key,
                    nature_floor_level,
                    allow_ditto,
                    target_alpha,
                    strategy,
                    regular_gender="F",
                ):
                    if nature_parent.mask & ~upper_plain.mask:
                        continue
                    missing_upper = [
                        index
                        for index in range(6)
                        if upper_plain.mask & (1 << index) and not nature_parent.mask & (1 << index)
                    ]
                    if len(missing_upper) != 1:
                        continue
                    if is_ditto(nature_parent.species):
                        nature_upper = _forced_child(
                            upper_plain,
                            nature_parent,
                            upper_profile,
                            "M",
                            brace_a=missing_upper[0],
                            everstone_b=True,
                        )
                    else:
                        nature_profile = _profile_for_hand_state(nature_parent)
                        if (
                            nature_parent.gender != "F"
                            or "M" not in nature_profile.allowed_genders
                            or not set(_group_key(nature_parent.egg_groups))
                            & set(_group_key(upper_plain.egg_groups))
                        ):
                            continue
                        nature_upper = _forced_child(
                            nature_parent,
                            upper_plain,
                            nature_profile,
                            "M",
                            brace_b=missing_upper[0],
                            everstone_a=True,
                        )
                    if nature_upper is None:
                        continue
                    nature_upper.force_gender_lock = True
                    for body in female_full_bodies:
                        custom_goals.extend(finish_from_nature_upper(nature_upper, body))
        else:
            # N-1 itself is the floor (for example a 3V alpha target). There
            # is no meaningful random-hand tier left: buy that one final
            # desired-nature male/Ditto and combine it with the finished body.
            for body in female_full_bodies:
                for nature_parent in _nature_floor_parents(
                    all_leaf_states,
                    body,
                    target_ivs,
                    nature_label.strip() or nature_key,
                    nature_floor_level,
                    allow_ditto,
                    target_alpha,
                    strategy,
                ):
                    if nature_parent.mask & ~target_mask:
                        continue
                    missing_final = [
                        index
                        for index in range(6)
                        if target_mask & (1 << index) and not nature_parent.mask & (1 << index)
                    ]
                    if len(missing_final) != 1:
                        continue
                    if not is_ditto(nature_parent.species) and (
                        nature_parent.gender != "M"
                        or not set(_group_key(body.egg_groups)) & set(_group_key(nature_parent.egg_groups))
                    ):
                        continue
                    for output_gender in desired_final_genders:
                        root = _forced_child(
                            body,
                            nature_parent,
                            target_profile,
                            output_gender,
                            brace_a=missing_final[0],
                            everstone_b=True,
                        )
                        if root is not None:
                            custom_goals.append(root)

    existing_goals = [
        state for state in all_leaf_states
        if (state.leaf is not None or state.action is not None)
        and (
            normalize_text(state.leaf.species) in goal_keys
            if state.leaf is not None
            else normalize_text(state.species) == species_key
        )
        and state.mask & target_mask == target_mask
        and (not need_nature or state.has_nature)
        and state.is_alpha == target_alpha
        and (not search_target_gender or state.gender == search_target_gender)
        and (not need_hidden_ability or state.has_hidden_ability)
        and required_moves.issubset(state.inherited_moves)
    ]

    def feature_goals(states: list[ChainState]) -> list[ChainState]:
        return [
            state for state in states
            if (not need_hidden_ability or state.has_hidden_ability)
            and required_moves.issubset(state.inherited_moves)
        ]
    if custom_goals is not None:
        goals = custom_goals
    elif existing_goals:
        goals = existing_goals
    elif target_mask.bit_count() == 6:
        goals = _canonical_six_iv_pyramid(
            all_leaf_states,
            target_profile,
            target_mask,
            need_nature,
            search_target_gender,
            target_alpha,
            max_results,
            strategy,
        )
        goals = feature_goals(goals)
        if not goals:
            purchase_leaves = _virtual_materials(
                target_profile,
                target_ivs,
                need_nature,
                nature_label.strip() or nature_key,
                target_alpha,
                allow_ditto,
                all_leaf_states,
                need_hidden_ability,
                required_moves,
                egg_move_donors,
            )
            goals = _canonical_six_iv_pyramid(
                all_leaf_states + purchase_leaves,
                target_profile,
                target_mask,
                need_nature,
                search_target_gender,
                target_alpha,
                max_results,
                strategy,
            )
            goals = feature_goals(goals)
    else:
        goals = (
            _genderless_line_pyramid(
                all_leaf_states,
                target_profile,
                target_mask,
                need_nature,
                max_results,
                strategy,
            )
            if target_profile.genderless
            else _same_species_pyramid(
                all_leaf_states,
                target_profile,
                target_mask,
                need_nature,
                search_target_gender,
                max_results,
                strategy,
            )
        )
        goals = feature_goals([goal for goal in goals if goal.is_alpha == target_alpha])
        if not goals:
            goals = _structured_search(
                all_leaf_states,
                target_profile,
                target_mask,
                need_nature,
                search_target_gender,
                beam_per_signature,
                strategy,
                preferred_inventory_ditto_ids,
            )
            goals = feature_goals([goal for goal in goals if goal.is_alpha == target_alpha])

        if not goals:
            purchase_leaves = _virtual_materials(
                target_profile,
                target_ivs,
                need_nature,
                nature_label.strip() or nature_key,
                target_alpha,
                allow_ditto,
                all_leaf_states,
                need_hidden_ability,
                required_moves,
                egg_move_donors,
            )
            leaves_with_purchases = all_leaf_states + purchase_leaves
            goals = _direct_market_complements(
                all_leaf_states,
                purchase_leaves,
                target_profile,
                target_mask,
                search_target_gender,
                target_alpha,
                strategy,
                max_results,
            ) if need_nature else []
            goals = feature_goals(goals)
            if not goals:
                goals = (
                    _genderless_line_pyramid(
                        leaves_with_purchases,
                        target_profile,
                        target_mask,
                        need_nature,
                        max_results,
                        strategy,
                    )
                    if target_profile.genderless
                    else _maternal_spine_pyramid(
                        leaves_with_purchases,
                        target_profile,
                        target_mask,
                        need_nature,
                        search_target_gender,
                        max_results,
                        strategy,
                        preferred_inventory_ditto_ids,
                        need_hidden_ability,
                    )
                )
                goals = feature_goals([goal for goal in goals if goal.is_alpha == target_alpha])
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
                needs_structured_fallback = not goals or (
                    bool(preferred_inventory_ditto_ids)
                    and not any(
                        goal.used_ids & preferred_inventory_ditto_ids
                        for goal in goals
                    )
                )
                if needs_structured_fallback and (
                    has_compatible_actual
                    or has_compatible_market_parent
                    or target_profile.allowed_genders != ("F", "M")
                ):
                    goals.extend(_structured_search(
                        leaves_with_purchases,
                        target_profile,
                        target_mask,
                        need_nature,
                        search_target_gender,
                        beam_per_signature,
                        strategy,
                        preferred_inventory_ditto_ids,
                    ))
                    goals = feature_goals([goal for goal in goals if goal.is_alpha == target_alpha])

    if allow_ditto:
        goals.extend(_direct_ditto_complements(
            all_leaf_states,
            target_profile,
            target_mask,
            need_nature,
            search_target_gender,
            target_alpha,
            required_moves,
            need_hidden_ability,
        ))
    goals = feature_goals([goal for goal in goals if goal.is_alpha == target_alpha])
    def final_goal_rank(state: ChainState) -> tuple[object, ...]:
        base = _state_rank(state, strategy)
        # The checkbox is an explicit request to consume an existing Ditto.
        # First choose among routes that actually use one, then optimize
        # purchases/breeds normally inside that constrained set.
        ditto_penalty = int(
            bool(preferred_inventory_ditto_ids)
            and not bool(state.used_ids & preferred_inventory_ditto_ids)
        )
        conversion_penalty = int(conversion_required and not state.maternal_conversion)
        preferred_material_penalty = int(
            bool(available_preferred_material_ids)
            and not bool(state.used_ids & available_preferred_material_ids)
        )
        return (conversion_penalty, preferred_material_penalty, ditto_penalty, *base)

    goals.sort(key=final_goal_rank)
    if goals:
        if _normalize_strategy(strategy) == "steps":
            best_quality = (
                int(conversion_required and not goals[0].maternal_conversion),
                int(bool(available_preferred_material_ids) and not bool(goals[0].used_ids & available_preferred_material_ids)),
                int(bool(preferred_inventory_ditto_ids) and not bool(goals[0].used_ids & preferred_inventory_ditto_ids)),
                goals[0].breeds,
                goals[0].purchases,
            )
            goals = [
                goal for goal in goals
                if (
                    int(conversion_required and not goal.maternal_conversion),
                    int(bool(available_preferred_material_ids) and not bool(goal.used_ids & available_preferred_material_ids)),
                    int(bool(preferred_inventory_ditto_ids) and not bool(goal.used_ids & preferred_inventory_ditto_ids)),
                    goal.breeds,
                    goal.purchases,
                ) == best_quality
            ]
        else:
            best_quality = (
                int(conversion_required and not goals[0].maternal_conversion),
                int(bool(available_preferred_material_ids) and not bool(goals[0].used_ids & available_preferred_material_ids)),
                int(bool(preferred_inventory_ditto_ids) and not bool(goals[0].used_ids & preferred_inventory_ditto_ids)),
                goals[0].purchases,
                goals[0].breeds,
            )
            goals = [
                goal for goal in goals
                if (
                    int(conversion_required and not goal.maternal_conversion),
                    int(bool(available_preferred_material_ids) and not bool(goal.used_ids & available_preferred_material_ids)),
                    int(bool(preferred_inventory_ditto_ids) and not bool(goal.used_ids & preferred_inventory_ditto_ids)),
                    goal.purchases,
                    goal.breeds,
                ) == best_quality
            ]
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
            goal.has_hidden_ability,
            goal.inherited_moves,
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
        (nature_label.strip() or nature_key) if need_nature else "",
        target_ivs,
        inferred_groups,
        target_alpha,
        allow_ditto,
        allow_alpha_materials,
        need_hidden_ability,
        required_moves,
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
            working_gender=search_target_gender,
            target_alpha=target_alpha,
            target_species=requested_species,
            offspring_species=planning_species,
            breeding_species=breeding_species.strip() or planning_species,
            nature_strategy=nature_strategy_key,
            gender_strategy=normalize_intermediate_gender_strategy(intermediate_gender_strategy),
            inventory_pool_size=len(audit_inventory),
            inventory_iv_histogram=tuple(audit_histogram),
            inventory_nature_count=audit_nature_count,
            inventory_target_female_count=audit_target_female_count,
            inventory_compatible_male_count=audit_compatible_male_count,
            inventory_other_female_count=audit_other_female_count,
            inventory_excluded_female_only_count=audit_excluded_female_only_count,
            target_hidden_ability=need_hidden_ability,
            target_moves=tuple(sorted(required_moves)),
            nature_phase=nature_phase,
            nature_attempt_level=nature_attempt_level,
            nature_target_key=nature_target_key,
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
    need_hidden_ability: bool = False,
    target_moves: frozenset[str] = frozenset(),
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
    if need_hidden_ability and not any(state.has_hidden_ability for state in leaves):
        missing.append(f"同进化线且梦特已解锁的 {species} 素材（可从头目或交易行取得）")
    for move in sorted(target_moves):
        if not any(move in state.inherited_moves for state in leaves):
            missing.append(f"携带遗传技能“{move}”的同进化线素材；可先按遗传链制作后录入库存")
    if inventory and not any(normalize_gender(monster.gender) in {"M", "F", "N"} for monster in inventory):
        missing.append("素材性别信息")
    return missing
