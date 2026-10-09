"""Tests for Phase 6.4b: graph provenance."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))


def test_edge_provenance():
    """Edges have provenance labels."""
    from backend.knowledge_graph import build_knowledge_graph

    memories = [
        {"id": "1", "content": "Python is great for data science", "kind": "semantic"},
        {"id": "2", "content": "Data science uses Python libraries", "kind": "semantic"},
    ]
    result = build_knowledge_graph(memories=memories)

    # Check edges have provenance
    for edge in result["edges"]:
        assert "provenance" in edge
        assert edge["provenance"] in ("EXTRACTED", "INFERRED", "AMBIGUOUS")
        assert "source" in edge


def test_memory_wings():
    """Memories are grouped into wings by kind."""
    from backend.knowledge_graph import build_knowledge_graph

    memories = [
        {"id": "1", "content": "Test", "kind": "episodic"},
        {"id": "2", "content": "Test2", "kind": "semantic"},
    ]
    result = build_knowledge_graph(memories=memories)

    wings = [n for n in result["nodes"] if n["type"] == "wing"]
    assert len(wings) == 2  # episodic and semantic

    # Wings should have contains edges
    wing_edges = [e for e in result["edges"] if e["type"] == "contains"]
    assert len(wing_edges) == 2


def test_answer_provenance():
    """Answer provenance tracks used nodes."""
    from backend.graph_provenance import AnswerProvenance

    prov = AnswerProvenance()
    prov.mark_used("mem:1", "memory", "Test memory", "relevant to query")
    prov.mark_used("mem:1", "memory", "Test memory", "duplicate")  # Should not duplicate

    result = prov.to_dict()
    assert result["count"] == 1
    assert result["used_nodes"][0]["id"] == "mem:1"
