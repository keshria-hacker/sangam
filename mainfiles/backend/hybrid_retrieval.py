"""
hybrid_retrieval.py — Phase 2 (all-in-one plan): hybrid retrieval.

Problem it fixes
----------------
Document RAG was vector-only (``rag.retrieve_relevant_chunks``): a query
using an exact term that the embedding model paraphrases away could miss
the one chunk that literally contains it, and results carried no
provenance beyond a filename.

What this module does (pure functions, no Chroma dependency, so the
scoring is unit-testable without an embedding model):

1. BM25 keyword scoring over a candidate set (standard BM25, k1=1.5,
   b=0.75, corpus IDF from the candidates themselves).
2. Reciprocal Rank Fusion (RRF, k=60) of the vector ranking and the
   keyword ranking — a candidate found by both ranks above one found
   by either alone.
3. Deterministic reranking of the fused set: a normalised blend of
   vector similarity (1 / (1 + L2 distance)) and BM25, so the final
   order is explainable from the two signals, not a black box.

Honest limits
-------------
This is a *deterministic* reranker, not a neural cross-encoder: it
cannot judge semantic relevance beyond the embedding distance and
term overlap it is given. A cross-encoder reranker is a later Phase 2
item, gated on a local model being available; it must not be claimed
from this module.

Candidate shape (in and out)
-----------------------------
Input candidates are dicts with at least ``text`` and an ``id`` (or
``file_id`` + ``chunk_index``). ``vector_score`` is a Chroma L2
distance (lower = closer) or ``None`` for keyword-only candidates.
Output candidates carry ``score`` (fused, higher = better),
``vector_score``, ``keyword_score``, ``source`` (``vector`` /
``keyword`` / ``both``), and a ``citation`` dict with ``file_id``,
``filename``, ``chunk_index`` and a 200-char ``excerpt``.
"""

from __future__ import annotations

import math
import re
from typing import Any

# Small English stopword set: dropping these keeps BM25 from rewarding
# "the / is / of" matches. Deliberately short — domain terms are never
# stopwords here.
_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "of", "to", "in", "on", "at", "for", "with", "by", "and", "or",
    "what", "how", "why", "when", "where", "which", "who", "do",
    "does", "did", "can", "could", "should", "would", "it", "its",
    "this", "that", "these", "those", "i", "you", "we", "they",
})

_TOKEN_RE = re.compile(r"[a-z0-9]+")

BM25_K1 = 1.5
BM25_B = 0.75
RRF_K = 60
RERANK_VECTOR_WEIGHT = 0.6
RERANK_KEYWORD_WEIGHT = 0.4


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, stopwords removed."""
    if not text:
        return []
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


def bm25_scores(query: str, documents: list[str]) -> list[float]:
    """Standard BM25 scores, one per document, in input order.

    IDF is computed from the candidate corpus itself (``log(1 +
    (N - df + 0.5) / (df + 0.5))``), so scores are comparable within a
    retrieval call but not across calls — which is all reranking needs.
    """
    query_terms = tokenize(query)
    if not query_terms or not documents:
        return [0.0] * len(documents)
    tokenized = [tokenize(d) for d in documents]
    n = len(documents)
    doc_lens = [len(t) for t in tokenized]
    avg_len = sum(doc_lens) / n if n else 0.0
    df: dict[str, int] = {}
    for toks in tokenized:
        for term in set(toks):
            df[term] = df.get(term, 0) + 1
    scores: list[float] = []
    for toks, doc_len in zip(tokenized, doc_lens):
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        norm = 1.0 - BM25_B + BM25_B * (doc_len / avg_len) if avg_len else 1.0
        total = 0.0
        for term in set(query_terms):
            if term not in tf:
                continue
            idf = math.log(1.0 + (n - df[term] + 0.5) / (df[term] + 0.5))
            f = tf[term]
            total += idf * (f * (BM25_K1 + 1.0)) / (f + BM25_K1 * norm)
        scores.append(total)
    return scores


def _candidate_key(c: dict[str, Any]) -> str:
    if c.get("id"):
        return str(c["id"])
    return f"{c.get('file_id', '')}:{c.get('chunk_index', '')}"


def rrf_fuse(
    vector_ranked: list[dict[str, Any]],
    keyword_ranked: list[dict[str, Any]],
    k: int = RRF_K,
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion of two rankings.

    Each candidate gets ``sum(1 / (k + rank))`` over the rankings it
    appears in (rank is 1-based). The merged candidate keeps the
    ``vector_score``/``keyword_score`` of whichever ranking supplied
    it, and ``source`` records whether it came from one or both.
    """
    fused: dict[str, dict[str, Any]] = {}
    for ranked, source in ((vector_ranked, "vector"), (keyword_ranked, "keyword")):
        for rank, cand in enumerate(ranked, start=1):
            key = _candidate_key(cand)
            entry = fused.setdefault(key, dict(cand))
            entry["score"] = entry.get("score", 0.0) + 1.0 / (k + rank)
            prev = entry.get("source")
            entry["source"] = source if prev is None or prev == source else "both"
    out = sorted(fused.values(), key=lambda c: c["score"], reverse=True)
    return out


