"""Exercise exactly the Python files shipped in the APK, without the repo on sys.path."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_packaged_python_dependency_closure(tmp_path):
    manifest = ROOT / "android-app/planner-modules.txt"
    for line in manifest.read_text(encoding="utf-8").splitlines():
        name = line.split("#", 1)[0].strip()
        if name:
            shutil.copy2(ROOT / name, tmp_path / name)
    shutil.copytree(ROOT / "data", tmp_path / "data")
    for source in (ROOT / "android-app/app/src/main/python").glob("*.py"):
        shutil.copy2(source, tmp_path / source.name)
    code = """
import sys, json
sys.path.insert(0, sys.argv[1])
import mobile_bridge, mobile_capture
assert json.loads(mobile_capture.parse_capture('[]'))['material'] is None
assert json.loads(mobile_bridge.search_species('伊布'))['items']
request = dict(species='伊布', ivs=['31','31','X','X','X','X'], max_purchase_v=1,
               strategy='cost', cost_pricing=dict(include_inventory_value=False))
result = json.loads(mobile_bridge.generate_plan('[]', json.dumps(request)))
assert result['ok'], result
assert result['plan']['cost_summary']
print(result['rules_version'])
"""
    result = subprocess.run([sys.executable, "-I", "-c", code, str(tmp_path)],
                            text=True, capture_output=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
