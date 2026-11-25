from __future__ import annotations

from pathlib import Path

import yaml

from topogen.offline import reference_json

REFERENCE = Path(__file__).parent / "data" / "topogen_reference.yaml"


def _normalize(data: dict) -> dict:
    for node in data["nodes"]:
        if node["label"] == "dns-host":
            node["configuration"] = []
        for config in node["configuration"]:
            config["content"] = config["content"].rstrip("\n")
    return data


def test_three_router_nx_matches_reference_json():
    expected = _normalize(yaml.safe_load(REFERENCE.read_text()))
    assert _normalize(reference_json()) == expected