def rerank(
    query: str,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rerank fused candidates by a vector + BM25 blend.

    ``vector_score`` is an L2 distance, converted to a similarity
    (``1 / (1 + distance)``) which is already bounded in (0, 1], so it
    is used raw — min-max normalising it would turn any small distance
    gap into a full 0-to-1 gap and let the vector side always win.
    BM25 is unbounded, so it is normalised by the max BM25 in the set.
    The blend is 0.6 vector / 0.4 keyword: semantic closeness leads,
    exact-term evidence breaks ties and rescues literal matches.
    Returns candidates in final order, each with ``score`` (the
    blend), ``keyword_score`` and a ``citation``.
    """
    if not candidates:
        return []
    texts = [c.get("text", "") for c in candidates]
    kw = bm25_scores(query, texts)
    vec_sim = [
        (1.0 / (1.0 + c["vector_score"]))
        if isinstance(c.get("vector_score"), (int, float)) else None
        for c in candidates
    ]
    kw_max = max(kw) if kw else 0.0
    kw_n = [(s / kw_max) if kw_max > 0 else 0.0 for s in kw]
    vec_n = [s if s is not None else 0.0 for s in vec_sim]
    out = []
    for cand, kw_s, vec_s, kw_norm, vec_norm in zip(
        candidates, kw, vec_sim, kw_n, vec_n
    ):
        merged = dict(cand)
        merged["keyword_score"] = kw_s
        merged["vector_score"] = vec_s
        merged["score"] = (
            RERANK_VECTOR_WEIGHT * vec_norm + RERANK_KEYWORD_WEIGHT * kw_norm
        )
        merged["citation"] = make_citation(merged)
        out.append(merged)
    out.sort(key=lambda c: c["score"], reverse=True)
    return out


def make_citation(candidate: dict[str, Any]) -> dict[str, Any]:
    """Provenance for one retrieved chunk: what to cite, where it came from.

    ``provenance`` is ``verified`` for every chunk here: the chunk is
    grounded in a stored document (vector and/or BM25 match against
    its own text), not generated or guessed. The ``inferred`` label
    is reserved for signals that are NOT a stored chunk — graph
    keyword-links and web-search fallbacks, which label themselves
    in their own routes — so a reader can tell grounded citations
    from heuristic ones at a glance.
    """
    text = candidate.get("text", "") or ""
    return {
        "file_id": candidate.get("file_id", ""),
        "filename": candidate.get("filename", ""),
        "chunk_index": candidate.get("chunk_index"),
        "excerpt": text[:200],
        "source": candidate.get("source", "vector"),
        "provenance": "verified",
    }


def hybrid_rank(
    query: str,
    vector_candidates: list[dict[str, Any]],
    keyword_candidates: list[dict[str, Any]],
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Full pipeline: fuse the two rankings, rerank, take top_k.

    ``vector_candidates`` must be in vector-rank order and carry
    ``vector_score`` (L2 distance); ``keyword_candidates`` are the
    same chunk pool (their order is ignored — BM25 is recomputed).
    Candidates missing from one side are still eligible via the other.
    """
    if top_k <= 0 or not query:
        return []
    # Keyword side: rank by BM25, keeping only candidates with a
    # non-zero score, so zero-match chunks do not dilute the fusion.
    kw_scores = bm25_scores(query, [c.get("text", "") for c in keyword_candidates])
    kw_ranked = [
        c for c, s in sorted(
            zip(keyword_candidates, kw_scores), key=lambda p: p[1], reverse=True
        ) if s > 0
    ]
    fused = rrf_fuse(vector_candidates, kw_ranked)
    return rerank(query, fused)[:top_k]
