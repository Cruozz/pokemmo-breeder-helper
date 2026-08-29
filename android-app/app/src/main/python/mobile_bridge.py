"""Small JSON boundary between the native Android UI and the desktop planner.

Keep this module free of Android details.  It deliberately calls the same
``planner`` and ``execution`` modules as the Windows application so both clients
produce the same material choices and Nidoran/Ditto/nature-hand behavior.
"""

from __future__ import annotations

import json
import traceback
from typing import Any

from execution import build_execution_plan
from models import Monster, normalize_gender
from planner import make_report_with_candidates
from species_data import get_species_database


def _response(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


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
        iv_values = list(request.get("ivs") or ["31", "31", "31", "31", "31", "31"])
        iv_values = [str(value).strip() or "X" for value in iv_values[:6]]
        iv_values += ["X"] * (6 - len(iv_values))

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
            frozenset(),
            "smart",
            bool(request.get("need_hidden_ability", False)),
            (),
            bool(request.get("convert_maternal_with_ditto", False)),
            frozenset(),
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
        plan_value = plan.to_dict()
        producer_ids = {step.child.id for step in plan.steps}
        for step, step_value in zip(plan.steps, plan_value["steps"]):
            step_value["gender_instruction"] = step.gender_instruction
            step_value["requires_purchase"] = step.requires_purchase
            step_value["should_check_nature"] = plan.should_check_nature(step)
            step_value["is_final"] = not any(
                step.child.id in (other.parent_a_id, other.parent_b_id)
                for other in plan.steps
                if other is not step
            )
            step_value["dependencies"] = [
                parent_id
                for parent_id in (step.parent_a_id, step.parent_b_id)
                if parent_id in producer_ids
            ]
        plan_value["status_text"] = plan.status_text()
        plan_value["candidate_description"] = candidate.description()
        plan_value["inventory_used_count"] = len(
            [value for value in candidate.root.used_ids if not str(value).startswith("buy:")]
        )
        return _response(
            {
                "ok": True,
                "error": "",
                "report": report,
                "candidate_count": len(candidates),
                "plan": plan_value,
            }
        )
    except Exception as exc:  # Return a readable message across the JVM boundary.
        return _response(
            {
                "ok": False,
                "error": str(exc) or exc.__class__.__name__,
                "report": "",
                "candidate_count": 0,
                "plan": None,
                "debug": traceback.format_exc(limit=8),
            }
        )
