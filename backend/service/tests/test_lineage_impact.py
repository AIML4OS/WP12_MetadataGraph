"""
Tests for US-03 lineage traversal and change-impact severity.

Covers:
- GraphStorage.traverse_directional (forward / reverse / depth / relationship filter)
- GraphStorage.get_lineage_subgraph (merged provenance + structure)
- backend.service.impact severity rules + report serialization
- GraphService.get_lineage / assess_change_impact / get_impact_report

The embedding model is mocked by the service-tests conftest, so add_nodes is cheap.
Node/Edge models accept arbitrary string types, so a synthetic GSIM-like lineage graph is
built directly without depending on the stockholmsprint schema.
"""

import os
import tempfile

import pytest

from backend.core import GraphStorage, Node, Edge
from backend.service import GraphService
from backend.service import impact


# ---------------------------------------------------------------------------
# Synthetic lineage graph
# ---------------------------------------------------------------------------
#
#   ds_in --INPUT_TO--> step --PRODUCES_OUTPUT--> ds_out --HAS_STRUCTURE--> struct
#   struct --HAS_VARIABLE--> var  (identifier) --USES_CODE_LIST--> nace  (Rev. 2)
#   struct --HAS_VARIABLE--> var2 (attribute)  --USES_CODE_LIST--> cl2

def _build_lineage_storage() -> GraphStorage:
    json_path = os.path.join(tempfile.mkdtemp(), "lineage.json")
    storage = GraphStorage(json_path=json_path)
    nodes = [
        Node(id="ds_in", type="DataSet", name="Raw input microdata", metadata={"role": "input"}),
        Node(id="step", type="ProcessStep", name="Aggregate",
             metadata={"classification_applied": ["NACE Rev. 2"], "transformation": "aggregate"}),
        Node(id="ds_out", type="DataSet", name="Output table"),
        Node(id="struct", type="DataStructure", name="Table structure"),
        Node(id="var", type="InstanceVariable", name="economic_activity", metadata={"role": "identifier"}),
        Node(id="var2", type="InstanceVariable", name="footnote", metadata={"role": "attribute"}),
        Node(id="nace", type="CodeList", name="NACE Rev. 2", metadata={"version": "Rev. 2"}),
        Node(id="cl2", type="CodeList", name="Footnote codes", metadata={"version": "1.0"}),
    ]
    edges = [
        Edge(id="e1", source="ds_in", target="step", type="INPUT_TO"),
        Edge(id="e2", source="step", target="ds_out", type="PRODUCES_OUTPUT"),
        Edge(id="e3", source="ds_out", target="struct", type="HAS_STRUCTURE"),
        Edge(id="e4", source="struct", target="var", type="HAS_VARIABLE"),
        Edge(id="e5", source="struct", target="var2", type="HAS_VARIABLE"),
        Edge(id="e6", source="var", target="nace", type="USES_CODE_LIST"),
        Edge(id="e7", source="var2", target="cl2", type="USES_CODE_LIST"),
    ]
    storage.add_nodes(nodes, edges)
    return storage


@pytest.fixture
def lineage_storage() -> GraphStorage:
    return _build_lineage_storage()


@pytest.fixture
def lineage_service(lineage_storage) -> GraphService:
    return GraphService(lineage_storage)


def _ids(result):
    return {n.id for n in result["nodes"]}


# ---------------------------------------------------------------------------
# traverse_directional
# ---------------------------------------------------------------------------

def test_forward_traversal_follows_structure(lineage_storage):
    result = lineage_storage.traverse_directional(
        "ds_out", "forward", ["HAS_STRUCTURE", "HAS_VARIABLE", "USES_CODE_LIST"], depth=4,
    )
    ids = _ids(result)
    assert {"struct", "var", "var2", "nace", "cl2"} <= ids
    # Provenance (reverse) nodes must NOT be reached going forward.
    assert "step" not in ids and "ds_in" not in ids


def test_reverse_traversal_follows_provenance(lineage_storage):
    result = lineage_storage.traverse_directional(
        "ds_out", "reverse", ["PRODUCES_OUTPUT", "INPUT_TO", "PRODUCES"], depth=4,
    )
    ids = _ids(result)
    assert {"step", "ds_in"} <= ids
    assert "struct" not in ids  # forward-only artefacts not reached


def test_depth_limit(lineage_storage):
    shallow = lineage_storage.traverse_directional("ds_out", "reverse", ["PRODUCES_OUTPUT", "INPUT_TO"], depth=1)
    ids = _ids(shallow)
    assert "step" in ids
    assert "ds_in" not in ids  # two hops away, beyond depth=1


def test_relationship_filter_stops_traversal(lineage_storage):
    result = lineage_storage.traverse_directional("ds_out", "forward", ["HAS_STRUCTURE"], depth=4)
    ids = _ids(result)
    assert "struct" in ids
    assert "var" not in ids  # HAS_VARIABLE not in the filter


def test_invalid_direction_raises(lineage_storage):
    with pytest.raises(ValueError):
        lineage_storage.traverse_directional("ds_out", "sideways")


def test_unknown_node_returns_empty(lineage_storage):
    assert lineage_storage.traverse_directional("missing", "forward") == {"nodes": [], "edges": []}


# ---------------------------------------------------------------------------
# get_lineage_subgraph
# ---------------------------------------------------------------------------

