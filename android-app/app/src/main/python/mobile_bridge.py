"""Small JSON boundary between the native Android UI and the desktop planner.

Keep this module free of Android details.  It deliberately calls the same
``planner`` and ``execution`` modules as the Windows application so both clients
produce the same material choices and Nidoran/Ditto/nature-hand behavior.
"""

from __future__ import annotations

import json
import traceback
from typing import Any

from execution import ExecutionPlan, build_execution_plan
from models import Monster, normalize_gender
from planner import make_report_with_candidates, nature_matches, normalize_nature, parse_iv_requirements
from species_data import get_species_database
from reference_data import get_reference_database
from route_roles import RouteSource, classify_routes
from chain_planner import is_ditto

RULES_VERSION = "0.2.8"


def _final_target(plan: ExecutionPlan) -> Monster:
    snapshot, options = plan.candidate_snapshot, plan.planning_options
    return Monster(
        id=f"target-{plan.id}", species=plan.target_species, gender=plan.target_gender,
        nature=plan.target_nature,
        ivs=snapshot.get("target_ivs") or parse_iv_requirements("/".join(options.get("ivs") or ["X"] * 6)),
        is_alpha=bool(snapshot.get("target_alpha", options.get("target_alpha", False))),
        has_hidden_ability=bool(snapshot.get("target_hidden_ability", options.get("need_hidden_ability", False))),
        moves=list(snapshot.get("target_moves") or options.get("target_moves") or ()),
    )


def _meets_final_target(plan: ExecutionPlan, child: Monster) -> bool:
    """A phase root is not necessarily the finished product (e.g. a 4V hand)."""
    target = _final_target(plan)
    database = get_species_database()
    record = database.get(target.species, fuzzy=False)
    source = database.get(child.species, fuzzy=False)
    species_match = child.species == target.species or bool(
        record and source and source.id in {item.id for item in database.ancestry(record)}
    )
    return bool(
        species_match
        and all(required is None or actual == required for actual, required in zip(child.ivs, target.ivs))
        and sum(value is not None for value in child.ivs) >= plan.required_iv_count
        and (not target.nature or nature_matches(normalize_nature(target.nature), child.nature))
        and (not target.gender or child.gender == target.gender)
        and child.is_alpha == target.is_alpha
        and (not target.has_hidden_ability or child.has_hidden_ability)
        and set(target.moves).issubset(child.moves)
        and plan.nature_phase not in {"gamble_upper", "gamble_lower"}
    )


def _present_plan(plan: ExecutionPlan, inventory: list[Monster]) -> dict[str, Any]:
    """Render the exact saved execution plan, never generate a second UI tree."""
    database = get_species_database()
    value = plan.to_dict()
    producers = {step.child.id for step in plan.steps}
    known = {key: Monster.from_dict(item) for key, item in plan.materials.items()}
    known.update({monster.id: monster for monster in inventory})
    known.update({step.child.id: step.child for step in plan.steps})
    steps_by_id = {step.child.id: step for step in plan.steps}
    target_moves = set(_final_target(plan).moves)
    def source(key, path=frozenset()):
        if key in path:
            raise ValueError("执行路线存在循环依赖")
        monster = known.get(key) or _purchase_parent(key)
        step = steps_by_id.get(key)
        node = RouteSource(key, (step.planned_gender or monster.gender) if step else monster.gender if monster else "",
                           is_ditto(monster.species) if monster else False)
        if step:
            node.parents = [(source(step.parent_a_id, path | {key}), step.item_a),
                            (source(step.parent_b_id, path | {key}), step.item_b)]
        return node
    roles = {}
    for step in plan.steps:
        if plan.is_final_step(step):
            roles.update(classify_routes(source(step.child.id), nature_phase=plan.nature_phase))
    for step, item in zip(plan.steps, value["steps"]):
        item.update(
            route_role=roles.get(step.child.id, "iv"),
            route_moves=sorted(target_moves.intersection(step.child.moves)),
            display_gender=step.child.gender if step.completed else step.expected_gender if step.effective_gender_policy in {"locked", "fixed"} else "",
            gender_instruction=step.gender_instruction,
            gender_policy=step.effective_gender_policy,
            requires_purchase=step.requires_purchase,
            should_check_nature=plan.should_check_nature(step),
            is_final=plan.is_final_step(step),
            dependencies=[key for key in (step.parent_a_id, step.parent_b_id) if key in producers],
            child_species_id=_species_id(database, step.child.species),
        )
        for side, parent_id in (("a", step.parent_a_id), ("b", step.parent_b_id)):
            parent = known.get(parent_id) or _purchase_parent(parent_id)
            item[f"parent_{side}_species"] = parent.species if parent else ""
            item[f"parent_{side}_species_id"] = _species_id(database, parent.species) if parent else None
            item[f"parent_{side}_record"] = parent.to_dict() if parent else None
            item[f"parent_{side}_role"] = roles.get(parent_id, "iv")
            item[f"parent_{side}_moves"] = sorted(target_moves.intersection(parent.moves)) if parent else []
    value["status_text"] = plan.status_text()
    value["final_target"] = _final_target(plan).to_dict()
    value["final_target_species_id"] = _species_id(database, plan.target_species)
    value["phase_label"] = {
        "maternal": "母体升V", "gamble_upper": f"赌{plan.nature_attempt_level}V性格手",
        "gamble_lower": f"赌{plan.nature_attempt_level}V性格手", "promote": "性格手升V并合成",
        "guarantee": "性格保底并合成", "finish": "合成最终成品", "strict": "合成最终成品",
    }.get(plan.nature_phase, "合成最终成品")
    if plan.completed and not plan.needs_replan:
        value["phase_label"] = "成品已完成"
    value["retained_materials"] = [
        known[key].to_dict() for key in (
            plan.candidate_snapshot.get("retained_body_id"),
            plan.candidate_snapshot.get("retained_upper_id"),
        ) if key in known
    ]
    return value


