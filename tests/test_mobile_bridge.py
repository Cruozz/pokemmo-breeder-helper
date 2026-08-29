import importlib.util
import json
from pathlib import Path


BRIDGE_PATH = (
    Path(__file__).resolve().parents[1]
    / "android-app"
    / "app"
    / "src"
    / "main"
    / "python"
    / "mobile_bridge.py"
)


def _load_bridge():
    spec = importlib.util.spec_from_file_location("mobile_bridge_test", BRIDGE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mobile_bridge_uses_desktop_nidoran_planning_rules():
    bridge = _load_bridge()
    search = json.loads(bridge.search_species("尼多王"))
    assert search["items"][0]["display_name"] == "尼多王"
    assert search["items"][0]["required_gender"] == "M"

    result = json.loads(
        bridge.generate_plan(
            "[]",
            json.dumps(
                {
                    "species": "尼多王",
                    "nature": "",
                    "ivs": ["31", "31", "31", "X", "X", "X"],
                    "allow_ditto": False,
                    "strategy": "inventory",
                },
                ensure_ascii=False,
            ),
        )
    )
    assert result["ok"] is True
    steps = result["plan"]["steps"]
    final = next(step for step in steps if step["is_final"])
    assert final["child"]["species"] == "尼多朗"
    assert final["child"]["gender"] == "M"
    assert any(
        step["child"]["species"] == "尼多兰" and step["child"]["gender"] == "F"
        for step in steps
        if not step["is_final"]
    )