def test_lineage_subgraph_merges_both_directions(lineage_storage):
    result = lineage_storage.get_lineage_subgraph("ds_out")
    ids = _ids(result)
    # provenance side
    assert {"ds_in", "step", "ds_out"} <= ids
    # structure side
    assert {"struct", "var", "nace"} <= ids


# ---------------------------------------------------------------------------
# impact engine (pure)
# ---------------------------------------------------------------------------

def test_breaking_change_marks_coded_chain_breaking(lineage_storage):
    sub = lineage_storage.traverse_directional("nace", "reverse", impact.IMPACT_RELATIONSHIPS, depth=4)
    nace = lineage_storage.get_node("nace")
    result = impact.assess_impact(nace, "breaking", sub["nodes"], sub["edges"])
    sev = {a["id"]: a["severity"] for a in result["affected"]}
    assert sev["var"] == impact.SEVERITY_BREAKING
    assert sev["struct"] == impact.SEVERITY_BREAKING
    assert sev["ds_out"] == impact.SEVERITY_BREAKING
    assert result["summary"]["breaking"] == 3


def test_breaking_change_via_non_coded_variable_is_annotation(lineage_storage):
    # var2 is an attribute (not a coded identifier/measure): the structure/data set it
    # rolls up to are annotation-only even for a breaking classification change.
    sub = lineage_storage.traverse_directional("cl2", "reverse", impact.IMPACT_RELATIONSHIPS, depth=4)
    cl2 = lineage_storage.get_node("cl2")
    result = impact.assess_impact(cl2, "breaking", sub["nodes"], sub["edges"])
    sev = {a["id"]: a["severity"] for a in result["affected"]}
    assert sev["var2"] == impact.SEVERITY_BREAKING            # direct consumer is always breaking
    assert sev["struct"] == impact.SEVERITY_ANNOTATION        # transitive, non-coded
    assert sev["ds_out"] == impact.SEVERITY_ANNOTATION


def test_annotation_change_is_all_annotation(lineage_storage):
    sub = lineage_storage.traverse_directional("nace", "reverse", impact.IMPACT_RELATIONSHIPS, depth=4)
    nace = lineage_storage.get_node("nace")
    result = impact.assess_impact(nace, "annotation", sub["nodes"], sub["edges"])
    assert result["summary"]["breaking"] == 0
    assert all(a["severity"] == impact.SEVERITY_ANNOTATION for a in result["affected"])


def test_relationship_path_is_recorded(lineage_storage):
    sub = lineage_storage.traverse_directional("nace", "reverse", impact.IMPACT_RELATIONSHIPS, depth=4)
    nace = lineage_storage.get_node("nace")
    result = impact.assess_impact(nace, "breaking", sub["nodes"], sub["edges"])
    var = next(a for a in result["affected"] if a["id"] == "var")
    assert var["relationship_path"] == ["USES_CODE_LIST"]
    assert "NACE Rev. 2" in var["path"] and "economic_activity" in var["path"]


def test_normalize_change_type():
    assert impact.normalize_change_type("annotation") == impact.SEVERITY_ANNOTATION
    assert impact.normalize_change_type("annotation-only") == impact.SEVERITY_ANNOTATION
    assert impact.normalize_change_type("breaking") == impact.SEVERITY_BREAKING
    assert impact.normalize_change_type("") == impact.SEVERITY_BREAKING


def test_build_impact_report(lineage_storage):
    sub = lineage_storage.traverse_directional("nace", "reverse", impact.IMPACT_RELATIONSHIPS, depth=4)
    nace = lineage_storage.get_node("nace")
    result = impact.assess_impact(nace, "breaking", sub["nodes"], sub["edges"],
                                  version_before="Rev. 2", version_after="Rev. 2.1")
    report = impact.build_impact_report(result)
    assert report["report_version"] == "1.0"
    assert "BREAKING" in report["text"]
    assert "Rev. 2" in report["text"] and "Rev. 2.1" in report["text"]
    assert report["summary"]["total_affected"] == 3


# ---------------------------------------------------------------------------
# GraphService wrappers
# ---------------------------------------------------------------------------

def test_service_get_lineage(lineage_service):
    result = lineage_service.get_lineage("ds_out")
    assert result["success"] is True
    types = {n["type"] for n in result["nodes"]}
    assert "ProcessStep" in types
    assert any(n["id"] == "ds_in" for n in result["nodes"])


def test_service_assess_change_impact_records_change(lineage_service):
    result = lineage_service.assess_change_impact("nace", change_type="breaking", new_version="Rev. 2.1")
    assert result["success"] is True
    assert result["change_type"] == "breaking"
    assert result["summary"]["breaking"] == 3
    # severity also exposed via groups
    assert len(result["groups"]["breaking"]) == 3
    # version change recorded on the node metadata
    node = lineage_service.get_node_details("nace")["node"]
    assert node["metadata"]["version"] == "Rev. 2.1"
    assert node["metadata"]["last_change_type"] == "breaking"


def test_service_assess_change_impact_annotation(lineage_service):
    result = lineage_service.assess_change_impact("nace", change_type="annotation", record_change=False)
    assert result["summary"]["breaking"] == 0
    assert result["summary"]["annotation-only"] == 3


def test_service_get_impact_report(lineage_service):
    result = lineage_service.get_impact_report("nace", change_type="breaking")
    assert result["success"] is True
    assert "report" in result
    assert result["report"]["summary"]["total_affected"] == 3


def test_service_lineage_unknown_node(lineage_service):
    result = lineage_service.get_lineage("does-not-exist")
    assert result["success"] is False
