from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from chain_planner import ChainCandidate, ChainState, child_gender_policy, gender_name, normalize_text
from models import Monster


@dataclass
class ExecutionStep:
    number: int
    parent_a_id: str
    parent_b_id: str
    parent_a_label: str
    parent_b_label: str
    child: Monster
    item_a: str = ""
    item_b: str = ""
    completed: bool = False
    planned_gender: str = ""
    gender_policy: str = "locked"
    gender_override: str = ""
    in_progress: bool = False
    # "maternal" follows the N-1 threshold; "nature_hand" is an
    # intentional lower-tier gamble; "ignore" never prompts for nature.
    nature_check_role: str = ""

    @property
    def requires_purchase(self) -> bool:
        return self.parent_a_id.startswith("buy:") or self.parent_b_id.startswith("buy:")

    @property
    def uses_everstone(self) -> bool:
        return "不变之石" in {self.item_a, self.item_b}

    @property
    def effective_gender_policy(self) -> str:
        if self.gender_override == "random":
            return "random"
        if self.gender_override in {"F", "M"}:
            return "locked"
        return self.gender_policy

    @property
    def expected_gender(self) -> str:
        if self.gender_override in {"F", "M"}:
            return self.gender_override
        return self.planned_gender or self.child.gender

    @property
    def gender_instruction(self) -> str:
        policy = self.effective_gender_policy
        if policy == "irrelevant":
            return "本路线无需确认性别；下一步与百变怪孵化"
        if policy == "random":
            return "不锁性别；孵出后记录实际性别并重算"
        if policy == "fixed":
            return f"固定{gender_name(self.expected_gender)}"
        return f"锁定{gender_name(self.expected_gender)}"

    @property
    def outcome_changes_plan(self) -> bool:
        return self.effective_gender_policy == "random" or (
            self.gender_override in {"F", "M"}
            and self.gender_override != self.planned_gender
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["child"] = self.child.to_dict()
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExecutionStep":
        return cls(
            number=int(value["number"]),
            parent_a_id=str(value["parent_a_id"]),
            parent_b_id=str(value["parent_b_id"]),
            parent_a_label=str(value.get("parent_a_label", "")),
            parent_b_label=str(value.get("parent_b_label", "")),
            child=Monster.from_dict(value["child"]),
            item_a=str(value.get("item_a", "")),
            item_b=str(value.get("item_b", "")),
            completed=bool(value.get("completed", False)),
            planned_gender=str(value.get("planned_gender", value.get("child", {}).get("gender", ""))),
            gender_policy=str(value.get("gender_policy", "locked")),
            gender_override=str(value.get("gender_override", "")),
            in_progress=bool(value.get("in_progress", False)),
            nature_check_role=str(value.get("nature_check_role", "")),
        )


@dataclass
class ExecutionPlan:
    id: str
    target_species: str
    steps: list[ExecutionStep] = field(default_factory=list)
    purchase_requirements: list[str] = field(default_factory=list)
    target_nature: str = ""
    adaptive_nature: bool = False
    target_iv_count: int = 0
    target_gender: str = ""
    gender_strategy: str = "lock_all"
    nature_phase: str = ""
    nature_target_key: str = ""
    nature_attempt_level: int = 0

    @property
    def required_iv_count(self) -> int:
        if self.target_iv_count > 0:
            return self.target_iv_count
        return max(
            (sum(value is not None for value in step.child.ivs) for step in self.steps),
            default=0,
        )

    @property
    def nature_check_min_ivs(self) -> int:
        count = self.required_iv_count
        return max(1, count - 1) if count else 0

    def should_check_nature(self, step: ExecutionStep) -> bool:
        """Apply phase-aware nature prompts.

        Maternal nodes use the normal N-1 threshold. A staged nature-hand
        node explicitly overrides that threshold because its sole purpose is
        to gamble a lower-tier nature after the finished mother already lost.
        """
        if step.nature_check_role == "ignore":
            return False
        if step.nature_check_role == "nature_hand":
            return bool(self.adaptive_nature and self.target_nature and not step.uses_everstone)
        if step.nature_check_role == "maternal":
            return bool(
                self.adaptive_nature
                and self.target_nature
                and not step.uses_everstone
                and self.nature_check_min_ivs
                and sum(value is not None for value in step.child.ivs) >= self.nature_check_min_ivs
            )
        # Legacy plans saved before per-node roles retain the old behavior.
        return bool(
            self.adaptive_nature
            and self.target_nature
            and not step.uses_everstone
            and self.nature_check_min_ivs
            and sum(value is not None for value in step.child.ivs) >= self.nature_check_min_ivs
        )

    def _producer_by_child_id(self) -> dict[str, ExecutionStep]:
        return {step.child.id: step for step in self.steps}

    def dependencies_completed(self, step: ExecutionStep) -> bool:
        producers = self._producer_by_child_id()
        return all(
            parent_id not in producers or producers[parent_id].completed
            for parent_id in (step.parent_a_id, step.parent_b_id)
        )

    def is_step_ready(self, step: ExecutionStep) -> bool:
        return bool(
            step in self.steps
            and not step.completed
            and self.dependencies_completed(step)
        )

    def is_final_step(self, step: ExecutionStep) -> bool:
        """Whether this child is the root result and feeds no later step."""
        return bool(
            step in self.steps
            and not any(
                step.child.id in (other.parent_a_id, other.parent_b_id)
                for other in self.steps
                if other is not step
            )
        )

    @property
    def frontier_steps(self) -> list[ExecutionStep]:
        """Incomplete nodes whose direct child dependencies are complete."""
        return [
            step
            for step in self.steps
            if not step.completed and self.dependencies_completed(step)
        ]

    @property
    def ready_steps(self) -> list[ExecutionStep]:
        """All sibling branches that can be executed now, in display order."""
        return list(self.frontier_steps)

    @property
    def next_actionable_step(self) -> ExecutionStep | None:
        return next(iter(self.ready_steps), None)

    @property
    def next_step(self) -> ExecutionStep | None:
        return next(iter(self.frontier_steps), None) or next(
            (step for step in self.steps if not step.completed),
            None,
        )

    @property
    def completed(self) -> bool:
        return bool(self.steps) and self.next_step is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 7,
            "id": self.id,
            "target_species": self.target_species,
            "steps": [step.to_dict() for step in self.steps],
            "purchase_requirements": list(self.purchase_requirements),
            "target_nature": self.target_nature,
            "adaptive_nature": self.adaptive_nature,
            "target_iv_count": self.target_iv_count,
            "target_gender": self.target_gender,
            "gender_strategy": self.gender_strategy,
            "nature_phase": self.nature_phase,
            "nature_target_key": self.nature_target_key,
            "nature_attempt_level": self.nature_attempt_level,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExecutionPlan":
        return cls(
            id=str(value["id"]),
            target_species=str(value.get("target_species", "")),
            steps=[ExecutionStep.from_dict(item) for item in value.get("steps", []) if isinstance(item, dict)],
            purchase_requirements=[str(item) for item in value.get("purchase_requirements", [])],
            target_nature=str(value.get("target_nature", "")),
            adaptive_nature=bool(value.get("adaptive_nature", False)),
            target_iv_count=int(value.get("target_iv_count", 0) or 0),
            target_gender=str(value.get("target_gender", "")),
            gender_strategy=str(value.get("gender_strategy", "lock_all")),
            nature_phase=str(value.get("nature_phase", "")),
            nature_target_key=str(value.get("nature_target_key", "")),
            nature_attempt_level=int(value.get("nature_attempt_level", 0) or 0),
        )

    def status_text(self) -> str:
        step = self.next_step
        if step is None:
            return "方案已经全部执行完成。"
        ready = self.ready_steps
        if len(ready) > 1:
            numbers = "、".join(str(value.number) for value in ready)
            purchase_steps = [value for value in ready if value.requires_purchase]
            progressing = [value for value in ready if value.in_progress]
            progress_note = (
                f"\n已标记孵化中：步骤 {'、'.join(str(value.number) for value in progressing)}；"
                "该标记只作备忘，不会核销素材或解锁上层。"
                if progressing
                else ""
            )
            random_note = (
                "\n其中包含不锁性别节点；完成时记录实际性别并重算剩余路线。"
                if any(value.effective_gender_policy == "random" for value in ready)
                else ""
            )
            purchase_note = (
                f"\n步骤 {'、'.join(str(value.number) for value in purchase_steps)} 含交易行素材；"
                "购买后可直接确认完成，无需 OCR 扫描入库。"
                if purchase_steps
                else ""
            )
            return (
                f"当前有 {len(ready)} 个可并行执行节点：步骤 {numbers}。\n"
                "它们互不依赖，可按任意顺序完成；直接勾选思维导图中的对应节点即可核销。"
                f"{progress_note}"
                f"{random_note}"
                f"{purchase_note}"
            )
        items = "、".join(item for item in (step.item_a, step.item_b) if item) or "无锁定道具"
        note = f"\n注意：{step.child.notes}" if step.child.notes else ""
        nature_note = ""
        if self.should_check_nature(step):
            if step.nature_check_role == "nature_hand":
                nature_note = (
                    f"\n主动赌性格手：本步必须记录是否爆出 {self.target_nature}；"
                    "未命中才会进入下一档或最终保底。"
                )
            else:
                nature_note = f"\n性格机会：本步未锁性格；孵出后请记录是否爆出 {self.target_nature}。"
        progress_note = (
            "\n当前已标记为“孵化中”；这只是备忘，不会提前核销素材。"
            if step.in_progress
            else ""
        )
        purchase_note = (
            "\n交易行素材：请先按规划购买；无需扫描入库，确认本步完成时会直接视为已使用。"
            if step.requires_purchase
            else ""
        )
        return (
            f"下一步 {step.number}/{len(self.steps)}：\n"
            f"父母 A：{step.parent_a_label}\n"
            f"父母 B：{step.parent_b_label}\n"
            f"道具：{items}\n"
            f"子代性别：{step.gender_instruction}\n"
            f"完成后得到：{'头目' if step.child.is_alpha else '普通'} "
            f"{step.child.species} {step.child.iv_string}{purchase_note}{progress_note}{nature_note}{note}"
        )


def _leaf_label(state: ChainState) -> str:
    if state.leaf is None:
        return "未知素材"
    monster = state.leaf
    account = monster.account or "账号未记录"
    suffix = f"（{account} {monster.position_label}）" if monster.position_label else f"（{account} · 未定位）"
    prefix = "需补充" if state.is_virtual else "库存"
    return (
        f"{prefix} {'头目' if monster.is_alpha else '普通'} {monster.species} "
        f"{monster.gender or '性别未知'} {monster.iv_string}{suffix}"
    )


def build_execution_plan(candidate: ChainCandidate) -> ExecutionPlan:
    plan_id = str(uuid.uuid4())
    steps: list[ExecutionStep] = []
    purchase_requirements: list[str] = []
    refs: dict[int, tuple[str, str]] = {}
    account_by_id: dict[str, str] = {}

    def emit(state: ChainState, sibling: ChainState | None = None) -> tuple[str, str]:
        cached = refs.get(id(state))
        if cached is not None:
            return cached
        if state.action is None:
            if state.leaf is None:
                raise ValueError("孵化树叶节点缺少素材记录。")
            label = _leaf_label(state)
            if state.is_virtual:
                purchase_requirements.append(label)
            result = (state.leaf.id, label)
            account_by_id[state.leaf.id] = state.leaf.account
            refs[id(state)] = result
            return result

        parent_specs = [
            (state.action.parent_a, state.action.item_a),
            (state.action.parent_b, state.action.item_b),
        ]
        parent_specs.sort(
            key=lambda pair: (
                pair[0].purchases > 0,
                pair[0].purchases,
                -pair[0].inventory_breeds,
                pair[0].breeds,
            )
        )
        (parent_a_state, item_a), (parent_b_state, item_b) = parent_specs
        parent_a_id, parent_a_label = emit(parent_a_state, parent_b_state)
        parent_b_id, parent_b_label = emit(parent_b_state, parent_a_state)
        number = len(steps) + 1
        child_id = f"plan-{plan_id}-step-{number}"
        parent_accounts = {
            account_by_id[parent_id]
            for parent_id in (parent_a_id, parent_b_id)
            if parent_id in account_by_id
            and not parent_id.startswith("buy:")
            and account_by_id[parent_id] not in {"", "待采购", "待确认"}
        }
        child_account = next(iter(parent_accounts)) if len(parent_accounts) == 1 else "待确认"
        child_ivs = [
            candidate.target_ivs[index] if state.mask & (1 << index) else None
            for index in range(6)
        ]
        state_iv_count = sum(value is not None for value in child_ivs)
        nature_check_role = "ignore"
        if candidate.target_nature and candidate.nature_strategy == "late":
            if (
                candidate.nature_phase == "maternal"
                and normalize_text(state.species) == normalize_text(candidate.offspring_species)
                and state.gender == "F"
                and state_iv_count >= max(1, sum(value is not None for value in candidate.target_ivs) - 1)
                and "不变之石" not in {item_a, item_b}
            ):
                nature_check_role = "maternal"
            elif (
                candidate.nature_phase in {"gamble_upper", "gamble_lower"}
                and state is candidate.root
                and "不变之石" not in {item_a, item_b}
            ):
                nature_check_role = "nature_hand"
        notes = [f"由方案步骤 {number} 生成"]
        if state.action is not None and any(
            normalize_text(parent.species) in {"百变怪", "ditto"}
            for parent in (state.action.parent_a, state.action.parent_b)
        ) and state.maternal_conversion:
            notes.append("使用百变怪将目标公体转换为母体主线")
        is_final_step = state is candidate.root
        output_species = state.output_species
        if nature_check_role == "nature_hand":
            notes.append(
                f"主动赌性格手：{state_iv_count} 项精确，孵出后确认是否为 {candidate.target_nature}"
            )
        elif is_final_step and candidate.target_species and candidate.target_species != output_species:
            notes.append(f"孵化后需进化为最终目标 {candidate.target_species}")
        elif not is_final_step:
            next_breeding_species = state.breeding_species or candidate.breeding_species
            if next_breeding_species and next_breeding_species != output_species:
                notes.append(f"再次参与孵化前需进化为 {next_breeding_species}")
        child = Monster(
            id=child_id,
            species=output_species,
            gender=state.gender,
            nature=state.nature if state.has_nature else "",
            ivs=child_ivs,
            egg_groups=list(state.egg_groups),
            is_alpha=state.is_alpha,
            has_hidden_ability=state.has_hidden_ability,
            moves=sorted(state.inherited_moves),
            account=child_account,
            source=f"孵化方案 {plan_id} 步骤 {number}",
            verified=True,
            notes="；".join(notes),
            breeding_target_key=candidate.nature_target_key if nature_check_role != "ignore" else "",
            breeding_role="nature_hand" if nature_check_role == "nature_hand" else (
                "maternal" if nature_check_role == "maternal" else ""
            ),
            nature_attempt_level=state_iv_count if nature_check_role != "ignore" else 0,
        )
        step = ExecutionStep(
            number=number,
            parent_a_id=parent_a_id,
            parent_b_id=parent_b_id,
            parent_a_label=parent_a_label,
            parent_b_label=parent_b_label,
            child=child,
            item_a=item_a,
            item_b=item_b,
            planned_gender=state.gender,
            gender_policy=child_gender_policy(
                state,
                candidate.root,
                candidate.working_gender or candidate.target_gender,
                candidate.gender_strategy,
                sibling,
            ),
            nature_check_role=nature_check_role,
        )
        steps.append(step)
        account_by_id[child_id] = child_account
        result = (
            child_id,
            f"步骤 {number} 的子代 {child.species} {child.gender} {child.iv_string}"
            + (f"（{child.notes}）" if len(notes) > 1 else ""),
        )
        refs[id(state)] = result
        return result

    emit(candidate.root)
    return ExecutionPlan(
        id=plan_id,
        target_species=candidate.target_species or candidate.root.output_species,
        steps=steps,
        purchase_requirements=list(dict.fromkeys(purchase_requirements)),
        target_nature=candidate.target_nature,
        adaptive_nature=bool(candidate.target_nature and candidate.nature_strategy == "late"),
        target_iv_count=sum(value is not None for value in candidate.target_ivs),
        target_gender=candidate.target_gender,
        gender_strategy=candidate.gender_strategy,
        nature_phase=candidate.nature_phase,
        nature_target_key=candidate.nature_target_key,
        nature_attempt_level=candidate.nature_attempt_level,
    )
