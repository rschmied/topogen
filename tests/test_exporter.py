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
    validate_topology,
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
            ),
            ExportNode(
                id="n2",
                label="R2",
                node_definition="lxc",
                x=1,
                y=1,
                interfaces=[ExportInterface(id="i2", label="eth0", slot=0)],
            ),
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


def test_to_dict_keeps_boot_disk_size_separate_from_cpu_limit():
    topo = ExportTopology(
        lab=ExportLab(version="0.3.0", title="lab"),
        nodes=[
            ExportNode(
                id="n1",
                label="R1",
                node_definition="alpine",
                x=0,
                y=0,
                boot_disk_size=16,
                cpu_limit=100,
            )
        ],
    )
    data = to_dict(topo)
    assert data["nodes"][0]["boot_disk_size"] == 16
    assert data["nodes"][0]["cpu_limit"] == 100


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


def test_to_yaml_uses_literal_blocks_for_multiline_configuration():
    topo = ExportTopology(
        lab=ExportLab(version="0.3.0", title="lab"),
        nodes=[
            ExportNode(
                id="n1",
                label="R1",
                node_definition="frr",
                x=0,
                y=0,
                configuration=[{"name": "node.cfg", "content": "line one\nline two"}],
            )
        ],
    )
    rendered = to_yaml(topo)
    assert "content: |-\n" in rendered
    assert "      line one\n      line two" in rendered
    assert (
        yaml.safe_load(rendered)["nodes"][0]["configuration"]
        == topo.nodes[0].configuration
    )


def test_exported_shape_matches_expected_keys():
    topo = ExportTopology(
        lab=ExportLab(version="0.3.0", title="lab"),
        nodes=[],
        links=[],
    )
    data = to_dict(topo)
    assert set(data) == {"annotations", "smart_annotations", "nodes", "links", "lab"}
    assert set(data["lab"]) == {"version", "title", "description", "notes"}


@pytest.mark.parametrize(
    ("topo", "match"),
    [
        (
            ExportTopology(
                lab=ExportLab(version="0.3.0", title="lab"),
                nodes=[
                    ExportNode(id="n1", label="R1", node_definition="frr", x=0, y=0),
                    ExportNode(id="n1", label="R2", node_definition="frr", x=1, y=1),
                ],
            ),
            "duplicate node id",
        ),
        (
            ExportTopology(
                lab=ExportLab(version="0.3.0", title="lab"),
                nodes=[
                    ExportNode(
                        id="n1",
                        label="R1",
                        node_definition="frr",
                        x=0,
                        y=0,
                        interfaces=[
                            ExportInterface(id="i0", label="eth0", slot=0),
                            ExportInterface(id="i0", label="eth1", slot=1),
                        ],
                    )
                ],
            ),
            "duplicate interface id",
        ),
        (
            ExportTopology(
                lab=ExportLab(version="0.3.0", title="lab"),
                nodes=[
                    ExportNode(id="n1", label="R1", node_definition="frr", x=0, y=0)
                ],
                links=[
                    ExportLink(
                        id="l1", n1="n1", n2="n2", i1="i0", i2="i0", label="link"
                    )
                ],
            ),
            "missing node",
        ),
        (
            ExportTopology(
                lab=ExportLab(version="0.3.0", title="lab"),
                nodes=[
                    ExportNode(id="n1", label="R1", node_definition="frr", x=0, y=0)
                ],
                links=[
                    ExportLink(id="", n1="n1", n2="n1", i1="i0", i2="i0", label="link")
                ],
            ),
            "link id is required",
        ),
    ],
)
def test_validate_topology_rejects_invalid_nodes_and_links(topo, match):
    with pytest.raises(TopologyExportError, match=match):
        validate_topology(topo)


@pytest.mark.parametrize(
    ("node", "match"),
    [
        (
            ExportNode(id="", label="R1", node_definition="frr", x=0, y=0),
            "node id is required",
        ),
        (
            ExportNode(id="n1", label="R1", node_definition="", x=0, y=0),
            "node n1 node_definition is required",
        ),
        (
            ExportNode(
                id="n1",
                label="R1",
                node_definition="frr",
                x=0,
                y=0,
                interfaces=[ExportInterface(id="", label="eth0", slot=0)],
            ),
            "interface id is required",
        ),
        (
            ExportNode(
                id="n1",
                label="R1",
                node_definition="frr",
                x=0,
                y=0,
                interfaces=[ExportInterface(id="i0", label="", slot=0)],
            ),
            "label is required",
        ),
        (
            ExportNode(
                id="n1",
                label="R1",
                node_definition="frr",
                x=0,
                y=0,
                interfaces=[ExportInterface(id="i0", label="eth0", slot=-1)],
            ),
            "slot must be >= 0",
        ),
        (
            ExportNode(
                id="n1",
                label="R1",
                node_definition="frr",
                x=0,
                y=0,
                interfaces=[
                    ExportInterface(id="i0", label="eth0", slot=0),
                    ExportInterface(id="i1", label="eth1", slot=0),
                ],
            ),
            "duplicate interface slot",
        ),
    ],
)
def test_validate_topology_rejects_invalid_node_fields(node, match):
    topo = ExportTopology(lab=ExportLab(version="0.3.0", title="lab"), nodes=[node])
    with pytest.raises(TopologyExportError, match=match):
        validate_topology(topo)


