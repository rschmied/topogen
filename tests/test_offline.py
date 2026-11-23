from __future__ import annotations

import yaml

from topogen.offline import export_plan, main, nx_plan, simple_plan


def test_simple_plan_generates_chain(tmp_path):
    plan = simple_plan(3, 100, "lab", "iosv")
    assert len(plan.nodes) == 3
    assert [link.label for link in plan.links] == ["R1--R2", "R2--R3"]
    out = export_plan(plan, tmp_path / "lab.yaml")
    data = yaml.safe_load(out.read_text())
    assert data["lab"]["title"] == "lab"
    assert data["nodes"][0]["id"] == "n0"
    assert data["links"][0]["id"].startswith("l")


def test_simple_plan_allows_zero_links():
    plan = simple_plan(1, 100, "lab", "iosv")
    assert len(plan.nodes) == 1
    assert len(plan.links) == 0


def test_nx_plan_uses_prefix_ids():
    plan = nx_plan(2, 100, "lab", "iosv")
    assert plan.nodes[0].id.startswith("n")
    assert plan.links[0].id.startswith("l")


def test_nx_plan_assigns_unique_slots():
    plan = nx_plan(20, 100, "lab", "iosv")
    seen = set()
    for link in plan.links:
        left = (link.left.node_id, link.left.iface_slot)
        right = (link.right.node_id, link.right.iface_slot)
        assert left not in seen
        assert right not in seen
        seen.add(left)
        seen.add(right)


def test_mode_helpers_return_titles():
    assert simple_plan(2, 100, "lab", "iosv").title == "lab"
    assert nx_plan(2, 100, "lab", "iosv").title == "lab"


def test_main_uses_mode(monkeypatch, tmp_path):
    out = tmp_path / "lab.yaml"
    captured = {}

    def fake_export(plan, output):
        captured["title"] = plan.title
        captured["output"] = str(output)
        return out

    monkeypatch.setattr("topogen.offline.export_plan", fake_export)
    args = type("Args", (), {"nodes": 2, "distance": 100, "labname": "lab", "template": "iosv", "mode": "nx", "output": str(out)})()
    assert main(args) == 0
    assert captured["title"] == "lab"
    assert captured["output"] == str(out)
