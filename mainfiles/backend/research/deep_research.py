"""
research/deep_research.py — Batch 9: research job state machine
(gpt-researcher-inspired loop, Sangam-native, no live model required).

State machine (mirrored into the Runs centre on completion):

  planned -> searching -> curating -> compressing -> writing -> done
  (any step may go to ``failed`` with an error message)

- Planner: deterministic query templates from the question (breadth
  N). This is a template planner, documented as such — it never
  pretends an LLM planned the queries.
- Breadth/depth recursion: each breadth query is searched; each
  depth level derives follow-up queries from retrieved learnings
  (keyword extractor by default; injectable for tests). Depth and
  query counts are capped, queries are deduped, recursion always
  terminates.
- Curator: sources are scored (retrieved text + URL + snippet
  length) and ranked — cited, retrieved sources outrank bare
  search-result stubs.
- Compression: learnings are trimmed to a word budget, lowest
  curator score first, without dropping citation ids.
- Report writer ("no evidence, no claim" — the research analogue of
  shannon's "no exploit, no report"): every claim must cite a
  retrieved source id; an uncited claim raises UncitedClaimError
  and the route answers 422. The writer never invents citations.

``search_fn`` / ``fetch_fn`` / ``followup_fn`` are injectable so
tests run with fakes and no network. The route defaults wire them
to ``backend.websearch.web_search`` and ``backend.ingest_url``.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy import DateTime, Integer, String, Text, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base

JOB_STATES = ("planned", "searching", "curating", "compressing",
              "writing", "done", "failed")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "what", "how", "why", "when", "which",
    "this", "that", "from", "by", "about", "into", "over", "under",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return f"rj-{uuid.uuid4().hex[:12]}"


class UncitedClaimError(ValueError):
    """A report claim cites no retrieved source."""


class ResearchJob(Base):
    """One deep-research run. Tables live here, following the Batch 4
    precedent: importing the route module registers this table."""

    __tablename__ = "research_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    notebook_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    breadth: Mapped[int] = mapped_column(Integer, default=4)
    depth: Mapped[int] = mapped_column(Integer, default=2)
    word_budget: Mapped[int] = mapped_column(Integer, default=2000)
    status: Mapped[str] = mapped_column(String(16), default="planned")
    plan_json: Mapped[str] = mapped_column(Text, default="[]")
    queries_json: Mapped[str] = mapped_column(Text, default="[]")
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    learnings_json: Mapped[str] = mapped_column(Text, default="[]")
    report_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations_json: Mapped[str] = mapped_column(Text, default="[]")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


def research_job_out(row: ResearchJob) -> dict:
    return {
        "id": row.id, "notebook_id": row.notebook_id,
        "question": row.question, "breadth": row.breadth,
        "depth": row.depth, "word_budget": row.word_budget,
        "status": row.status, "error": row.error,
        "plan": json.loads(row.plan_json or "[]"),
        "queries": json.loads(row.queries_json or "[]"),
        "sources": json.loads(row.sources_json or "[]"),
        "learnings": json.loads(row.learnings_json or "[]"),
        "report": row.report_md,
        "citations": json.loads(row.citations_json or "[]"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ---------------------------------------------------------------- planner

def plan_queries(question: str, breadth: int) -> list[str]:
    """Deterministic breadth queries. The first is always the question
    verbatim; the rest are template variants (evidence / comparison /
    background angles). Template planner — no LLM involved."""
    question = (question or "").strip()
    if not question:
        raise ValueError("question must not be empty")
    breadth = min(max(1, breadth), 8)
    variants = [
        question,
        f"{question} evidence",
        f"{question} overview",
        f"{question} comparison",
        f"{question} examples",
        f"{question} limitations",
        f"{question} best practices",
        f"{question} recent developments",
    ]
    return variants[:breadth]


def _keywords(text: str, limit: int = 4) -> list[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    seen: list[str] = []
    for word in words:
        if word not in _STOPWORDS and len(word) > 2 and word not in seen:
            seen.append(word)
    return seen[:limit]


def default_followups(question: str, learnings: list[dict]) -> list[str]:
    """Keyword follow-ups: top keywords from learnings not already in
    the question, one query per learning batch. Deterministic."""
    base = set(_keywords(question, limit=50))
    queries: list[str] = []
    for learning in learnings:
        fresh = [w for w in _keywords(learning.get("text", "")) if w not in base]
        if fresh:
            queries.append(f"{question} {' '.join(fresh[:3])}")
    return queries


# ---------------------------------------------------------------- curator

def curator_score(source: dict) -> float:
    """0.0–1.0. Retrieved full text counts most; a bare search stub
    (URL + snippet only) scores below any retrieved source."""
    score = 0.0
    if source.get("url"):
        score += 0.3
    if source.get("text"):
        score += 0.5
        score += min(0.2, len(source["text"]) / 5000.0)
    return round(min(1.0, score), 3)


def curate_sources(sources: list[dict]) -> list[dict]:
    """Dedupe by URL, score, rank highest first."""
    seen: dict[str, dict] = {}
    for source in sources:
        url = (source.get("url") or "").strip()
        key = url or f"stub-{source.get('title', '')}"
        if key not in seen:
            seen[key] = dict(source)
        elif source.get("text") and not seen[key].get("text"):
            seen[key] = dict(source)
    ranked = sorted(seen.values(), key=curator_score, reverse=True)
    for source in ranked:
        source["curator_score"] = curator_score(source)
    return ranked


# ------------------------------------------------------------- compression

def compress_learnings(learnings: list[dict], word_budget: int) -> list[dict]:
    """Trim to a word budget, lowest curator score first, keeping
    citation ids intact. A learning is never half-cited: trimming
    cuts words, never the ``source_id`` field."""
    budget = max(100, word_budget)
    ordered = sorted(learnings, key=lambda item: item.get("curator_score", 0.0))
    total = sum(len((item.get("text") or "").split()) for item in learnings)
    kept = list(learnings)
    while total > budget and kept:
        victim = min(kept, key=lambda item: item.get("curator_score", 0.0))
        kept.remove(victim)
        total -= len((victim.get("text") or "").split())
    # If one giant learning still busts the budget, trim its words
    # (citation id untouched).
    trimmed = []
    for item in kept:
        words = (item.get("text") or "").split()
        if len(words) > budget:
            item = dict(item, text=" ".join(words[:budget]))
        trimmed.append(item)
    return trimmed


# ------------------------------------------------------------ report writer

def write_report(question: str, learnings: list[dict], claims: list[dict]) -> str:
    """Cited report. Every claim MUST cite at least one source id
    present in ``learnings``; otherwise UncitedClaimError. The report
    body is assembled from learnings, never from model invention —
    there is no model in this path at all."""
    known = {item.get("source_id") for item in learnings}
    for claim in claims:
        cited = [c for c in (claim.get("citations") or []) if c in known]
        if not cited:
            raise UncitedClaimError(
                f"claim cites no retrieved source: {(claim.get('text') or '')[:80]}")
    lines = [f"# Research: {question}", ""]
    if claims:
        lines.append("## Findings")
        lines.append("")
        for claim in claims:
            cites = ", ".join(f"[{c}]" for c in claim.get("citations") or [])
            lines.append(f"- {claim.get('text', '')} {cites}")
        lines.append("")
    lines.append("## Sources")
    lines.append("")
    for item in learnings:
        title = item.get("title") or item.get("source_id") or "source"
        url = item.get("url") or ""
        lines.append(f"- [{item.get('source_id')}] {title} {url}".rstrip())
    lines.append("")
    lines.append("## Evidence notes")
    lines.append("")
    for item in learnings:
        snippet = " ".join((item.get("text") or "").split()[:60])
        lines.append(f"- [{item.get('source_id')}] {snippet}")
    return "\n".join(lines)


# ------------------------------------------------------------- source graph

def source_graph(sources: list[dict]) -> dict:
    """flowsint-pattern sketch, re-scoped: nodes are ONLY the job's
    own retrieved sources; edges are same-domain links and
    mention-links (one source's text naming another's domain). No
    third-party targeting — there is no enricher for people, IPs,
    or breach data anywhere in this module."""
    nodes = []
    for source in sources:
        domain = urlparse(source.get("url") or "").netloc or ""
        nodes.append({"id": source.get("source_id") or source.get("url"),
                      "title": source.get("title", ""),
                      "url": source.get("url", ""), "domain": domain,
                      "curator_score": source.get("curator_score", 0.0)})
    edges: list[dict] = []
    by_domain: dict[str, list[str]] = {}
    for node in nodes:
        if node["domain"]:
            by_domain.setdefault(node["domain"], []).append(node["id"])
    for domain, ids in by_domain.items():
        for other in ids[1:]:
            edges.append({"from": ids[0], "to": other, "type": "same_domain",
                          "label": domain})
    texts = {s.get("source_id"): (s.get("text") or "") for s in sources}
    for node in nodes:
        for other in nodes:
            if other["id"] != node["id"] and other["domain"] \
                    and other["domain"] in (texts.get(node["id"]) or ""):
                edges.append({"from": node["id"], "to": other["id"],
                              "type": "mentions", "label": other["domain"]})
    return {"nodes": nodes, "edges": edges}


# ------------------------------------------------------------ slide outline

def report_to_slides(report_md: str, citations: list[str]) -> dict:
    """Guarded OpenMAIC-style transform: report sections become a
    slide/lesson outline through a schema, not free text. Slides
    carry ONLY citations from the report; unknown citations are
    dropped, never invented. No video is produced anywhere here."""
    sections: list[dict] = []
    current: dict | None = None
    for line in (report_md or "").splitlines():
        if line.startswith("## "):
            current = {"title": line[3:].strip(), "bullets": [], "sources": []}
            sections.append(current)
        elif line.startswith("- ") and current is not None:
            current["bullets"].append(line[2:].strip()[:280])
    slides = []
    for section in sections:
        cited = [c for c in re.findall(r"\[([^\]]+)\]", " ".join(section["bullets"]))
                 if c in set(citations)]
        slides.append({"title": section["title"][:120],
                       "bullets": section["bullets"][:6],
                       "sources": cited})
    if not slides:
        slides = [{"title": "Research summary", "bullets": [], "sources": []}]
    return {"format": "slide_outline", "slide_count": len(slides), "slides": slides}


# ------------------------------------------------------------------- runner

async def run_job(
    db: AsyncSession, job: ResearchJob,
    search_fn=None, fetch_fn=None, followup_fn=None,
) -> ResearchJob:
    """Execute the state machine to completion. ``search_fn(query)``
    returns [{title, url, snippet}]; ``fetch_fn(url)`` returns text
    (or raises — failures degrade to snippet-only sources, never a
    job crash). Progress is persisted at every state."""
    async def _set(status: str, **fields: object) -> None:
        job.status = status
        for key, value in fields.items():
            setattr(job, key, value)
        job.updated_at = _now()
        await db.commit()

    try:
        plan = plan_queries(job.question, job.breadth)
        await _set("searching", plan_json=json.dumps(plan))
        queries: list[str] = []
        sources: list[dict] = []
        seen_queries: set[str] = set()

        async def _search(query: str) -> None:
            if query in seen_queries:
                return
            seen_queries.add(query)
            queries.append(query)
            results = await search_fn(query) if search_fn else []
            for result in results or []:
                url = (result.get("url") or "").strip()
                source_id = f"src-{len(sources) + 1}"
                text = ""
                if fetch_fn and url:
                    try:
                        text = await fetch_fn(url) or ""
                    except Exception:  # noqa: BLE001 — snippet-only fallback
                        text = ""
                sources.append({
                    "source_id": source_id, "title": result.get("title", ""),
                    "url": url, "snippet": result.get("snippet", ""),
                    "text": text[:8000],
                })

        for query in plan:
            await _search(query)
        learnings = [{
            "source_id": s["source_id"], "title": s["title"], "url": s["url"],
            "text": (s["text"] or s["snippet"] or "")[:2000],
            "curator_score": curator_score(s),
        } for s in sources]
        for level in range(max(0, job.depth - 1)):
            followups = (followup_fn(job.question, learnings)
                         if followup_fn else default_followups(job.question, learnings))
            if not followups:
                break
            before = len(sources)
            for query in followups[:job.breadth]:
                await _search(query)
            if len(sources) == before:
                break
            learnings = [{
                "source_id": s["source_id"], "title": s["title"], "url": s["url"],
                "text": (s["text"] or s["snippet"] or "")[:2000],
                "curator_score": curator_score(s),
            } for s in sources]
        await _set("curating", queries_json=json.dumps(queries),
                   sources_json=json.dumps(curate_sources(sources)))
        ranked = curate_sources(sources)
        learnings = [{
            "source_id": s["source_id"], "title": s["title"], "url": s["url"],
            "text": (s["text"] or s["snippet"] or "")[:2000],
            "curator_score": s.get("curator_score", 0.0),
        } for s in ranked]
        await _set("compressing", learnings_json=json.dumps(learnings))
        compressed = compress_learnings(learnings, job.word_budget)
        await _set("writing", learnings_json=json.dumps(compressed),
                   citations_json=json.dumps([item["source_id"] for item in compressed]))
        job.status = "done"
        job.updated_at = _now()
        await db.commit()
        await db.refresh(job)
        return job
    except Exception as exc:  # noqa: BLE001 — job failure is a state
        job.status = "failed"
        job.error = str(exc)[:500]
        job.updated_at = _now()
        await db.commit()
        await db.refresh(job)
        return job
