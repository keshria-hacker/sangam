# Response Quality — no-ai-slop + ADHD-friendly output

**Status:** implemented (2026-10-08) · branch `output-quality`
**Inspired by:** petergyang/no-ai-slop (20+ slop patterns), ayghri/i-have-adhd
(don't bury the answer)

## Architecture

```
backend/response_quality/
  slop.py   remove_slop(): purple-prose swaps ("delve into"->"look at",
            "tapestry"->"mix", "game-changer"->"major improvement"),
            filler-hedge deletions ("It's important to note that",
            "As an AI", "In today's fast-paced world"), leading openers.
            Case-preserving, sentence capitalization fixed after deletions.
  adhd.py   adhd_format(): strip throat-clearing openers, reflow walls of
            text (>600 chars) at sentence boundaries into <=400-char
            chunks, collapse blank lines. Never reorders; skips code
            blocks and lists.
  __init__.py  apply_quality(text, no_slop, adhd_friendly) -> (text, stats)
```

### Seam
Hooks into `post_process_response()` in `response_postprocessor.py` — runs on
the **fully-collected text at persistence time, never the live stream** (same
constraint as the confidence hedge). Wrapped so quality can never break chat.

### Configuration (env, off by default)
- `QUALITY_NO_SLOP=true` — slop cleanup
- `QUALITY_ADHD_FRIENDLY=true` — scannable formatting

Documented in `.env.example`. Projects as `capability:response_quality`.

## Design decisions
- **Conservative patterns only** — every slop pattern is slop in virtually
  any context; legitimate connectives ("moreover", "however") untouched.
- **Deterministic** — regex-based, no LLM calls, no latency, fully testable.
- **Stats returned** (`slop_removed`, `adhd_changes`) for future UI surfacing.

## Future (not in this pass)
- Per-user toggles in Settings (currently env-global)
- "Detect slop" mode that reports without rewriting
- Model-side guidance (system prompt) to reduce slop at generation time
