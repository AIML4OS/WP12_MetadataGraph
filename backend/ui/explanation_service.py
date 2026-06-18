"""
ExplanationService - LLM plain-language explanations for individual graph entities (US-03).

Reuses the existing LLM provider abstraction (backend.llm_providers) and the schema-driven
prompt context (presentation.prompt_prefix). Given a node it builds a compact prompt from the
node's details and immediate relationships and asks for a plain-language explanation:
- what the entity represents,
- what process / transformation produced it,
- which quality dimensions or classifications apply.

For a ProcessStep it asks specifically about the methodological choices and the classification
or code list applied. In impact mode (a `context` describing a classification version change is
supplied) it asks what attribute or mapping must be reviewed.

Degrades gracefully: when no LLM provider is configured it returns a deterministic templated
explanation built from the node fields and relationships, mirroring the `llmAvailable` handling
elsewhere in the app.
"""

from typing import Any, Dict, List, Optional
import json
import logging
import os

from backend import config_loader
from backend.llm_providers import create_provider, get_llm_availability

logger = logging.getLogger(__name__)

# Metadata keys that are system/visualization noise and should not feed the prompt.
_NOISE_METADATA_KEYS = {
    "node_ids", "positions", "edges", "edge_ids", "groups", "parentIds",
    "view_data", "hidden_nodes", "embedding",
}


