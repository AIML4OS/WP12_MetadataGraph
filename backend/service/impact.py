"""
Change-impact severity engine for classification version changes (US-03).

This is a small, pure module (no I/O, no LLM, no graph access) so it can be unit
tested in isolation. It consumes the reverse-impact subgraph produced by
``GraphStorage.traverse_directional(direction="reverse", ...)`` and classifies each
affected artefact by impact severity using deterministic, data-driven rules.

The LLM (see backend/ui/explanation_service.py) fills in the per-node
``recommended_review`` text afterwards; this module only assigns ``severity`` and the
``relationship_path`` from the changed classification to each dependent artefact.
"""

from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

# Severity buckets (kept stable — used as CSS class suffixes and report keys on the frontend)
SEVERITY_BREAKING = "breaking"
SEVERITY_ANNOTATION = "annotation-only"

# Reverse-impact relationships: from a classification / code list outward to the
# variables, structures and data sets that depend on it.
IMPACT_RELATIONSHIPS = ["USES_CODE_LIST", "HAS_VARIABLE", "HAS_STRUCTURE"]

# Variable roles that make a downstream structure/data set layout-breaking when their
# classification changes (a recoded identifier/measure changes the published table).
_BREAKING_ROLES = {"identifier", "measure", "dimension"}

NodeLike = Union[Dict[str, Any], Any]
EdgeLike = Union[Dict[str, Any], Any]


# ---------------------------------------------------------------------------
# Accessors that work with both serialized dicts and Node/Edge objects
# ---------------------------------------------------------------------------

def _get(obj: Any, key: str, attr: Optional[str] = None, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, attr or key, default)


def _node_id(n: NodeLike) -> str:
    return _get(n, "id", "id")


def _node_type(n: NodeLike) -> str:
    if isinstance(n, dict):
        return n.get("type", "")
    return getattr(n, "type_str", getattr(n, "type", ""))


def _node_name(n: NodeLike) -> str:
    return _get(n, "name", "name", "")


def _node_subtypes(n: NodeLike) -> List[str]:
    return _get(n, "subtypes", "subtypes", []) or []


def _node_metadata(n: NodeLike) -> Dict[str, Any]:
    return _get(n, "metadata", "metadata", {}) or {}


def _edge_source(e: EdgeLike) -> str:
    return _get(e, "source", "source")


def _edge_target(e: EdgeLike) -> str:
    return _get(e, "target", "target")


def _edge_type(e: EdgeLike) -> str:
    if isinstance(e, dict):
        return e.get("type", "")
    return getattr(e, "type_str", getattr(e, "type", ""))


# ---------------------------------------------------------------------------
# Severity rules
# ---------------------------------------------------------------------------

def normalize_change_type(change_type: Optional[str]) -> str:
    """Map a free-form change type onto a severity bucket name."""
    value = (change_type or "").strip().lower()
    if value in ("annotation", "annotation-only", "annotation_only", "non-breaking"):
        return SEVERITY_ANNOTATION
    # Default to the conservative (breaking) interpretation for anything else.
    return SEVERITY_BREAKING


def _is_breaking_variable(node: NodeLike) -> bool:
    """A coded identifier/measure variable whose code list change alters published output."""
    if node is None or _node_type(node) != "InstanceVariable":
        return False
    role = str(_node_metadata(node).get("role", "")).lower()
    if role in _BREAKING_ROLES:
        return True
    return any(str(s).lower() in _BREAKING_ROLES for s in _node_subtypes(node))


def _path_has_breaking_variable(path_ids: List[str], nodes_by_id: Dict[str, NodeLike]) -> bool:
    return any(_is_breaking_variable(nodes_by_id.get(nid)) for nid in path_ids)


def _severity_for(
    change_type: str,
    node_type: str,
    path_ids: List[str],
    nodes_by_id: Dict[str, NodeLike],
) -> str:
    """
    Deterministic rule table (relationship-position + node type -> severity).

    annotation change  -> everything is annotation-only.
    breaking change    -> direct variable consumers are breaking; transitive
                          structures/data sets are breaking only when a coded
                          identifier/measure sits on the dependency path,
                          otherwise annotation-only.
    """
    if change_type == SEVERITY_ANNOTATION:
        return SEVERITY_ANNOTATION

    if node_type == "InstanceVariable":
        return SEVERITY_BREAKING
    if node_type in ("DataStructure", "DataSet"):
        return SEVERITY_BREAKING if _path_has_breaking_variable(path_ids, nodes_by_id) else SEVERITY_ANNOTATION
    # Other artefacts (e.g. another code list, concept) are annotation-only.
    return SEVERITY_ANNOTATION


