"""
council_mode.py — Council "Deliberate" Teams mode (council-of-high-
intelligence protocol, ported as code, not prose).

Flow: 3-lens panel (Skeptic / Builder / Pragmatist — see
``teams.definitions.COUNCIL_LENSES``; each lens carries a ``method``
field on its AgentSpec) -> Round 1 blind-parallel (each lens sees only
the problem) -> Round 2 anonymized cross-examination (Member A/B/C
labels, each member must name a disagreement AND a strengthening
insight) -> enforcement scan -> Round 3 STANCE lines -> exact
confidence-weighted tally with a 2/3 bar -> verdict template.

Tally arithmetic (council's, exactly):
- base weight 1.0, or 1.5 for the domain seat (locked BEFORE analysis;
  "none" when ambiguous — never picked after votes);
- confidence weight: high 1.0 / med 0.75 / low 0.5;
- denominator = SUM of BASE weights INCLUDING abstainers (abstention
  raises the bar instead of shrinking it);
- consensus iff the winning option's weight >= (2/3) * denominator.
- any DEALBREAKER: yes dissent survives as a Minority Report EVEN
  WHEN OUTVOTED.
- no option clears 2/3 -> NO manufactured consensus: the split is
  returned to the user with weighted tallies + strongest argument per
  option, and the verdict reads "No consensus reached". No further
  mechanical round is run (the round budget is the forcing function).

Stances are NEVER inferred from prose: a member that omits the exact
``STANCE: ... | CONFIDENCE: ... | DEALBREAKER: ...`` line is an
abstainer (recorded as ``missing_stance``), not a guessed vote.

Outcome ledger: predictions are recorded BEFORE acting (prediction,
owner, review date, kill criteria) and later marked confirmed /
revised / reversed / inconclusive. The original prediction is
immutable — marking never rewrites it. The ledger is JSON-file backed
(atomic writes) so it survives restarts; it can also mirror onto the
Runs store via ``mirror_to_runstore`` when a run id is supplied.

This module takes a ``completer`` callable (``async (messages) ->
str``) for LLM calls so tests run it with a fake; it never imports
the LLM layer itself. Reasoning-only: no tool calls, no approval
conflict.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

CONSENSUS_BAR = 2 / 3
CONFIDENCE_WEIGHTS = {"high": 1.0, "med": 0.75, "low": 0.5}
DOMAIN_BASE = 1.5
BASE_WEIGHT = 1.0

STANCE_RE = re.compile(
    r"STANCE:\s*(?P<stance>[^|]+?)\s*\|\s*CONFIDENCE:\s*(?P<confidence>high|med|low)"
    r"\s*\|\s*DEALBREAKER:\s*(?P<dealbreaker>yes|no)",
    re.IGNORECASE,
)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _norm_label(label: str) -> str:
    """Canonicalize a stance label (council's normalization: e.g.
    'single repo' -> 'monorepo' style collapsing is caller-supplied
    via ``label_aliases``; here we just trim + lowercase + collapse
    whitespace so 'Go ' and 'go' are the same option)."""
    return re.sub(r"\s+", " ", (label or "").strip().lower())


@dataclass
class CouncilVote:
    member: str
    stance: str | None  # None = abstainer (incl. missing STANCE line)
    confidence: str = "med"
    dealbreaker: bool = False
    missing_stance: bool = False

    @property
    def weight(self) -> float:
        return CONFIDENCE_WEIGHTS.get(self.confidence, 0.5)


def parse_stance(text: str, member: str) -> CouncilVote:
    """Parse the exact STANCE line. Never infer from prose: no line
    -> abstainer with missing_stance=True."""
    match = STANCE_RE.search(text or "")
    if match is None:
        return CouncilVote(member=member, stance=None, missing_stance=True)
    return CouncilVote(
        member=member,
        stance=_norm_label(match.group("stance")),
        confidence=match.group("confidence").lower(),
        dealbreaker=match.group("dealbreaker").lower() == "yes",
    )


def check_cross_examination(text: str) -> dict[str, bool]:
    """Round-2 discipline: the member must (1) name a member it most
    disagrees with, and (2) name an insight that strengthens it.
    Returns which requirements are met; both False-safe (missing
    text fails both, never passes by default)."""
    body = text or ""
    disagrees = bool(re.search(r"disagree\w*\s+with\s+member\s+[a-z]", body, re.IGNORECASE))
    strengthens = bool(re.search(r"strengthen\w*", body, re.IGNORECASE))
    return {"names_disagreement": disagrees, "names_strengthening_insight": strengthens,
            "ok": disagrees and strengthens}


def anonymize(analyses: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Replace member ids with stable Member A/B/C labels and strip
    self-references ('As Skeptic...' -> 'As Member B...').
    Returns (label -> anonymized text, member -> label)."""
    members = sorted(analyses)
    member_to_label = {m: f"Member {chr(ord('A') + i)}" for i, m in enumerate(members)}
    out: dict[str, str] = {}
    for member, text in analyses.items():
        anon = text or ""
        for other, label in member_to_label.items():
            anon = re.sub(rf"\bAs {re.escape(other)}\b", f"As {label}", anon,
                          flags=re.IGNORECASE)
            anon = re.sub(rf"\b{re.escape(other)}\b", label, anon)
        out[member_to_label[member]] = anon
    return out, member_to_label