@pytest.mark.parametrize(
    ("link", "match"),
    [
        (
            ExportLink(id="", n1="n1", n2="n2", i1="i0", i2="i0", label="link"),
            "link id is required",
        ),
        (
            ExportLink(id="l1", n1="n1", n2="n1", i1="i0", i2="i0", label="link"),
            "self-links node n1",
        ),
    ],
)
def test_validate_topology_rejects_invalid_link_fields(link, match):
    nodes = [
        ExportNode(
            id="n1",
            label="R1",
            node_definition="frr",
            x=0,
            y=0,
            interfaces=[ExportInterface(id="i0", label="eth0", slot=0)],
        ),
        ExportNode(
            id="n2",
            label="R2",
            node_definition="frr",
            x=1,
            y=1,
            interfaces=[ExportInterface(id="i0", label="eth0", slot=0)],
        ),
    ]
    topo = ExportTopology(
        lab=ExportLab(version="0.3.0", title="lab"), nodes=nodes, links=[link]
    )
    with pytest.raises(TopologyExportError, match=match):
        validate_topology(topo)


def test_validate_topology_rejects_duplicate_link_id():
    nodes = [
        ExportNode(
            id="n1",
            label="R1",
            node_definition="frr",
            x=0,
            y=0,
            interfaces=[ExportInterface(id="i0", label="eth0", slot=0)],
        ),
        ExportNode(
            id="n2",
            label="R2",
            node_definition="frr",
            x=1,
            y=1,
            interfaces=[ExportInterface(id="i0", label="eth0", slot=0)],
        ),
        ExportNode(
            id="n3",
            label="R3",
            node_definition="frr",
            x=2,
            y=2,
            interfaces=[ExportInterface(id="i0", label="eth0", slot=0)],
        ),
    ]
    topo = ExportTopology(
        lab=ExportLab(version="0.3.0", title="lab"),
        nodes=nodes,
        links=[
            ExportLink(id="l1", n1="n1", n2="n2", i1="i0", i2="i0", label="first"),
            ExportLink(id="l1", n1="n2", n2="n3", i1="i0", i2="i0", label="second"),
        ],
    )
    with pytest.raises(TopologyExportError, match="duplicate link id"):
        validate_topology(topo)


def test_validate_topology_rejects_missing_or_reused_interfaces():
    nodes = [
        ExportNode(
            id="n1",
            label="R1",
            node_definition="frr",
            x=0,
            y=0,
            interfaces=[ExportInterface(id="i0", label="eth0", slot=0)],
        ),
        ExportNode(
            id="n2",
            label="R2",
            node_definition="frr",
            x=1,
            y=1,
            interfaces=[ExportInterface(id="i0", label="eth0", slot=0)],
        ),
        ExportNode(
            id="n3",
            label="R3",
            node_definition="frr",
            x=2,
            y=2,
            interfaces=[ExportInterface(id="i0", label="eth0", slot=0)],
        ),
    ]
    missing = ExportTopology(
        lab=ExportLab(version="0.3.0", title="lab"),
        nodes=nodes,
        links=[ExportLink(id="l1", n1="n1", n2="n2", i1="i1", i2="i0", label="link")],
    )
    with pytest.raises(TopologyExportError, match="missing interface"):
        validate_topology(missing)
    reused = ExportTopology(
        lab=ExportLab(version="0.3.0", title="lab"),
        nodes=nodes,
        links=[
            ExportLink(id="l1", n1="n1", n2="n2", i1="i0", i2="i0", label="first"),
            ExportLink(id="l2", n1="n1", n2="n3", i1="i0", i2="i0", label="second"),
        ],
    )
    with pytest.raises(TopologyExportError, match="reuses interface"):
        validate_topology(reused)


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
    with pytest.raises(TopologyPlanError):
        build_text_ids(1, "")


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