class ExplanationService:
    """Produces plain-language explanations for a single node, with graceful fallback."""

    def __init__(self, graph_service):
        self._graph_service = graph_service

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def explain_node(
        self,
        node_id: str,
        context: Optional[Dict[str, Any]] = None,
        api_key: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Explain a single node in plain language.

        Args:
            node_id: ID of the node to explain
            context: optional impact context, e.g.
                {classification_name, version_before, version_after, change_type,
                 relationship_path, severity}
            api_key / provider: optional LLM overrides

        Returns:
            Dict: {success, explanation, llm_available, node_id}
        """
        details = self._graph_service.get_node_details(node_id)
        if not details.get("success"):
            return {"success": False, "error": details.get("error", f"Node {node_id} not found")}
        node = details["node"]

        related = self._graph_service.get_related_nodes(node_id, depth=1)
        relationships = self._summarize_relationships(node_id, related)

        availability = get_llm_availability()
        provider_type = provider or availability.get("provider", "claude")
        env_key = os.getenv("ANTHROPIC_API_KEY") if provider_type == "claude" else os.getenv("OPENAI_API_KEY")
        key_to_use = api_key or env_key

        if not key_to_use:
            # No LLM configured — return a deterministic, useful fallback.
            return {
                "success": True,
                "node_id": node_id,
                "llm_available": False,
                "explanation": self._fallback_explanation(node, relationships, context),
            }

        try:
            system_prompt = self._build_system_prompt()
            user_prompt = self._build_user_prompt(node, relationships, context)
            llm = create_provider(key_to_use, provider_type)
            response = llm.create_completion(
                messages=[{"role": "user", "content": user_prompt}],
                system_prompt=system_prompt,
                tools=[],
                max_tokens=900,
            )
            text = "".join(
                block.get("text", "")
                for block in response.content
                if isinstance(block, dict) and block.get("type") == "text"
            ).strip()
            if not text:
                text = self._fallback_explanation(node, relationships, context)
                return {"success": True, "node_id": node_id, "llm_available": False, "explanation": text}
            return {"success": True, "node_id": node_id, "llm_available": True, "explanation": text}
        except Exception as exc:  # pragma: no cover - network/provider errors
            logger.warning("explain_node LLM call failed for %s: %s", node_id, exc)
            return {
                "success": True,
                "node_id": node_id,
                "llm_available": False,
                "explanation": self._fallback_explanation(node, relationships, context),
            }

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        presentation = config_loader.get_presentation()
        prefix = presentation.get("prompt_prefix", "")
        return (
            f"{prefix}\n\n"
            "You explain individual metadata entities to methodology officers and data stewards "
            "in clear, plain language. Be concise (2-4 short paragraphs), neutral and factual. "
            "Do not use markdown tables. Ground every statement in the entity details and "
            "relationships provided; do not invent facts."
        )

    def _build_user_prompt(
        self,
        node: Dict[str, Any],
        relationships: str,
        context: Optional[Dict[str, Any]],
    ) -> str:
        node_type = node.get("type", "")
        parts: List[str] = ["Explain the following metadata entity.", "", self._render_node(node)]
        if relationships:
            parts.append("\nImmediate relationships:\n" + relationships)

        instructions = [
            "In plain language explain: what this entity represents, what process or "
            "transformation produced it, and which quality dimensions or classifications apply.",
        ]
        if node_type == "ProcessStep":
            instructions.append(
                "This is a Process Step: describe the methodological choices made at this step, "
                "including any classification or code list applied and how inputs are transformed "
                "into the output."
            )
        if context:
            instructions.append(self._render_impact_instruction(context))

        parts.append("\n" + " ".join(instructions))
        return "\n".join(parts)

    @staticmethod
    def _render_impact_instruction(context: Dict[str, Any]) -> str:
        classification = context.get("classification_name") or context.get("changed_name") or "a classification"
        before = context.get("version_before")
        after = context.get("version_after")
        change_type = context.get("change_type", "breaking")
        rel_path = context.get("relationship_path") or context.get("path")
        version_clause = ""
        if before or after:
            version_clause = f" (version {before or '?'} → {after or '?'})"
        path_clause = f" It is affected via: {rel_path}." if rel_path else ""
        return (
            f"A {change_type} version change has occurred on {classification}{version_clause}."
            f"{path_clause} Explain specifically what attribute or mapping on THIS entity must be "
            "reviewed or updated as a result of the change, and how urgent it is."
        )

    def _render_node(self, node: Dict[str, Any]) -> str:
        lines = [
            f"Entity type: {node.get('type', '')}",
            f"Name: {node.get('name', '')}",
        ]
        if node.get("summary"):
            lines.append(f"Summary: {node['summary']}")
        if node.get("description"):
            lines.append(f"Description: {node['description']}")
        if node.get("subtypes"):
            lines.append(f"Subtypes: {', '.join(node['subtypes'])}")
        if node.get("tags"):
            lines.append(f"Tags: {', '.join(node['tags'])}")
        interesting = {
            k: v for k, v in (node.get("metadata") or {}).items()
            if k not in _NOISE_METADATA_KEYS
        }
        if interesting:
            lines.append("Metadata: " + json.dumps(interesting, default=str)[:1500])
        return "\n".join(lines)

    @staticmethod
    def _summarize_relationships(node_id: str, related: Dict[str, Any]) -> str:
        nodes = {n["id"]: n for n in related.get("nodes", [])}
        lines: List[str] = []
        for edge in related.get("edges", []):
            src, tgt, rel = edge.get("source"), edge.get("target"), edge.get("type", "RELATES_TO")
            if src == node_id and tgt in nodes:
                other = nodes[tgt]
                lines.append(f"  → {rel} → {other.get('type', '')}: {other.get('name', '')}")
            elif tgt == node_id and src in nodes:
                other = nodes[src]
                lines.append(f"  ← {rel} ← {other.get('type', '')}: {other.get('name', '')}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Deterministic fallback (no LLM configured)
    # ------------------------------------------------------------------

    def _fallback_explanation(
        self,
        node: Dict[str, Any],
        relationships: str,
        context: Optional[Dict[str, Any]],
    ) -> str:
        node_type = node.get("type", "entity")
        name = node.get("name", "This entity")
        parts = [f"{name} is a {node_type}."]
        if node.get("description"):
            parts.append(node["description"])
        elif node.get("summary"):
            parts.append(node["summary"])

        if node_type == "ProcessStep":
            meta = node.get("metadata") or {}
            applied = meta.get("classification_applied")
            transformation = meta.get("transformation")
            if transformation:
                parts.append(f"Methodological transformation: {transformation}")
            if applied:
                applied_text = ", ".join(applied) if isinstance(applied, list) else str(applied)
                parts.append(f"Classifications/code lists applied: {applied_text}.")

        if relationships:
            parts.append("It is directly connected to:\n" + relationships)

        if context:
            classification = context.get("classification_name") or "the classification"
            change_type = context.get("change_type", "breaking")
            rel_path = context.get("relationship_path") or context.get("path")
            review = (
                f"Because {classification} changed ({change_type}), review how this entity maps to "
                f"the updated codes"
            )
            if rel_path:
                review += f" along: {rel_path}"
            parts.append(review + ".")

        parts.append("(LLM not configured — this is a templated explanation generated from the graph.)")
        return "\n\n".join(parts)