@dataclass
class TallyResult:
    totals: dict[str, float]
    denominator: float
    winner: str | None
    consensus: bool
    dealbreakers: list[str]
    votes: list[CouncilVote]
    domain_seat: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"totals": self.totals, "denominator": round(self.denominator, 4),
                "winner": self.winner, "consensus": self.consensus,
                "dealbreakers": self.dealbreakers, "domain_seat": self.domain_seat,
                "votes": [{"member": v.member, "stance": v.stance,
                           "confidence": v.confidence, "dealbreaker": v.dealbreaker,
                           "missing_stance": v.missing_stance} for v in self.votes]}


def tally(votes: list[CouncilVote], domain_seat: str | None = None,
          label_aliases: dict[str, str] | None = None) -> TallyResult:
    """Exact council tally. Abstainers count in the denominator at
    full base weight; dealbreaker dissent is listed even when
    outvoted."""
    aliases = { _norm_label(k): _norm_label(v) for (k, v) in (label_aliases or {}).items() }
    totals: dict[str, float] = {}
    denominator = 0.0
    for vote in votes:
        base = DOMAIN_BASE if vote.member == domain_seat else BASE_WEIGHT
        denominator += base
        if vote.stance is None:
            continue
        stance = aliases.get(vote.stance, vote.stance)
        totals[stance] = totals.get(stance, 0.0) + base * vote.weight
    winner = None
    consensus = False
    if totals:
        winner = max(totals, key=lambda k: (totals[k], k))
        consensus = totals[winner] >= CONSENSUS_BAR * denominator
    dealbreakers = [v.member for v in votes
                    if v.dealbreaker and v.stance is not None
                    and (not consensus or v.stance != winner)]
    # A dealbreaker on the WINNING side under consensus is not a minority
    # report; a dealbreaker dissent always is (even when outvoted).
    if consensus and winner is not None:
        dealbreakers = [v.member for v in votes
                        if v.dealbreaker and v.stance != winner]
    return TallyResult(totals=totals, denominator=denominator, winner=winner,
                       consensus=consensus, dealbreakers=dealbreakers,
                       votes=votes, domain_seat=domain_seat)


def enforcement_scan(round1: dict[str, str], round2: dict[str, str],
                     votes: list[CouncilVote]) -> dict[str, Any]:
    """Post-round enforcement scan (tags only — it reports, it never
    rewrites a vote). Dissent quota: >= 2 members must voice a
    disagreement in Round 2; novelty gate: a Round-2 reply that merely
    restates Round 1; >70% agreement counterfactual flag; missing
    stance re-prompt list."""
    dissenters = [m for m, text in round2.items()
                  if re.search(r"disagree", text or "", re.IGNORECASE)]
    novelty_failures = [m for m, text in round2.items()
                        if (round1.get(m) or "").strip() and (text or "").strip() == (round1[m] or "").strip()]
    total_votes = len(votes) or 1
    top_share = 0.0
    if votes:
        from collections import Counter
        counts = Counter(v.stance for v in votes if v.stance is not None)
        top_share = (max(counts.values()) / total_votes) if counts else 0.0
    return {
        "dissent_quota_met": len(dissenters) >= 2,
        "dissenters": sorted(dissenters),
        "novelty_failures": sorted(novelty_failures),
        "agreement_over_70pct": top_share > 0.70,
        "missing_stance": sorted(v.member for v in votes if v.missing_stance),
    }


