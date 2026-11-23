from __future__ import annotations

from pathlib import Path

import yaml

FIXTURE = Path(__file__).parent / "data" / "topogen_lab_export.yaml"


def test_fixture_shape_loads():
    data = yaml.safe_load(FIXTURE.read_text())
    assert data["lab"]["version"] == "0.3.0"
    assert data["nodes"]
    assert data["links"]
    assert data["nodes"][0]["node_definition"] == "lxc"


def test_fixture_contains_minimal_export_keys():
    data = yaml.safe_load(FIXTURE.read_text())
    assert set(data) == {"annotations", "smart_annotations", "nodes", "links", "lab"}
    assert data["nodes"][0]["id"].startswith("n")
    assert data["links"][0]["id"].startswith("l")
