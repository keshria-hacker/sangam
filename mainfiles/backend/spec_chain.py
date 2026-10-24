"""
spec_chain.py — spec-kit artifact chain (deep-read refinement, Wave 1).

Replaces ``spec_wizard.py`` (retired: one 46-line template, no stored
artifact, whole-spec single-prompt dispatch, TDD as a prompt sentence).

The chain is a pipeline of *persisted documents*, each stage's output
being the next stage's input, with structural validation in code — not
in prompts:

  constitution -> spec -> clarify -> plan -> tasks -> implement
  -> analyze -> converge

* constitution: principles / non-goals the plan must satisfy.
* spec: independently-testable stories with Given/When/Then acceptance
  scenarios, numbered functional requirements (FR-001, ...), and
  ``[NEEDS CLARIFICATION]`` markers for anything unknowable yet.
* clarify: at most 5 questions; answers are written back into the
  stored spec (markers resolved, not answered in a side channel).
* plan: research resolves every remaining marker; data model,
  contracts, quickstart; stops before code.
* tasks: sequential T-ids, ``[P]`` only when parallel-safe (no shared
  file paths with any other task), exact file paths, each task naming
  the FRs it covers.
* implement: per-task real agent runs (see pipeline_agents) with tests
  recorded in the ledger; a failing task halts the chain (enforced in
  the route layer, not by prompt).
* analyze: spec x plan x tasks coverage map; every FR is mapped to
  tasks or marked UNCOVERED.
* converge: the spec-vs-output gap becomes new tasks, one per
  uncovered FR.

Pure helpers here are importable without a database. The SQLAlchemy
tables at the bottom persist chain artifacts, per-task run ledger rows,
review packages, and reviewer verdicts; importing this module
registers them on Base.metadata (Batch 2/4 precedent).
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import Base

CHAIN_STAGES = ["constitution", "spec", "clarify", "plan", "tasks",
                "implement", "analyze", "converge"]
MAX_CLARIFICATIONS = 5
MAX_FIX_ROUNDS = 5

_FR_RE = re.compile(r"FR-(\d{3})")
_TASK_RE = re.compile(r"^-\s*\[ \]\s*(T\d+)\s*(\[P\])?\s*(.*)$", re.MULTILINE)
_MARKER_RE = re.compile(r"\[NEEDS CLARIFICATION[^\]]*\]")


# --------------------------------------------------------------------- spec
def render_spec(title: str, problem: str,
                stories: list[dict], requirements: list[str]) -> str:
    """Render a spec-kit spec: stories + numbered FRs + markers.

    stories: [{title, priority ("P0".."P2"), given, when, then}]
    requirements: free-text FRs; markers may be embedded verbatim.
    """
    lines = [f"# {title}", "", "## Problem", problem or "_Not specified_", "",
             "## User stories"]
    for i, s in enumerate(stories, 1):
        lines += [f"### Story S{i} (priority: {s.get('priority', 'P1')})",
                  str(s.get("title", "")),
                  f"- Given {s.get('given', '')}",
                  f"- When {s.get('when', '')}",
                  f"- Then {s.get('then', '')}", ""]
    if not stories:
        lines.append("_None_")
    lines += ["", "## Functional requirements"]
    for i, req in enumerate(requirements, 1):
        lines.append(f"- FR-{i:03d}: {req}")
    if not requirements:
        lines.append("- _None_")
    return "\n".join(lines) + "\n"


def build_spec(title: str, problem: str, goals: list[str],
               constraints: list[str], plan: list[str],
               tasks: list[str]) -> str:
    """Back-compat shape for the retired wizard's inputs, rendered as a
    spec-kit spec instead of the old flat template.

    Goals become P1 stories (one acceptance scenario each, marked for
    clarification where no scenario is given); constraints and plan
    lines become FRs; tasks become the task list seed. The structured
    renderers above are the primary path; this exists only so the
    /spec/build endpoint keeps its input contract.
    """
    stories = [{"title": g, "priority": "P1",
                "given": "the user requests this goal",
                "when": "the feature runs",
                "then": "[NEEDS CLARIFICATION] acceptance scenario for this goal"}
               for g in (goals or [])]
    requirements = [f"Goal: {g}" for g in (goals or [])]
    requirements += [f"Constraint: {c}" for c in (constraints or [])]
    requirements += [f"Plan step: {p}" for p in (plan or [])]
    spec = render_spec(title, problem, stories, requirements)
    if tasks:
        spec += "\n## Task seed (refine via the tasks stage)\n"
        spec += "\n".join(f"- [ ] {t}" for t in tasks) + "\n"
    return spec


def spec_frs(spec: str) -> list[str]:
    return sorted({f"FR-{n}" for n in _FR_RE.findall(spec or "")})


def spec_markers(spec: str) -> list[str]:
    return sorted(set(_MARKER_RE.findall(spec or "")))


def validate_spec(spec: str) -> None:
    """Raise ValueError unless the spec is structurally spec-kit shaped."""
    text = spec or ""
    if "Story S" not in text:
        raise ValueError("spec requires at least one user story ('Story S<n>')")
    if not _FR_RE.search(text):
        raise ValueError("spec requires at least one numbered requirement (FR-001, ...)")
    for block in re.split(r"### Story S\d+", text)[1:]:
        story = block.split("### Story S")[0]
        for kw in ("Given", "When", "Then"):
            if kw not in story:
                raise ValueError(
                    f"spec story is missing a Given/When/Then scenario ('{kw}')")


def apply_clarifications(spec: str,
                         clarifications: list[dict]) -> str:
    """Write clarifications back into the spec. At most 5.

    Each clarification is {question, answer}. If ``question`` matches a
    ``[NEEDS CLARIFICATION ...]`` marker substring in the spec, that
    marker is replaced by the answer; every clarification is also
    appended under a 'Clarifications' section so the write-back is
    auditable. Raises ValueError on >5 or empty answers.
    """
    if not clarifications:
        raise ValueError("clarify requires at least one question/answer")
    if len(clarifications) > MAX_CLARIFICATIONS:
        raise ValueError(
            f"clarify allows at most {MAX_CLARIFICATIONS} questions, "
            f"got {len(clarifications)}")
    out = spec or ""
    lines = ["", "## Clarifications (written back into this spec)"]
    for i, c in enumerate(clarifications, 1):
        q, a = (c.get("question") or "").strip(), (c.get("answer") or "").strip()
        if not q or not a:
            raise ValueError(f"clarification {i} requires a question and an answer")
        if q in out:
            out = out.replace(q, f"[CLARIFIED: {a}]", 1)
        # The appendix records the Q&A without re-printing the raw
        # marker token, so a resolved marker is genuinely gone.
        q_clean = _MARKER_RE.sub("(clarification resolved)", q)
        lines.append(f"- Q{i}: {q_clean}")
        lines.append(f"  A{i}: {a}")
    return out.rstrip() + "\n" + "\n".join(lines) + "\n"


# --------------------------------------------------------------------- plan
def render_plan(research: str, data_model: str, contracts: str,
                quickstart: str) -> str:
    return (
        "# Plan\n\n## Research\n" + (research or "_None_") +
        "\n\n## Data model\n" + (data_model or "_None_") +
        "\n\n## Contracts\n" + (contracts or "_None_") +
        "\n\n## Quickstart\n" + (quickstart or "_None_") + "\n"
    )


def validate_plan(plan: str, spec: str) -> None:
    """A plan must carry all four sections and resolve every marker
    left in the (clarified) spec. It stops before code: a plan that
    already contains an implementation diff is rejected."""
    text = plan or ""
    for section in ("## Research", "## Data model", "## Contracts", "## Quickstart"):
        if section not in text:
            raise ValueError(f"plan requires section '{section}'")
    for marker in spec_markers(spec):
        # A marker counts as resolved only if the research section names
        # its distinguishing text (first 24 chars inside the brackets).
        inner = marker.strip("[]")
        key = inner.replace("NEEDS CLARIFICATION", "").strip(" :")[:24].strip()
        research = text.split("## Data model")[0]
        if key and key not in research and marker not in research:
            raise ValueError(
                f"plan research does not resolve marker '{marker}'")
    if "\n--- a/" in text or "\n+++ b/" in text:
        raise ValueError("plan stops before code: it must not contain a code diff")


# -------------------------------------------------------------------- tasks
def render_tasks(items: list[dict]) -> str:
    """items: [{title, files:[...], parallel: bool, covers:[FR ids]}]."""
    lines = ["# Tasks"]
    for i, item in enumerate(items, 1):
        p = " [P]" if item.get("parallel") else ""
        files = ", ".join(item.get("files") or [])
        covers = ", ".join(item.get("covers") or [])
        line = f"- [ ] T{i}{p} {item.get('title', '')} — files: {files}"
        if covers:
            line += f" — covers: {covers}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def parse_tasks(tasks_text: str) -> list[dict]:
    out = []
    for m in _TASK_RE.finditer(tasks_text or ""):
        tid, parallel, rest = m.group(1), bool(m.group(2)), m.group(3)
        files: list[str] = []
        fm = re.search(r"files:\s*([^\n—]+)", rest)
        if fm:
            files = [f.strip() for f in fm.group(1).split(",") if f.strip()]
        covers: list[str] = []
        cm = re.search(r"covers:\s*([^\n]+)", rest)
        if cm:
            covers = sorted({f"FR-{n}" for n in _FR_RE.findall(cm.group(1))})
        title = re.split(r"\s—\s", rest)[0].strip()
        out.append({"id": tid, "parallel": parallel, "title": title,
                    "files": files, "covers": covers})
    return out


def validate_tasks(tasks_text: str) -> list[dict]:
    """Sequential T-ids, exact file paths, [P] only when parallel-safe
    (no shared file path with any other task). Returns parsed tasks."""
    tasks = parse_tasks(tasks_text or "")
    if not tasks:
        raise ValueError("tasks stage requires at least one T-id task line")
    for i, t in enumerate(tasks, 1):
        if t["id"] != f"T{i}":
            raise ValueError(
                f"tasks must use sequential T-ids: expected T{i}, got {t['id']}")
        if not t["files"]:
            raise ValueError(f"task {t['id']} requires at least one exact file path")
    seen: dict[str, str] = {}
    for t in tasks:
        if not t["parallel"]:
            continue
        for f in t["files"]:
            if f in seen:
                raise ValueError(
                    f"task {t['id']} is marked [P] but shares file '{f}' "
                    f"with task {seen[f]}: [P] is only for parallel-safe tasks")
            seen[f] = t["id"]
    return tasks


# ------------------------------------------------------------ analyze/converge
def analyze_coverage(spec: str, tasks_text: str) -> str:
    """Spec x tasks coverage map: every FR mapped or UNCOVERED."""
    tasks = parse_tasks(tasks_text or "")
    lines = ["# Coverage analysis"]
    for fr in spec_frs(spec):
        covering = sorted(t["id"] for t in tasks if fr in t["covers"])
        if covering:
            lines.append(f"- {fr}: covered by {', '.join(covering)}")
        else:
            lines.append(f"- {fr}: UNCOVERED")
    return "\n".join(lines) + "\n"


def uncovered_frs(analysis_text: str) -> list[str]:
    out = []
    for line in (analysis_text or "").splitlines():
        m = re.search(r"(FR-\d{3}):\s*UNCOVERED", line)
        if m:
            out.append(m.group(1))
    return sorted(set(out))


def validate_analysis(spec: str, analysis_text: str) -> None:
    for fr in spec_frs(spec):
        if fr not in (analysis_text or ""):
            raise ValueError(f"analysis must map requirement {fr} (or mark UNCOVERED)")


def validate_converge(analysis_text: str, converge_text: str) -> None:
    """Converge must turn every uncovered FR into a new task."""
    tasks = parse_tasks(converge_text or "")
    for fr in uncovered_frs(analysis_text):
        if not any(fr in t["covers"] or fr in t["title"] for t in tasks):
            raise ValueError(
                f"converge requires a new task covering uncovered {fr}")


def task_briefs(spec: str, tasks_text: str) -> list[dict]:
    """Per-task briefs: each brief carries ONLY its own task plus the
    FRs it covers — never a whole-spec dump into one agent prompt
    (the retired spec_to_agent_task failure mode)."""
    tasks = validate_tasks(tasks_text)
    fr_lines = {}
    for line in (spec or "").splitlines():
        m = _FR_RE.search(line)
        if m:
            fr_lines[f"FR-{m.group(1)}"] = line.strip()
    briefs = []
    for t in tasks:
        fr_text = "\n".join(fr_lines.get(fr, fr) for fr in t["covers"])
        briefs.append({
            "task_id": t["id"],
            "parallel": t["parallel"],
            "files": t["files"],
            "brief": (
                f"Implement task {t['id']}: {t['title']}\n"
                f"Files: {', '.join(t['files'])}\n"
                f"Requirements:\n{fr_text or '(no FRs listed)'}\n"
                "TDD: write a failing test first, then implement until it "
                "passes. Do not touch files outside the list above."
            ),
        })
    return briefs


def spec_to_agent_task(spec: str, tasks_text: str = "") -> str:
    """Retired whole-spec dispatch, kept only as a loud failure: the
    chain dispatches per-task briefs (task_briefs), never one prompt
    carrying the entire spec. Callers must migrate."""
    raise NotImplementedError(
        "Whole-spec single-prompt dispatch is retired with spec_wizard. "
        "Use task_briefs(spec, tasks) and run one agent per task.")


def sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------- tables
class SpecChainArtifact(Base):
    __tablename__ = "spec_chain_artifacts"

    id = Column(String, primary_key=True)
    pipeline_id = Column(String, ForeignKey("engineering_pipelines.id"), nullable=False)
    stage = Column(String, nullable=False)
    artifact = Column(Text, nullable=False, default="")
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class PipelineTaskRun(Base):
    """Per-task agent-run ledger: real run, real diff, test evidence.

    A row is written for every task run attempt. The chain may advance
    past implement only when the LATEST row per task has
    test_passed=True. Rows are append-only; a fix round appends a new
    row with a higher ``fix_round`` instead of overwriting history.
    """
    __tablename__ = "pipeline_task_runs"

    id = Column(String, primary_key=True)
    pipeline_id = Column(String, ForeignKey("engineering_pipelines.id"), nullable=False)
    task_id = Column(String, nullable=False)
    brief = Column(Text, nullable=False, default="")
    agent_source = Column(String, nullable=False, default="agent")  # agent|mock
    diff = Column(Text, nullable=False, default="")
    test_command = Column(String, nullable=False, default="")
    test_passed = Column(Integer, nullable=False, default=0)  # 0/1
    test_output = Column(Text, nullable=False, default="")
    fix_round = Column(Integer, nullable=False, default=0)
    fresh_context = Column(Integer, nullable=False, default=0)  # 0/1
    error = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class ReviewPackage(Base):
    """BASE/HEAD diff package for two-stage review.

    base_ref hashes the pre-implement snapshot (the tasks artifact);
    head_ref hashes the concatenated per-task diffs. Reviews must
    reference this package id; pasted text alone never satisfies finish.
    """
    __tablename__ = "pipeline_review_packages"

    id = Column(String, primary_key=True)
    pipeline_id = Column(String, ForeignKey("engineering_pipelines.id"), nullable=False)
    base_ref = Column(String, nullable=False, default="")
    head_ref = Column(String, nullable=False, default="")
    diff = Column(Text, nullable=False, default="")
    fix_rounds = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class ChainReview(Base):
    __tablename__ = "pipeline_chain_reviews"

    id = Column(String, primary_key=True)
    pipeline_id = Column(String, ForeignKey("engineering_pipelines.id"), nullable=False)
    axis = Column(String, nullable=False)  # spec | quality
    verdict = Column(String, nullable=False)  # pass | fail
    review_package_id = Column(String, nullable=False)
    artifact = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


def new_chain_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


async def list_chain(db: AsyncSession, pipeline_id: str) -> list[SpecChainArtifact]:
    rows = await db.execute(
        select(SpecChainArtifact).where(
            SpecChainArtifact.pipeline_id == pipeline_id
        ).order_by(SpecChainArtifact.position))
    return list(rows.scalars().all())


async def list_task_runs(db: AsyncSession, pipeline_id: str) -> list[PipelineTaskRun]:
    rows = await db.execute(
        select(PipelineTaskRun).where(
            PipelineTaskRun.pipeline_id == pipeline_id
        ).order_by(PipelineTaskRun.created_at))
    return list(rows.scalars().all())


async def list_reviews(db: AsyncSession, pipeline_id: str) -> list[ChainReview]:
    rows = await db.execute(
        select(ChainReview).where(
            ChainReview.pipeline_id == pipeline_id
        ).order_by(ChainReview.created_at))
    return list(rows.scalars().all())


async def latest_package(db: AsyncSession, pipeline_id: str) -> ReviewPackage | None:
    rows = await db.execute(
        select(ReviewPackage).where(
            ReviewPackage.pipeline_id == pipeline_id
        ).order_by(ReviewPackage.created_at.desc()))
    return rows.scalars().first()


def chain_out(chain: list[SpecChainArtifact],
              runs: list[PipelineTaskRun],
              packages: list[ReviewPackage],
              reviews: list[ChainReview]) -> dict:
    current = chain[-1].stage if chain else None
    finished = any(c.stage == "finish" for c in chain)
    return {
        "current_stage": current,
        "finished": finished,
        "stages": [{"id": c.id, "stage": c.stage, "artifact": c.artifact}
                   for c in chain],
        "task_runs": [{"id": r.id, "task_id": r.task_id,
                       "agent_source": r.agent_source,
                       "test_passed": bool(r.test_passed),
                       "test_command": r.test_command,
                       "fix_round": r.fix_round,
                       "fresh_context": bool(r.fresh_context),
                       "diff": r.diff, "error": r.error} for r in runs],
        "review_packages": [{"id": p.id, "base_ref": p.base_ref,
                             "head_ref": p.head_ref, "diff": p.diff,
                             "fix_rounds": p.fix_rounds} for p in packages],
        "reviews": [{"id": v.id, "axis": v.axis, "verdict": v.verdict,
                     "review_package_id": v.review_package_id,
                     "artifact": v.artifact} for v in reviews],
    }


async def advance_chain(db: AsyncSession, pipeline_id: str, stage: str,
                        artifact: str = "",
                        clarifications: list[dict] | None = None) -> SpecChainArtifact:
    """Advance the spec chain one stage, in order. Raises ValueError
    (route maps to 422) on ordering or structural violations.

    Implement/analyze/converge additionally enforce ledger state:
    implement requires every parsed task to have a latest ledger row
    with test_passed=True (a failing implement stage halts the chain);
    analyze requires a coverage map over the spec's FRs; converge
    requires a new task per uncovered FR.
    """
    chain = await list_chain(db, pipeline_id)
    stages = [c.stage for c in chain]
    if "finish" in stages:
        raise ValueError("Spec chain is already finished")
    expected = CHAIN_STAGES[len([s for s in stages if s in CHAIN_STAGES])] \
        if len([s for s in stages if s in CHAIN_STAGES]) < len(CHAIN_STAGES) else None
    if expected is None:
        raise ValueError("Spec chain stages are complete; use chain finish")
    if stage != expected:
        raise ValueError(
            f"Out of order: next chain stage is '{expected}', not '{stage}'")
    by_stage = {c.stage: c for c in chain}

    if stage == "constitution":
        if not (artifact or "").strip() or not re.search(
                r"(?m)^\s*(?:#+\s+|-\s+|\d+\.\s+).*?[Pp]rinciple\b", artifact):
            raise ValueError(
                "constitution requires at least one Principle line")
    elif stage == "spec":
        validate_spec(artifact)
    elif stage == "clarify":
        if not clarifications:
            raise ValueError(
                "clarify requires clarifications [{question, answer}] "
                "(at most 5); answers are written back into the spec")
        spec_row = by_stage.get("spec")
        if spec_row is None:
            raise ValueError("clarify requires a stored spec stage")
        updated = apply_clarifications(spec_row.artifact, clarifications)
        spec_row.artifact = updated
        await db.commit()
        artifact = artifact or (
            "Clarifications written back into the spec:\n" +
            "\n".join(f"- {c.get('question')}: {c.get('answer')}"
                      for c in clarifications))
    elif stage == "plan":
        spec_row = by_stage.get("spec")
        if spec_row is None:
            raise ValueError("plan requires a stored spec stage")
        validate_plan(artifact, spec_row.artifact)
    elif stage == "tasks":
        validate_tasks(artifact)
    elif stage == "implement":
        tasks_row = by_stage.get("tasks")
        if tasks_row is None:
            raise ValueError("implement requires a stored tasks stage")
        tasks = parse_tasks(tasks_row.artifact)
        runs = await list_task_runs(db, pipeline_id)
        latest: dict[str, PipelineTaskRun] = {}
        for r in runs:
            latest[r.task_id] = r
        missing = [t["id"] for t in tasks if t["id"] not in latest]
        if missing:
            raise ValueError(
                f"implement halted: tasks not yet run: {', '.join(missing)}")
        failed = [t["id"] for t in tasks if not latest[t["id"]].test_passed]
        if failed:
            raise ValueError(
                f"implement halted: failing tasks (tests did not pass): "
                f"{', '.join(failed)}")
        if not (artifact or "").strip():
            raise ValueError("implement requires a summary artifact")
    elif stage == "analyze":
        spec_row = by_stage.get("spec")
        if spec_row is None:
            raise ValueError("analyze requires a stored spec stage")
        validate_analysis(spec_row.artifact, artifact)
    elif stage == "converge":
        analysis_row = by_stage.get("analyze")
        if analysis_row is None:
            raise ValueError("converge requires a stored analysis stage")
        validate_converge(analysis_row.artifact, artifact)

    row = SpecChainArtifact(
        id=new_chain_id("chain"), pipeline_id=pipeline_id, stage=stage,
        artifact=artifact or "", position=len(chain))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row