def build_verdict(question: str, tally_result: TallyResult,
                  compromises: str = "", kill_criteria: str = "",
                  next_step: str = "", minority_report: str = "",
                  strongest_per_option: dict[str, str] | None = None) -> str:
    """Verdict template. Splits below the bar are surfaced as splits,
    never as consensus."""
    lines = [f"Problem: {question}", "",
             f"Consensus: {'reached' if tally_result.consensus else 'No consensus reached'}"]
    if tally_result.consensus and tally_result.winner:
        lines.append(f"Verdict: {tally_result.winner}")
    else:
        lines.append("Verdict: No consensus reached — the split below is handed back for a human decision.")
    lines.append("")
    lines.append("Vote Tally:")
    for option, weight in sorted(tally_result.totals.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {option}: {weight:.2f} / {tally_result.denominator:.2f}")
    abstainers = [v.member for v in tally_result.votes if v.stance is None]
    if abstainers:
        lines.append(f"- abstained (incl. missing STANCE line): {', '.join(abstainers)}")
    if strongest_per_option:
        lines.append("")
        lines.append("Strongest argument per option:")
        for option, arg in strongest_per_option.items():
            lines.append(f"- {option}: {arg}")
    lines.append("")
    lines.append(f"Acceptable Compromises: {compromises or '(none stated — the verdict gives up nothing explicitly)'}")
    lines.append(f"Kill Criteria: {kill_criteria or '(none stated)'}")
    lines.append(f"Concrete Next Step: {next_step or '(none stated)'}")
    if tally_result.dealbreakers or minority_report:
        lines.append("")
        lines.append("Minority Report:")
        if tally_result.dealbreakers:
            lines.append(f"- Dealbreaker dissent from: {', '.join(tally_result.dealbreakers)} (survives even when outvoted).")
        if minority_report:
            lines.append(minority_report)
    return "\n".join(lines)


# ------------------------------------------------------- panel selection
# Batch 13: council's STEP 0 panel selection. The panel itself stays
# the 3 lenses in teams.definitions (Skeptic / Builder / Pragmatist);
# what is new is CHOOSING among them by profile, locking the domain
# seat BEFORE any analysis, and naming the selection in session
# metadata. No 18-persona panel is invented: Sangam has 3 lenses, and
# the profiles below are honest subsets/pairs of those 3.
PANEL_PROFILES: dict[str, tuple[str, ...]] = {
    "classic": ("skeptic", "builder", "pragmatist"),
    "exploration-orthogonal": ("skeptic", "builder"),
    "execution-lean": ("builder", "pragmatist"),
    "duo-skeptic-builder": ("skeptic", "builder"),
    "duo-builder-pragmatist": ("builder", "pragmatist"),
    "duo-skeptic-pragmatist": ("skeptic", "pragmatist"),
}

# Domain keyword -> lens that holds the 1.5x domain seat for it.
DOMAIN_SEAT_KEYWORDS: dict[str, str] = {
    "security": "skeptic", "vulnerab": "skeptic", "risk": "skeptic",
    "attack": "skeptic", "flaw": "skeptic",
    "build": "builder", "implement": "builder", "ship": "builder",
    "code": "builder", "architect": "builder",
    "cost": "pragmatist", "budget": "pragmatist", "price": "pragmatist",
    "deadline": "pragmatist", "reversib": "pragmatist",
}

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "should", "we", "is", "are", "be", "do", "does", "what", "how", "why",
    "this", "that", "it", "its", "our", "us", "by", "from", "at", "as",
}


def select_panel(lenses: list[Any], profile: str = "classic",
                 members: list[str] | None = None) -> tuple[list[Any], str]:
    """Choose the deliberating panel. ``members`` (manual selection)
    wins over ``profile``; both are validated, never silently trimmed.

    Returns (panel_lenses, panel_name). Raises ValueError on an
    unknown profile, unknown member, or a panel smaller than 2."""
    by_id = {lens.id: lens for lens in lenses}
    if members:
        unknown = [m for m in members if m not in by_id]
        if unknown:
            raise ValueError(f"Unknown council members: {', '.join(unknown)}")
        if len(members) < 2:
            raise ValueError("A council needs at least 2 members.")
        return [by_id[m] for m in members], "manual"
    profile = (profile or "classic").lower()
    if profile not in PANEL_PROFILES:
        raise ValueError(
            f"Unknown council profile: {profile!r} "
            f"(known: {', '.join(sorted(PANEL_PROFILES))})")
    ids = PANEL_PROFILES[profile]
    panel = [by_id[i] for i in ids if i in by_id]
    if len(panel) < 2:
        raise ValueError(f"Profile {profile!r} resolves to fewer than 2 lenses.")
    return panel, profile


