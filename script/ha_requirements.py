"""Print the libraries of the Home Assistant integrations homgar_ble depends on.

The test package installs Home Assistant without the libraries its integrations need
(bluetooth, usb, ...). Install them pinned to the installed Home Assistant:

    python script/ha_requirements.py > /tmp/ha_requirements.txt
    pip install -r /tmp/ha_requirements.txt -c "$(python script/ha_requirements.py --constraints)"
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import homeassistant

HA = Path(homeassistant.__file__).parent
MANIFEST = Path(__file__).parents[1] / "custom_components/homgar_ble/manifest.json"


def requirements() -> list[str]:
    seen: set[str] = set()
    reqs: set[str] = set()
    todo = list(json.loads(MANIFEST.read_text()).get("dependencies", []))
    while todo:
        domain = todo.pop()
        if domain in seen:
            continue
        seen.add(domain)
        manifest = json.loads((HA / "components" / domain / "manifest.json").read_text())
        reqs.update(manifest.get("requirements", []))
        todo += manifest.get("dependencies", [])
    return sorted(reqs)


if __name__ == "__main__":
    if sys.argv[1:] == ["--constraints"]:
        print(HA / "package_constraints.txt")
    else:
        print("\n".join(requirements()))
