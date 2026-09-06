"""Render the executable dependency graph, never a separately numbered proposal."""
from execution import ExecutionPlan, gender_name
from mind_map import MindMapNode
from models import Monster

ITEM_KEYS = dict(zip(
    ("HP护腕", "攻击护腕", "防御护腕", "特攻护腕", "特防护腕", "速度护腕", "不变之石"),
    ("power-weight", "power-bracer", "power-belt", "power-lens", "power-band", "power-anklet", "everstone"),
))


def execution_map(plan: ExecutionPlan, inventory, expanded, species_db) -> MindMapNode | None:
    producers = {step.child.id: step for step in plan.steps}
    inventory_by_id = {m.id: m for m in inventory}
    parents = {pid for step in plan.steps for pid in (step.parent_a_id, step.parent_b_id)}
    roots = [step for step in plan.steps if step.child.id not in parents]
    if not roots:
        return None

    def sprite(name):
        record = species_db.get(name, fuzzy=True)
        return record.id if record else None

    def values(monster):
        return tuple("X" if v is None else str(v) for v in monster.ivs)

    def build(step, edge_item="", path=frozenset()):
        if step.child.id in path:
            raise ValueError("执行路线存在循环依赖")
        path = path | {step.child.id}
        child = step.child
        opened = (plan.id, step.number) in expanded
        ready = plan.is_step_ready(step)
        status = ("已完成 · 来源已展开" if opened else "已完成 · 来源已折叠") if step.completed else (
            "执行暂停" if plan.needs_replan else "孵化中" if step.in_progress else "当前可执行" if ready else "等待下级完成")
        nature = "性格：锁定" if step.uses_everstone else (
            f"性格：{child.nature or '未命中目标'}" if step.completed and plan.should_check_nature(step)
            else "爆性格：待确认" if plan.should_check_nature(step) else "性格：暂不统计")
        node = MindMapNode(
            key=f"{plan.id}-step-{step.number}", step_number=step.number,
            title=f"{'已完成' if step.completed else '步骤 ' + str(step.number)} · {child.species}",
            iv_text=f"{sum(v == 31 for v in child.ivs)}V", iv_values=values(child),
            detail=(f"实际{gender_name(child.gender)}" if step.completed else step.gender_instruction)
                + f" · 子代 {child.species}" + (f" · {child.notes}" if child.notes else ""),
            item_text=f"本只携带：{edge_item or '无需道具'}", item_keys=(ITEM_KEYS[edge_item],) if edge_item in ITEM_KEYS else (),
            status_text=status, nature_text=nature,
            kind="completed" if step.completed else "in_progress" if step.in_progress else "current" if ready else "pending",
            completed=step.completed, in_progress=step.in_progress, actionable=ready, show_checkbox=True,
            history_toggleable=step.completed, sources_collapsed=step.completed and not opened, species_id=sprite(child.species),
        )
        if step.completed and not opened:
            return node
        for pid, label, item in ((step.parent_a_id, step.parent_a_label, step.item_a),
                                 (step.parent_b_id, step.parent_b_label, step.item_b)):
            if pid in producers:
                node.children.append(build(producers[pid], item, path))
                continue
            payload = plan.materials.get(pid)
            monster = Monster.from_dict(payload) if payload else inventory_by_id.get(pid)
            purchase = pid.startswith("buy:")
            historical = step.completed
            node.children.append(MindMapNode(
                key=f"{plan.id}-parent-{step.number}-{pid}",
                title=("已消耗 · " if historical else "待采购 · " if purchase else "库存 · ") + (monster.species if monster else label),
                iv_text=f"{sum(v == 31 for v in monster.ivs)}V" if monster else "",
                iv_values=values(monster) if monster else (),
                detail=label, item_text=f"本只携带：{item or '无需道具'}",
                item_keys=(ITEM_KEYS[item],) if item in ITEM_KEYS else (),
                status_text="历史来源（不可再次使用）" if historical else "待采购" if purchase else "库存",
                kind="completed" if historical else "purchase" if purchase else "inventory",
                completed=historical or not purchase, show_checkbox=False,
                species_id=sprite(monster.species) if monster else None,
            ))
        return node

    nodes = [build(step) for step in roots]
    if len(nodes) == 1:
        return nodes[0]
    return MindMapNode(key=f"{plan.id}-roots", title="执行路线", children=nodes)