def lock_domain_seat(question: str, panel: list[Any]) -> str | None:
    """Lock the domain seat BEFORE analysis (council STEP 0 rule).

    First keyword match in question order wins; no match -> None
    ("none when ambiguous — never picked after votes"). The seat is
    a lens id present in the panel, or None."""
    panel_ids = {lens.id for lens in panel}
    text = (question or "").lower()
    for keyword, lens_id in DOMAIN_SEAT_KEYWORDS.items():
        if keyword in text and lens_id in panel_ids:
            return lens_id
    return None


def restate_gate(question: str, restatement: str) -> dict[str, Any]:
    """Problem-restate gate (council STEP 1.5): a restatement passes
    when it shares at least half of the question's content words
    (length >= 4, minus stopwords). Returns {ok, coverage, missing}.

    A failed gate is a signal to re-prompt the restatement, not proof
    the question was misunderstood — the threshold is a heuristic."""
    def _content(text: str) -> set[str]:
        return {w for w in re.findall(r"[a-z]+", (text or "").lower())
                if len(w) >= 4 and w not in _STOPWORDS}

    q_words = _content(question)
    if not q_words:
        return {"ok": False, "coverage": 0.0, "missing": []}
    r_words = _content(restatement)
    shared = q_words & r_words
    coverage = len(shared) / len(q_words)
    return {"ok": coverage >= 0.5, "coverage": round(coverage, 3),
            "missing": sorted(q_words - r_words)}


def session_metadata(panel: list[Any], profile: str,
                     domain_seat: str | None,
                     enforcement_log: list[dict]) -> dict[str, Any]:
    """Fixed-schema session metadata block (council STEP 8 shape).

    The domain seat is recorded as locked-before-analysis because
    callers lock it before calling deliberate(); this function only
    reports what it was given, it never re-derives it after votes."""
    return {"panel": [lens.id for lens in panel], "profile": profile,
            "domain_seat": domain_seat,
            "domain_seat_locked_before_analysis": True,
            "rounds": 3, "enforcement_calls": enforcement_log,
            "generated_at": datetime.now(UTC).isoformat()}


# ------------------------------------------------------------ outcome ledger

LEDGER_STATUSES = {"open", "confirmed", "revised", "reversed", "inconclusive"}


@dataclass
class OutcomeEntry:
    id: str
    prediction: str
    owner: str
    review_date: str  # ISO date; kill criteria are dated by this + text
    kill_criteria: str
    status: str = "open"
    review_notes: str = ""
    original_prediction: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "prediction": self.prediction, "owner": self.owner,
                "review_date": self.review_date, "kill_criteria": self.kill_criteria,
                "status": self.status, "review_notes": self.review_notes,
                "original_prediction": self.original_prediction}


