"""
graph_provenance.py — track which knowledge graph nodes were used in an answer.

When the agent or chat uses context from the knowledge graph, record the
node IDs so the UI can show a "used in this answer" panel.
"""
from __future__ import annotations

from typing import Any


class AnswerProvenance:
    """Tracks graph nodes used during answer generation."""

    def __init__(self):
        self.used_nodes: list[dict[str, Any]] = []

    def mark_used(self, node_id: str, node_type: str, label: str, reason: str = ""):
        """Mark a node as used in the current answer."""
        if not any(n["id"] == node_id for n in self.used_nodes):
            self.used_nodes.append({
                "id": node_id,
                "type": node_type,
                "label": label[:80],
                "reason": reason,
            })

    def to_dict(self) -> dict[str, Any]:
        return {
            "used_nodes": self.used_nodes,
            "count": len(self.used_nodes),
        }

    def clear(self):
        self.used_nodes.clear()


# Thread-local storage for the current answer's provenance
import threading
_local = threading.local()


def get_current_provenance() -> AnswerProvenance:
    """Get the provenance tracker for the current request."""
    if not hasattr(_local, 'provenance'):
        _local.provenance = AnswerProvenance()
    return _local.provenance


def clear_current_provenance():
    """Clear the provenance tracker (call at start of new request)."""
    if hasattr(_local, 'provenance'):
        _local.provenance.clear()
