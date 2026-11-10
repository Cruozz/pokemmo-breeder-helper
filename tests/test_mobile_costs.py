import json
from unittest.mock import patch

from test_mobile_bridge import _load_bridge
from models import Monster


def plan(bridge, **kwargs):
    request = dict(species="伊布", ivs=["31", "31", "31", "X", "X", "X"],
                   max_purchase_v=1, cost_pricing=dict(include_inventory_value=False))
    request.update(kwargs)
    return json.loads(bridge.generate_plan("[]", json.dumps(request)))


def test_cost_strategy_and_purchase_limit_reach_shared_planner():
    result = plan(_load_bridge(), strategy="cost")
    assert result["ok"], result
    saved = result["plan"]
    assert saved["planning_options"]["strategy"] == "cost"
    assert "还需支出" in saved["cost_summary"]
    assert "待报价" in saved["cost_summary"]
    for item in saved["materials"].values():
        if item["id"].startswith("buy:"):
            assert item["ivs"].count(31) <= 1


def test_purchase_limit_does_not_filter_existing_high_iv_stock():
    bridge = _load_bridge()
    inventory = [Monster(id="mother", species="伊布", gender="F", ivs=[31,31,31,1,1,1]).to_dict()]
    result = json.loads(bridge.generate_plan(json.dumps(inventory), json.dumps(dict(
        species="伊布", ivs=["31","31","31","X","X","X"], max_purchase_v=1))))
    assert result["ok"], result
    assert result["plan"]["steps"] == []


def test_no_market_data_never_recommends_automatic_purchases():
    bridge = _load_bridge()
    with patch.object(bridge, "_purchase_market_snapshot", return_value=None):
        result = plan(bridge, cost_pricing=dict(include_inventory_value=False, require_market_availability=True))
    assert not result["ok"]
    assert result["plan"] is None


def test_invalid_purchase_limit_and_prices_fail_without_mutation():
    bridge = _load_bridge()
    for limit in (0, 7, True, "3"):
        result = plan(bridge, max_purchase_v=limit)
        assert not result["ok"]
        assert "补购最高" in result["error"]
    assert not plan(bridge, cost_pricing=dict(brace=-1))["ok"]


def test_skill_preparation_requires_explicit_confirmation():
    bridge = _load_bridge()
    result = plan(bridge)
    assert result["ok"], result
    step = result["plan"]["steps"][0]
    step["preparations"] = [dict(parent_id=step["parent_a_id"], species="伊布", move="祈愿", method="测试学习准备")]
    outcome = dict(number=step["number"], gender=step["planned_gender"])
    rejected = json.loads(bridge.complete_step("[]", json.dumps(result), json.dumps(outcome)))
    assert not rejected["ok"]
    assert "技能准备" in rejected["error"]
    outcome["preparations_confirmed"] = True
    accepted = json.loads(bridge.complete_step("[]", json.dumps(result), json.dumps(outcome)))
    assert accepted["ok"], accepted
    assert accepted["response"]["plan"]["cost_summary"] == result["plan"]["cost_summary"]