class OutcomeLedger:
    """Decision ledger. ``prediction`` is the live text; marking a
    review NEVER rewrites ``original_prediction`` — that field is
    set once at record time and frozen."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.entries: dict[str, OutcomeEntry] = {}
        if self.path and self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                for item in raw:
                    self.entries[item["id"]] = OutcomeEntry(**item)
            except (json.JSONDecodeError, OSError, TypeError, KeyError):
                self.entries = {}

    def _persist(self) -> None:
        if self.path:
            _atomic_write(self.path, json.dumps([e.to_dict() for e in self.entries.values()], indent=2))

    def record(self, prediction: str, owner: str, review_date: str,
               kill_criteria: str) -> OutcomeEntry:
        entry = OutcomeEntry(id=f"oc-{uuid.uuid4().hex[:12]}", prediction=prediction,
                             owner=owner, review_date=review_date,
                             kill_criteria=kill_criteria, original_prediction=prediction)
        self.entries[entry.id] = entry
        self._persist()
        return entry

    def mark(self, entry_id: str, status: str, review_notes: str = "") -> OutcomeEntry:
        if status not in LEDGER_STATUSES:
            raise ValueError(f"unknown ledger status: {status}")
        entry = self.entries.get(entry_id)
        if entry is None:
            raise ValueError(f"unknown outcome entry: {entry_id}")
        # Status + notes move; the original prediction never does.
        entry.status = status
        entry.review_notes = review_notes
        self.entries[entry_id] = entry
        self._persist()
        return entry

    def due_for_review(self, on: date | None = None) -> list[OutcomeEntry]:
        today = (on or datetime.now(UTC).date()).isoformat()
        return [e for e in self.entries.values()
                if e.status == "open" and e.review_date <= today]


def mirror_to_runstore(run_id: str, owner_id: str, title: str, state: str) -> None:
    """Best-effort mirror onto contracts.run_store (live plane only).
    Failures are swallowed — the ledger file is authoritative."""
    try:
        from .contracts import RunState, run_store
        record = run_store.get(run_id)
        if record is None:
            record = run_store.create(kind="council", owner_id=owner_id, title=title, run_id=run_id)
        wanted = RunState(state) if state in RunState._value2member_map_ else None
        if wanted is not None and record.state != wanted:
            if record.state == RunState.PENDING and wanted != RunState.RUNNING:
                record.transition(RunState.RUNNING)
            record.transition(wanted)
    except Exception:
        pass


# ------------------------------------------------------------- deliberation

Completer = Callable[[list[dict[str, str]]], Awaitable[str]]


@dataclass
class DeliberationResult:
    question: str
    round1: dict[str, str]
    round2: dict[str, str]
    votes: list[CouncilVote]
    tally: TallyResult
    enforcement: dict[str, Any]
    verdict: str
    member_to_label: dict[str, str]
    chairman_synthesis: str = ""
    panel: list[str] = field(default_factory=list)
    profile: str = "classic"
    session: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"question": self.question, "round1": self.round1, "round2": self.round2,
                "tally": self.tally.to_dict(), "enforcement": self.enforcement,
                "verdict": self.verdict, "member_to_label": self.member_to_label,
                "chairman_synthesis": self.chairman_synthesis,
                "panel": self.panel, "profile": self.profile,
                "session_metadata": self.session}


async def deliberate(question: str, lenses: list[Any], completer: Completer,
                     domain_seat: str | None = None,
                     label_aliases: dict[str, str] | None = None,
                     chairman: bool = False, profile: str = "classic",
                     reprompt: bool = True) -> DeliberationResult:
    """Run one council deliberation. Lenses are AgentSpec-like objects
    with ``id``, ``role`` and ``system_prompt`` (method is metadata,
    not a separate call). The domain seat must be chosen BEFORE any
    analysis — passing it after the fact is a caller bug, not a
    feature, so it is an argument, not something inferred here."""
    question = (question or "").strip()
    if not question:
        raise ValueError("Empty question.")
    if len(lenses) < 2:
        raise ValueError("A council needs at least 2 lenses.")
    # Round 1 — blind-parallel: each lens sees ONLY the problem.
    round1: dict[str, str] = {}
    for lens in lenses:
        round1[lens.id] = await completer([
            {"role": "system", "content": lens.system_prompt},
            {"role": "user", "content": (
                f"Question: {question}\n\nAnalyse it in at most 400 words, "
                "through your own lens only. You have not seen any other member's view.")},
        ])
    # Round 2 — anonymized cross-examination.
    anonymized, member_to_label = anonymize(round1)
    anon_text = "\n\n".join(f"{label}:\n{text}" for label, text in anonymized.items())
    round2: dict[str, str] = {}
    for lens in lenses:
        label = member_to_label[lens.id]
        round2[lens.id] = await completer([
            {"role": "system", "content": lens.system_prompt},
            {"role": "user", "content": (
                f"You are {label} in this round. Anonymized Round-1 analyses:\n{anon_text}\n\n"
                "Name the member you most disagree with and why (engage specific claims), "
                "name one insight from another member that strengthens your position, "
                "then restate your position noting any change. Update only when a "
                "specific flaw in your own argument is named; agreement alone is not "
                "a reason to move.")},
        ])
    # Enforcement re-prompts (Batch 13 — council STEP 4, not tags-only
    # any more). Each trigger fires at most ONE re-prompt per member,
    # and only before Round 3, so the round budget stays bounded:
    # - dissent quota unmet (<2 dissenters): re-prompt every member
    #   whose Round-2 text names no disagreement, asking it to name
    #   one specific disagreement or state explicitly that it agrees.
    # - novelty failure (Round 2 == Round 1): re-prompt to engage.
    enforcement_log: list[dict] = []
    if reprompt:
        dissenters = {m for m, text in round2.items()
                      if re.search(r"disagree", text or "", re.IGNORECASE)}
        if len(dissenters) < 2:
            for lens in lenses:
                if lens.id in dissenters:
                    continue
                label = member_to_label[lens.id]
                round2[lens.id] = await completer([
                    {"role": "system", "content": lens.system_prompt},
                    {"role": "user", "content": (
                        f"You are {label}. Your cross-examination named no "
                        "disagreement. Name the member you most disagree with "
                        "and one specific claim you dispute — or state plainly "
                        "that you agree with every other member and why.")},
                ])
                enforcement_log.append({"trigger": "dissent_quota",
                                        "member": lens.id, "reprompted": True})
        for lens in lenses:
            if (round1.get(lens.id) or "").strip() and \
                    (round2.get(lens.id) or "").strip() == (round1[lens.id] or "").strip():
                round2[lens.id] = await completer([
                    {"role": "system", "content": lens.system_prompt},
                    {"role": "user", "content": (
                        "Your cross-examination merely restated your Round-1 "
                        "analysis. Engage one specific claim from another "
                        "member: agree with a reason, or disagree with a reason.")},
                ])
                enforcement_log.append({"trigger": "novelty",
                                        "member": lens.id, "reprompted": True})
    # Round 3 — final crystallization: exact STANCE line required.
    votes: list[CouncilVote] = []
    finals: dict[str, str] = {}
    for lens in lenses:
        final = await completer([
            {"role": "system", "content": lens.system_prompt},
            {"role": "user", "content": (
                "Give your final position in at most 100 words. Its last line MUST be exactly:\n"
                "STANCE: <short label> | CONFIDENCE: high|med|low | DEALBREAKER: yes|no")},
        ])
        finals[lens.id] = final
        votes.append(parse_stance(final, lens.id))
    # Missing-stance re-prompt: exactly one retry per abstainer, then
    # the member stays an abstainer (never an inferred vote).
    if reprompt:
        for lens, vote in zip(lenses, votes):
            if vote.missing_stance:
                retry = await completer([
                    {"role": "system", "content": lens.system_prompt},
                    {"role": "user", "content": (
                        "Your final position had no STANCE line, so it counts "
                        "as an abstention. Reply again with the same position "
                        "and end with exactly:\n"
                        "STANCE: <short label> | CONFIDENCE: high|med|low | DEALBREAKER: yes|no")},
                ])
                finals[lens.id] = retry
                votes[votes.index(vote)] = parse_stance(retry, lens.id)
                enforcement_log.append({"trigger": "missing_stance",
                                        "member": lens.id, "reprompted": True})
    tally_result = tally(votes, domain_seat=domain_seat, label_aliases=label_aliases)
    enforcement = enforcement_scan(round1, round2, votes)
    verdict = build_verdict(question, tally_result)
    # Chairman step (Batch 13 — council STEP 1.7): a synthesiser
    # distinct from the deliberators. Only when chairman=True, so
    # existing callers' call counts and verdicts are unchanged.
    chairman_synthesis = ""
    if chairman:
        chairman_synthesis = await completer([
            {"role": "system", "content": (
                "You are the Council Chairman. You did not deliberate; you "
                "only synthesise. Summarise the tally, name the strongest "
                "argument per option, and preserve dissent verbatim in "
                "spirit — never manufacture a consensus the tally does "
                "not show.")},
            {"role": "user", "content": (
                f"Question: {question}\n\nTally: {tally_result.to_dict()}\n\n"
                f"Verdict draft:\n{verdict}\n\nWrite the Chairman's synthesis "
                "(at most 150 words).")},
        ])
        verdict = f"Chairman's synthesis:\n{chairman_synthesis}\n\n{verdict}"
    session = session_metadata(lenses, profile, domain_seat, enforcement_log)
    return DeliberationResult(question=question, round1=round1, round2=round2,
                              votes=votes, tally=tally_result, enforcement=enforcement,
                              verdict=verdict, member_to_label=member_to_label,
                              chairman_synthesis=chairman_synthesis,
                              panel=[lens.id for lens in lenses], profile=profile,
                              session=session)
