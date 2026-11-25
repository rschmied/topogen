from __future__ import annotations

import pytest
import yaml

from topogen.exporter import (
    ExportInterface,
    ExportLab,
    ExportLink,
    ExportNode,
    ExportTopology,
    TopologyExportError,
    from_plan,
    to_dict,
    to_yaml,
)
from topogen.models import Point
from topogen.planner import (
    PlannedInterface,
    PlannedLink,
    PlannedLinkEnd,
    PlannedNode,
    TopologyPlan,
    TopologyPlanError,
    build_text_ids,
    validate_plan,
)


def test_to_dict_minimal_topology():
    topo = ExportTopology(
        lab=ExportLab(version="0.3.0", title="lab"),
        nodes=[
            ExportNode(
                id="n1",
                label="R1",
                node_definition="lxc",
                x=0,
                y=0,
                interfaces=[ExportInterface(id="i1", label="eth0", slot=0)],
            )
        ],
        links=[ExportLink(id="l1", n1="n1", n2="n2", i1="i1", i2="i2", label="a-b")],
    )

    data = to_dict(topo)

    assert data["lab"] == {
        "version": "0.3.0",
        "title": "lab",
        "description": "",
        "notes": "",
    }
    assert data["nodes"][0]["id"] == "n1"
    assert data["nodes"][0]["node_definition"] == "lxc"
    assert data["nodes"][0]["interfaces"][0]["id"] == "i1"
    assert data["links"][0]["id"] == "l1"
    assert data["links"][0]["conditioning"] == {}


def test_from_plan_builds_export_topology():
    plan = TopologyPlan(
        title="lab",
        nodes=[
            PlannedNode(
                id="n1",
                label="R1",
                node_definition="lxc",
                pos=Point(0, 0),
                interfaces=[PlannedInterface(label="eth0", slot=0)],
            ),
            PlannedNode(
                id="n2",
                label="R2",
                node_definition="lxc",
                pos=Point(1, 1),
                interfaces=[PlannedInterface(label="eth0", slot=0)],
            ),
        ],
        links=[
            PlannedLink(
                id="l1",
                left=PlannedLinkEnd(node_id="n1", iface_slot=0),
                right=PlannedLinkEnd(node_id="n2", iface_slot=0),
            )
        ],
    )
    topo = from_plan(plan)
    assert topo.nodes[0].interfaces[0].id == "i10"
    assert topo.links[0].i1 == "i10"


def test_to_yaml_round_trip():
    topo = ExportTopology(
        lab=ExportLab(version="0.3.0", title="lab"),
        nodes=[],
        links=[],
    )
    data = yaml.safe_load(to_yaml(topo))
    assert data["lab"]["title"] == "lab"
    assert data["nodes"] == []
    assert data["links"] == []


def test_exported_shape_matches_expected_keys():
    topo = ExportTopology(
        lab=ExportLab(version="0.3.0", title="lab"),
        nodes=[],
        links=[],
    )
    data = to_dict(topo)
    assert set(data) == {"annotations", "smart_annotations", "nodes", "links", "lab"}
    assert set(data["lab"]) == {"version", "title", "description", "notes"}


def test_validate_plan_rejects_bad_inputs():
    with pytest.raises(TopologyPlanError):
        validate_plan(TopologyPlan(title=""))
    with pytest.raises(TopologyPlanError):
        validate_plan(
            TopologyPlan(
                title="lab",
                nodes=[
                    PlannedNode(
                        id="n1", label="R1", node_definition="", pos=Point(0, 0)
                    )
                ],
            )
        )
    with pytest.raises(TopologyPlanError):
        validate_plan(
            TopologyPlan(
                title="lab",
                nodes=[
                    PlannedNode(
                        id="n1", label="R1", node_definition="lxc", pos=Point(0, 0)
                    ),
                    PlannedNode(
                        id="n1", label="R2", node_definition="lxc", pos=Point(1, 1)
                    ),
                ],
            )
        )
    with pytest.raises(TopologyPlanError):
        validate_plan(
            TopologyPlan(
                title="lab",
                nodes=[
                    PlannedNode(
                        id="n1", label="R1", node_definition="lxc", pos=Point(0, 0)
                    )
                ],
                links=[
                    PlannedLink(
                        id="l1",
                        left=PlannedLinkEnd(node_id="n1", iface_slot=0),
                        right=PlannedLinkEnd(node_id="n2", iface_slot=0),
                    )
                ],
            )
        )
    with pytest.raises(TopologyPlanError):
        validate_plan(
            TopologyPlan(
                title="lab",
                nodes=[
                    PlannedNode(
                        id="n1", label="R1", node_definition="lxc", pos=Point(0, 0)
                    )
                ],
                links=[
                    PlannedLink(
                        id="l1",
                        left=PlannedLinkEnd(node_id="n1", iface_slot=0),
                        right=PlannedLinkEnd(node_id="n1", iface_slot=0),
                    )
                ],
            )
        )


def test_build_text_ids():
    assert build_text_ids(3, "n") == ["n0", "n1", "n2"]
    with pytest.raises(TopologyPlanError):
        build_text_ids(-1, "n")


@pytest.mark.parametrize(
    "lab",
    [
        ExportLab(version="", title="lab"),
        ExportLab(version="0.3.0", title=""),
    ],
)
def test_to_dict_requires_lab_fields(lab: ExportLab):
    topo = ExportTopology(lab=lab)
    with pytest.raises(TopologyExportError):
        to_dict(topo)
