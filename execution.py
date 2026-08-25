from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from chain_planner import ChainCandidate, ChainState, child_gender_policy, gender_name
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
        )


@dataclass
class ExecutionPlan:
    id: str
    target_species: str
    steps: list[ExecutionStep] = field(default_factory=list)
    purchase_requirements: list[str] = field(default_factory=list)
    target_nature: str = ""
    adaptive_nature: bool = False
    target_gender: str = ""
    gender_strategy: str = "lock_all"

    @property
    def next_step(self) -> ExecutionStep | None:
        return next((step for step in self.steps if not step.completed), None)

    @property
    def completed(self) -> bool:
        return bool(self.steps) and self.next_step is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 3,
            "id": self.id,
            "target_species": self.target_species,
            "steps": [step.to_dict() for step in self.steps],
            "purchase_requirements": list(self.purchase_requirements),
            "target_nature": self.target_nature,
            "adaptive_nature": self.adaptive_nature,
            "target_gender": self.target_gender,
            "gender_strategy": self.gender_strategy,
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
            target_gender=str(value.get("target_gender", "")),
            gender_strategy=str(value.get("gender_strategy", "lock_all")),
        )

    def status_text(self) -> str:
        step = self.next_step
        if step is None:
            return "方案已经全部执行完成。"
        if step.requires_purchase:
            return (
                f"下一步 {step.number}/{len(self.steps)} 遇到缺料节点。"
                "请到交易行手动采购该节点素材，OCR 扫描入库后重新生成方案；"
                "此前已勾选的库存步骤不会恢复。"
            )
        items = "、".join(item for item in (step.item_a, step.item_b) if item) or "无锁定道具"
        note = f"\n注意：{step.child.notes}" if step.child.notes else ""
        nature_note = ""
        if self.adaptive_nature and self.target_nature and not step.uses_everstone:
            nature_note = f"\n性格机会：本步未锁性格；孵出后请记录是否爆出 {self.target_nature}。"
        return (
            f"下一步 {step.number}/{len(self.steps)}：\n"
            f"父母 A：{step.parent_a_label}\n"
            f"父母 B：{step.parent_b_label}\n"
            f"道具：{items}\n"
            f"子代性别：{step.gender_instruction}\n"
            f"完成后得到：{'头目' if step.child.is_alpha else '普通'} "
            f"{step.child.species} {step.child.iv_string}{nature_note}{note}"
        )


def _leaf_label(state: ChainState) -> str:
    if state.leaf is None:
        return "未知素材"
    monster = state.leaf
    location = "/".join(value for value in (monster.page, monster.slot) if value)
    suffix = f"（仓库 {location}）" if location else ""
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
        child_ivs = [
            candidate.target_ivs[index] if state.mask & (1 << index) else None
            for index in range(6)
        ]
        notes = [f"由方案步骤 {number} 生成"]
        is_final_step = state is candidate.root
        if is_final_step and candidate.target_species and candidate.target_species != state.species:
            notes.append(f"孵化后需进化为最终目标 {candidate.target_species}")
        elif not is_final_step:
            next_breeding_species = state.breeding_species or candidate.breeding_species
            if next_breeding_species and next_breeding_species != state.species:
                notes.append(f"再次参与孵化前需进化为 {next_breeding_species}")
        child = Monster(
            id=child_id,
            species=state.species,
            gender=state.gender,
            nature=state.nature if state.has_nature else "",
            ivs=child_ivs,
            egg_groups=list(state.egg_groups),
            is_alpha=state.is_alpha,
            source=f"孵化方案 {plan_id} 步骤 {number}",
            verified=True,
            notes="；".join(notes),
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
                candidate.target_gender,
                candidate.gender_strategy,
                sibling,
            ),
        )
        steps.append(step)
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
        target_species=candidate.target_species or candidate.root.species,
        steps=steps,
        purchase_requirements=list(dict.fromkeys(purchase_requirements)),
        target_nature=candidate.target_nature,
        adaptive_nature=bool(candidate.target_nature and candidate.nature_strategy == "late"),
        target_gender=candidate.target_gender,
        gender_strategy=candidate.gender_strategy,
    )