def _response(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _species_id(database: Any, species: str) -> int | None:
    record = database.get(species, fuzzy=True) if species else None
    return record.id if record is not None else None


def _purchase_parent(parent_id: str) -> Monster | None:
    """Recover the useful display fields encoded in planner purchase IDs."""
    if not parent_id.startswith("buy:"):
        return None
    parts = parent_id.split(":")
    if len(parts) < 4:
        return None
    return Monster(id=parent_id, species=parts[2], gender=parts[3])


def search_species(query: str, limit: int = 12) -> str:
    database = get_species_database()
    records = database.search(query, max(1, min(int(limit), 30)))
    return _response(
        {
            "items": [
                {
                    "id": record.id,
                    "display_name": record.display_name,
                    "identifier": record.identifier,
                    "egg_moves": sorted(get_reference_database().egg_moves_for_species(record.id)),
                    "egg_groups": list(record.egg_groups),
                    "allowed_genders": list(record.allowed_genders),
                    "female_percent": record.female_percent,
                    "required_gender": database.required_evolution_gender(record) or "",
                    "offspring_species": (
                        database.breeding_offspring(record).display_name
                        if database.breeding_offspring(record)
                        else record.display_name
                    ),
                }
                for record in records
            ]
        }
    )


def generate_plan(inventory_json: str, request_json: str) -> str:
    try:
        raw_inventory = json.loads(inventory_json or "[]")
        request = json.loads(request_json or "{}")
        if not isinstance(raw_inventory, list):
            raise ValueError("库存 JSON 顶层必须是数组。")
        inventory = [
            Monster.from_dict(item)
            for item in raw_inventory
            if isinstance(item, dict)
        ]

        database = get_species_database()
        record = database.get(str(request.get("species", "")), fuzzy=True)
        if record is None:
            raise ValueError("没有找到目标精灵，请先从搜索结果中选择。")
        breeding_parent = database.breeding_parent(record)
        groups = list(breeding_parent.egg_groups if breeding_parent else record.egg_groups)

        requested_gender = normalize_gender(str(request.get("target_gender", "")))
        required_gender = database.required_evolution_gender(record) or ""
        target_gender = required_gender or (
            requested_gender if bool(request.get("lock_gender", False)) else ""
        )
        iv_values = list(request.get("ivs") or ["X"] * 6)
        iv_values = [str(value).strip() or "X" for value in iv_values[:6]]
        iv_values += ["X"] * (6 - len(iv_values))
        selected_moves = get_reference_database().normalize_egg_move_selection(record.id, request.get("target_moves"))
        request["target_moves"] = list(selected_moves)

        report, candidates = make_report_with_candidates(
            inventory,
            record.display_name,
            target_gender,
            str(request.get("nature", "")).strip(),
            "/".join(iv_values),
            groups,
            bool(request.get("target_alpha", False)),
            bool(request.get("allow_ditto", True)),
            "steps" if request.get("strategy") == "steps" else "inventory",
            "late",
            bool(request.get("allow_alpha_materials", False)),
            frozenset(request.get("excluded_ids") or ()),
            "lock_all",
            bool(request.get("need_hidden_ability", False)),
            selected_moves,
            bool(request.get("convert_maternal_with_ditto", False)),
            frozenset(request.get("preferred_material_ids") or ()),
        )
        if not candidates:
            return _response(
                {
                    "ok": False,
                    "error": "没有找到可执行路线。",
                    "report": report,
                    "candidate_count": 0,
                    "plan": None,
                }
            )

        candidate = candidates[0]
        plan = build_execution_plan(candidate)
        plan.planning_options = request
        if not plan.steps and (candidate.root.leaf is None or not _meets_final_target(plan, candidate.root.leaf)):
            return _response({"ok": False, "error": "当前阶段没有可执行步骤，且现有素材尚未满足最终目标。",
                              "report": report, "candidate_count": 0, "plan": None})
        plan.lock_known_counterparts(inventory)
        plan_value = _present_plan(plan, inventory)
        plan_value["candidate_description"] = candidate.description()
        plan_value["inventory_used_count"] = len(
            [value for value in candidate.root.used_ids if not str(value).startswith("buy:")]
        )
        return _response(
            {
                "ok": True,
                "rules_version": RULES_VERSION,
                "error": "",
                "report": report,
                "candidate_count": len(candidates),
                "plan": plan_value,
            }
        )


    except Exception as exc:
        return _response({"ok": False, "error": str(exc), "plan": None,
                          "debug": traceback.format_exc(limit=8)})


def complete_step(inventory_json: str, response_json: str, outcome_json: str) -> str:
    """Pure transaction: return new inventory/plan only after all checks pass.

    Android persists both atomically. No desktop files or game APIs are used.
    Just like 0.2.2, a changed outcome PAUSES the saved route; it does not
    silently replace the user's plan with a newly generated candidate.
    """
    try:
        response = json.loads(response_json)
        if response.get("rules_version") != RULES_VERSION:
            raise ValueError("旧版路线仅保留为备忘，请按当前规则重新生成并启用路线；已完成子代仍保留。")
        inventory = [Monster.from_dict(item) for item in json.loads(inventory_json)]
        outcome = json.loads(outcome_json)
        plan = ExecutionPlan.from_dict(response["plan"])
        step = next((item for item in plan.steps if item.number == int(outcome["number"])), None)
        if step is None or not plan.is_step_ready(step):
            raise ValueError("步骤已完成、尚有依赖，或路线已暂停；不能核销。")
        actual_ids = {step.parent_a_id, step.parent_b_id} - {
            key for key in (step.parent_a_id, step.parent_b_id) if key.startswith("buy:")
        }
        if step.parent_a_id == step.parent_b_id:
            raise ValueError("不能重复使用同一只素材。")
        if not actual_ids.issubset({item.id for item in inventory}):
            raise ValueError("父母素材已不在库存，请核对或重新规划。")
        if any(item.id == step.child.id for item in inventory):
            raise ValueError("该子代已经入库，不能重复核销。")
        child = Monster.from_dict(step.child.to_dict())
        if step.effective_gender_policy == "random":
            gender = normalize_gender(str(outcome.get("gender", "")))
            if gender not in {"F", "M"}:
                raise ValueError("请记录实际孵出的性别。")
            child.gender = gender
        else:
            child.gender = step.expected_gender
            child.gender_unconfirmed = step.effective_gender_policy == "irrelevant"
        checked = plan.should_check_nature(step)
        hit = False
        if checked:
            if type(outcome.get("nature_hit")) is not bool:
                raise ValueError("请确认是否爆出目标性格。")
            hit = outcome["nature_hit"]
            child.nature = plan.target_nature if hit else ""
            child.breeding_target_key = plan.nature_target_key
            child.breeding_role = "nature_hand" if step.nature_check_role == "nature_hand" else "maternal"
            child.nature_attempt_level = sum(value is not None for value in child.ivs)
            child.nature_attempt_result = "hit" if hit else "miss"
        final = plan.is_final_step(step)
        all_done = all(item.completed or item is step for item in plan.steps)
        gender_pending = final and hit and step.nature_check_role != "nature_hand" and plan.target_gender in {"F", "M"} and child.gender != plan.target_gender
        mismatch = step.effective_gender_policy != "irrelevant" and child.gender != (step.planned_gender or step.child.gender)
        paused = bool(
            (mismatch and not all_done) or (hit and (not all_done or gender_pending))
            or (hit and step.nature_check_role == "nature_hand") or (final and checked and not hit)
        )
        finished = bool(final and all_done and not paused and _meets_final_target(plan, child))
        paused = paused or bool(final and all_done and not finished)
        updated = [item for item in inventory if item.id not in actual_ids]
        if not finished:
            updated.append(child)
        step.child, step.completed, step.in_progress = child, True, False
        plan.lock_known_counterparts(updated)
        plan.needs_replan = paused
        if paused:
            plan.replan_reason = (
                "实际性别与原计划不同" if mismatch else
                "命中目标性格，请查看下一阶段建议" if hit else
                "本档未命中目标性格，进入下一档性格手或保底" if checked else
                "当前阶段已完成，子代已保留；继续按最终目标规划"
            )
            plan.planning_options["preferred_material_ids"] = [child.id]
        presented = _present_plan(plan, updated)
        # These describe the original candidate, not the remaining inventory.
        for key in ("candidate_description", "inventory_used_count"):
            if key in response["plan"]:
                presented[key] = response["plan"][key]
        response["plan"] = presented
        return _response({"ok": True, "inventory": [item.to_dict() for item in updated],
                          "response": response, "message": "成品已完成，不再进入素材库存。" if finished else
                          "结果已保存，原路线暂停；生成建议并确认启用后继续。" if paused else "父母已核销，子代已保存；继续原路线。"})
    except Exception as exc:
        return _response({"ok": False, "error": str(exc)})