def _readable_path(
    path_ids: List[str],
    rels: List[str],
    nodes_by_id: Dict[str, NodeLike],
    changed_node: NodeLike,
) -> str:
    """Render 'Changed → REL → A → REL → B' for human-readable provenance."""

    def name(nid: str) -> str:
        if nid == _node_id(changed_node):
            return _node_name(changed_node)
        node = nodes_by_id.get(nid)
        return _node_name(node) if node is not None else nid

    parts = [name(path_ids[0])]
    for rel, nid in zip(rels, path_ids[1:]):
        parts.append(rel)
        parts.append(name(nid))
    return " → ".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assess_impact(
    changed_node: NodeLike,
    change_type: str,
    subgraph_nodes: List[NodeLike],
    subgraph_edges: List[EdgeLike],
    *,
    version_before: Optional[str] = None,
    version_after: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Classify the impact of a classification change over a reverse-impact subgraph.

    Args:
        changed_node: the changed classification / code list node (dict or Node)
        change_type: "breaking" or "annotation" (free-form, normalized internally)
        subgraph_nodes: nodes of the reverse-impact subgraph (includes the changed node)
        subgraph_edges: edges of the reverse-impact subgraph (natural source->target)
        version_before / version_after: optional version labels for the report header

    Returns:
        Dict with the changed-node summary, the flat ``affected`` list (each with
        ``severity`` and ``relationship_path``), and ``groups`` keyed by severity.
    """
    severity_bucket = normalize_change_type(change_type)
    changed_id = _node_id(changed_node)
    nodes_by_id: Dict[str, NodeLike] = {_node_id(n): n for n in subgraph_nodes}
    nodes_by_id.setdefault(changed_id, changed_node)

    # Reverse adjacency: an edge A --REL--> changed lets us step from changed back to A.
    reverse_adj: Dict[str, List[tuple]] = {}
    for edge in subgraph_edges:
        reverse_adj.setdefault(_edge_target(edge), []).append((_edge_source(edge), _edge_type(edge)))

    # Breadth-first walk outward from the changed node; BFS gives each artefact its
    # shortest dependency path.
    affected: List[Dict[str, Any]] = []
    visited = {changed_id}
    queue = deque([(changed_id, [], [changed_id])])
    while queue:
        current, rels, path_ids = queue.popleft()
        for neighbor, rel_type in reverse_adj.get(current, []):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            new_rels = rels + [rel_type]
            new_path = path_ids + [neighbor]
            node = nodes_by_id.get(neighbor)
            node_type = _node_type(node) if node is not None else "Unknown"
            affected.append({
                "id": neighbor,
                "name": _node_name(node) if node is not None else neighbor,
                "type": node_type,
                "severity": _severity_for(severity_bucket, node_type, new_path, nodes_by_id),
                "relationship_path": new_rels,
                "path": _readable_path(new_path, new_rels, nodes_by_id, changed_node),
                "recommended_review": "",
            })
            queue.append((neighbor, new_rels, new_path))

    # Stable ordering: breaking first, then by type, then name.
    severity_rank = {SEVERITY_BREAKING: 0, SEVERITY_ANNOTATION: 1}
    affected.sort(key=lambda a: (severity_rank.get(a["severity"], 9), a["type"], a["name"]))

    groups: Dict[str, List[Dict[str, Any]]] = {SEVERITY_BREAKING: [], SEVERITY_ANNOTATION: []}
    for item in affected:
        groups.setdefault(item["severity"], []).append(item)

    changed_meta = _node_metadata(changed_node)
    return {
        "change_type": severity_bucket,
        "changed_node": {
            "id": changed_id,
            "name": _node_name(changed_node),
            "type": _node_type(changed_node),
            "version_before": version_before if version_before is not None else changed_meta.get("version"),
            "version_after": version_after,
        },
        "affected": affected,
        "groups": groups,
        "summary": {
            "total_affected": len(affected),
            SEVERITY_BREAKING: len(groups.get(SEVERITY_BREAKING, [])),
            SEVERITY_ANNOTATION: len(groups.get(SEVERITY_ANNOTATION, [])),
        },
    }


def build_impact_report(impact_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Turn an impact result into a structured, exportable report (JSON + text rendering).

    Satisfies the US-03 acceptance criterion: an exportable structured report listing
    all affected artefacts and their type/severity.
    """
    changed = impact_result.get("changed_node", {})
    affected = impact_result.get("affected", [])
    summary = impact_result.get("summary", {})
    generated_at = datetime.utcnow().isoformat()

    version_before = changed.get("version_before")
    version_after = changed.get("version_after")
    version_line = ""
    if version_before or version_after:
        version_line = f" (version {version_before or '?'} → {version_after or '?'})"

    lines = [
        "Change Impact Report",
        "====================",
        f"Generated: {generated_at}",
        f"Changed classification: {changed.get('name', '')} [{changed.get('type', '')}]{version_line}",
        f"Change type: {impact_result.get('change_type', '')}",
        f"Affected artefacts: {summary.get('total_affected', 0)} "
        f"({summary.get(SEVERITY_BREAKING, 0)} breaking, "
        f"{summary.get(SEVERITY_ANNOTATION, 0)} annotation-only)",
        "",
    ]
    for severity in (SEVERITY_BREAKING, SEVERITY_ANNOTATION):
        items = impact_result.get("groups", {}).get(severity, [])
        if not items:
            continue
        lines.append(f"{severity.upper()} ({len(items)}):")
        for item in items:
            lines.append(f"  - {item['type']}: {item['name']}")
            if item.get("path"):
                lines.append(f"      via {item['path']}")
            if item.get("recommended_review"):
                lines.append(f"      review: {item['recommended_review']}")
        lines.append("")

    return {
        "report_version": "1.0",
        "generated_at": generated_at,
        "changed_node": changed,
        "change_type": impact_result.get("change_type", ""),
        "summary": summary,
        "affected": affected,
        "groups": impact_result.get("groups", {}),
        "text": "\n".join(lines).rstrip() + "\n",
    }
