import importlib.util
import json
from pathlib import Path

from models import Monster
from planner import make_report_with_candidates
from execution import build_execution_plan, validate_cosmetic_inputs
import pytest

spec = importlib.util.spec_from_file_location("cosmetic_mobile_bridge", Path(__file__).resolve().parents[1] / "android-app/app/src/main/python/mobile_bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


@pytest.mark.parametrize("target_v",[5,6])
def test_high_v_costume_with_two_particles_is_preserved_through_actual_execution(target_v):
    inventory = [Monster(id="ninja", species="喵喵", gender="F", ivs=[31, None, None, None, None, None],
                         is_costume=True, particles=["bats", "ghosts"])]
    # Synthetic material supply. Enough independent 1V donors for the pyramid.
    for stat in range(target_v):
        for number in range(16):
            inventory.append(Monster(id=f"{stat}-{number}", species="喵喵", gender="M" if number % 2 else "F",
                                     ivs=[31 if i == stat else None for i in range(6)]))
    iv_text="/".join(["31"]*target_v+["x"]*(6-target_v))
    report, candidates = make_report_with_candidates(inventory, "猫老大", "F", "", iv_text, ["陆上"],
        allow_ditto=False, cosmetic_options={"particle_mode": "target", "target_particles": ["bats", "ghosts"], "target_costume": True})
    assert candidates, report
    candidate = candidates[0]
    assert candidate.root.mask.bit_count() == target_v
    assert candidate.root.costume_lineage == "ninja"
    assert candidate.root.particles == frozenset({"bats", "ghosts"})
    plan = build_execution_plan(candidate)
    for step in plan.steps:
        parents=[item for item in inventory if item.id in {step.parent_a_id, step.parent_b_id}]
        validate_cosmetic_inputs(plan, step, parents)
        inventory=[item for item in inventory if item not in parents]+[step.child]
        if step.child.is_costume and not plan.is_final_step(step):
            assert step.expected_gender == "F" and step.effective_gender_policy == "locked"
    assert plan.meets_cosmetic_target(plan.steps[-1].child)


def test_particle_and_costume_edit_after_planning_cannot_be_consumed():
    a=Monster(id="a",species="喵喵",gender="F",ivs=[31,None,None,None,None,None])
    b=Monster(id="b",species="喵喵",gender="M",ivs=[None,31,None,None,None,None])
    _, candidates=make_report_with_candidates([a,b],"喵喵","","","31/31/x/x/x/x",["陆上"])
    plan=build_execution_plan(candidates[0])
    a.is_costume=True
    with pytest.raises(ValueError,match="登记已改变"):
        validate_cosmetic_inputs(plan,plan.steps[0],[a,b])


def test_nature_restart_keeps_original_costume_lineage_and_accumulated_particles():
    body=Monster(id="body",species="喵喵",gender="F",nature="温顺",ivs=[31,31,31,None,None,None],
                 is_costume=True,costume_lineage="original-costume",particles=["bats","ghosts"])
    # Ordinary 2V mother must never replace the selected costume on continuation.
    other=Monster(id="cheaper",species="喵喵",gender="F",nature="温顺",ivs=[31,31,31,None,None,None])
    duplicate_hand=Monster(id="duplicate-hand",species="喵喵",gender="M",ivs=[31,31,None,None,None,None],particles=["bats"])
    inventory=[body.to_dict(),other.to_dict(),duplicate_hand.to_dict()]
    request=dict(species="猫老大",gender="F",nature="固执",ivs=["31","31","31","X","X","X"],
        target_costume=True,costume_lineage="original-costume",particle_mode="target",target_particles=["bats"],allow_ditto=False)
    response=json.loads(bridge.generate_plan(json.dumps(inventory),json.dumps(request)))
    assert response["ok"],response
    assert response["plan"]["retained_materials"][0]["id"]=="body"
    assert response["plan"]["planning_options"]["costume_lineage"]=="original-costume"
    assert response["plan"]["final_target"]["particles"]==["bats"]
    assert response["plan"]["final_target"]["is_costume"]
    assert all("duplicate-hand" not in {step["parent_a_id"],step["parent_b_id"]} for step in response["plan"]["steps"])
    for step in response["plan"]["steps"]:
        result=json.loads(bridge.complete_step(json.dumps(inventory),json.dumps(response),
            json.dumps(dict(number=step["number"],gender=step["planned_gender"],nature_hit=True))))
        assert result["ok"],result
        inventory,response=result["inventory"],result["response"]
        if response["plan"]["needs_replan"]: break
    # Replanning receives the saved request, including the original lineage.
    continued=json.loads(bridge.generate_plan(json.dumps(inventory),json.dumps(response["plan"]["planning_options"])))
    assert continued["ok"],continued
    final=continued["plan"]["steps"][-1]["child"]
    assert final["costume_lineage"]=="original-costume"
    assert set(final["particles"])=={"bats","ghosts"}
