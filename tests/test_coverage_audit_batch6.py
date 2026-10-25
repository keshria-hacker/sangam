"""
Batch 6 (coverage audit) tests.

Covers only what Batch 6 itself added or corrected:
- the three Batch 11 "catalogue entry" claims (imajev, Vane,
  Open-Generative-AI) are now real, searchable catalogue rows of kind
  "reference_note" — documented rows only, no model run, no install;
- the spec-kit audit correction: spec_wizard.py is retired (absent)
  while its replacement, spec_chain.py, exists;
- the definitive coverage table in docs/ALL_IN_ONE_COVERAGE.md
  accounts for exactly 85 repos, one row each, with no row left
  unclassified.

No live model, no live network.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

from backend.research import catalogue as catalogue_mod  # noqa: E402


def test_batch6_reference_notes_exist_and_are_searchable():
    rows = catalogue_mod.search_catalogue(kind="reference_note")
    by_id = {r["id"]: r for r in rows}
    assert set(by_id) == {"ref-imajev", "ref-vane", "ref-open-generative-ai"}
    for row in rows:
        # A reference note must say what Sangam does instead and what
        # it does NOT do; it must never promise an install or a run.
        assert row["sangam_equivalent"]
        assert row["risk"]
        assert "not installed" in row["install"].lower()


def test_batch6_reference_notes_found_by_name_search():
    assert any(r["id"] == "ref-imajev" for r in catalogue_mod.search_catalogue(q="imajev"))
    assert any(r["id"] == "ref-vane" for r in catalogue_mod.search_catalogue(q="Vane"))
    assert any(
        r["id"] == "ref-open-generative-ai"
        for r in catalogue_mod.search_catalogue(q="Generative")
    )


def test_batch6_catalogue_still_deduped():
    rows = catalogue_mod.catalogue_entries()
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids))


def test_batch6_spec_wizard_retired_spec_chain_present():
    backend = _ROOT / "mainfiles" / "backend"
    assert not (backend / "spec_wizard.py").exists(), (
        "spec_wizard.py must stay retired; spec-kit is covered by spec_chain.py"
    )
    assert (backend / "spec_chain.py").exists()


def test_batch6_coverage_table_accounts_for_85_repos():
    doc = (_ROOT / "docs" / "ALL_IN_ONE_COVERAGE.md").read_text()
    section = doc[doc.index("## Definitive table"):]
    rows = [
        line
        for line in section.splitlines()
        if re.match(r"\| \d+ \|", line)
    ]
    assert len(rows) == 85, f"expected 85 coverage rows, found {len(rows)}"
    for line in rows:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        assert cells[2] in ("shipped", "native-equivalent", "excluded"), line
        assert cells[3], f"row without evidence: {line}"
    shipped = sum(1 for r in rows if "| shipped |" in r)
    native = sum(1 for r in rows if "| native-equivalent |" in r)
    excluded = sum(1 for r in rows if "| excluded |" in r)
    assert shipped + native + excluded == 85
    assert shipped == 58 and native == 22 and excluded == 5
