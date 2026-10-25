"""Audio depth, cloning-free (VoiceStudio salvage).

Pure helpers — no engine, no model, no reference audio anywhere:

* chunked long-form TTS: split only at sentence/clause boundaries,
  never mid-word (a single over-long word is kept whole and flagged);
* audiobook plans: chapters -> spans with deterministic per-span seeds
  (same text + seed -> same seeds) and chapter-gap rules;
* timed subtitles: SRT/VTT rendering plus word-level ASS (words split
  evenly across a cue — the ``even_split_words`` pattern), and fitting
  a voiced script back onto source segment timings;
* diarization *labels*: assigning speaker labels to segments from
  supplied turn boundaries. Sangam's STT engines return plain text, not
  turns, so labels are only ever carried from caller-supplied segments
  — never invented. A transcript without turn data has speaker None.
* WAV loudness normalisation for 16-bit PCM via the stdlib only.
"""
from __future__ import annotations

import hashlib
import io
import re
import struct
import wave

# ---------------------------------------------------------------- chunking

_SENTENCE_RE = re.compile(r"(?<=[.!?\u2026])\s+")
_CLAUSE_RE = re.compile(r"(?<=[,;:\u2014\u2013])\s+")
_WORD_RE = re.compile(r"\S+")


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return []
    return [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]


def chunk_text(text: str, max_chars: int = 800) -> list[dict]:
    """Split ``text`` into chunks of at most ``max_chars`` characters.

    Cuts happen at sentence boundaries first, then clause boundaries,
    then word boundaries — never mid-word. A chunk dict carries the
    text plus ``cut`` (``sentence``/``clause``/``word``/``whole-word``)
    so callers can see exactly where a cut happened.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be >= 1")
    chunks: list[dict] = []
    for sentence in split_sentences(text):
        if len(sentence) <= max_chars:
            chunks.append({"text": sentence, "cut": "sentence"})
            continue
        # Long sentence: clause splits, then word-boundary packing.
        pieces = [p for p in _CLAUSE_RE.split(sentence) if p]
        buf, buf_cut = "", "clause"
        for piece in pieces:
            if len(piece) > max_chars:
                if buf:
                    chunks.append({"text": buf.strip(), "cut": buf_cut})
                    buf, buf_cut = "", "clause"
                # Pack words; a single over-long word stays whole.
                cur = ""
                for word in _WORD_RE.findall(piece):
                    if cur and len(cur) + 1 + len(word) > max_chars:
                        chunks.append({"text": cur,
                                       "cut": "whole-word" if len(cur) > max_chars else "word"})
                        cur = word
                    else:
                        cur = f"{cur} {word}".strip()
                if cur:
                    chunks.append({"text": cur,
                                   "cut": "whole-word" if len(cur) > max_chars else "word"})
                continue
            if buf and len(buf) + 1 + len(piece) > max_chars:
                chunks.append({"text": buf.strip(), "cut": buf_cut})
                buf, buf_cut = piece, "clause"
            else:
                buf = f"{buf} {piece}".strip() if buf else piece
        if buf:
            chunks.append({"text": buf.strip(), "cut": buf_cut})
    return chunks


def join_chunk_gaps(n_chunks: int, gap_ms: int = 250) -> list[int]:
    """Silence gap (ms) inserted between consecutive chunks.

    Deterministic and explicit: chunk joins are ``gap_ms`` of silence,
    not a crossfade nobody asked for.
    """
    if n_chunks <= 1:
        return []
    return [gap_ms] * (n_chunks - 1)


# ---------------------------------------------------------------- audiobook

def segment_seed(seed: int, chapter_index: int, span_index: int) -> int:
    """Deterministic per-span seed (VoiceStudio's ``segment_seed``)."""
    digest = hashlib.sha256(
        f"{seed}:{chapter_index}:{span_index}".encode()).hexdigest()
    return int(digest[:8], 16)


def audiobook_plan(text: str, seed: int = 0, chapters: list[dict] | None = None,
                   chapter_gap_ms: int = 1500, span_gap_ms: int = 250,
                   max_chars: int = 800) -> dict:
    """Build a chapter/span plan. ``chapters`` may be [{title, text}];
    otherwise the whole text is one untitled chapter. The export
    manifest lists chapters in order with their spans and seeds — it
    is a plan, not audio; rendering happens through the TTS engine.
    """
    if chapters is None:
        chapters = [{"title": "", "text": text}]
    out_chapters = []
    for ci, chapter in enumerate(chapters):
        spans = []
        for si, chunk in enumerate(chunk_text(chapter.get("text", ""), max_chars)):
            spans.append({"text": chunk["text"], "cut": chunk["cut"],
                          "seed": segment_seed(seed, ci, si),
                          "gap_after_ms": span_gap_ms})
        if spans:
            spans[-1]["gap_after_ms"] = chapter_gap_ms
        out_chapters.append({"title": chapter.get("title", ""),
                             "spans": spans})
    return {"seed": seed, "chapter_gap_ms": chapter_gap_ms,
            "span_gap_ms": span_gap_ms, "chapters": out_chapters,
            "manifest": "chaptered export: chapters in order, spans in "
                        "order, seeds deterministic per (seed, chapter, span)."}


# ---------------------------------------------------------------- subtitles

def _fmt_srt(t: float) -> str:
    ms = max(0, int(round(t * 1000)))
    return f"{ms // 3600000:02d}:{(ms // 60000) % 60:02d}:{(ms // 1000) % 60:02d},{ms % 1000:03d}"


def _fmt_vtt(t: float) -> str:
    ms = max(0, int(round(t * 1000)))
    return f"{ms // 3600000:02d}:{(ms // 60000) % 60:02d}:{(ms // 1000) % 60:02d}.{ms % 1000:03d}"


def _fmt_ass(t: float) -> str:
    cs = max(0, int(round(t * 100)))
    return f"{cs // 360000:01d}:{(cs // 6000) % 60:02d}:{(cs // 100) % 60:02d}.{cs % 100:02d}"


def validate_segments(segments: object) -> list[dict]:
    """Validate timed segments; returns fixable diagnostics."""
    errs: list[dict] = []

    def err(code: str, message: str, fix: str) -> dict:
        return {"code": code, "message": message, "supportedFixes": fix}

    if not isinstance(segments, list) or not segments:
        return [err("no-segments", "segments must be a non-empty list",
                    "Supply timed segments [{start, end, text}].")]
    prev_end = 0.0
    for i, seg in enumerate(segments):
        if not isinstance(seg, dict):
            errs.append(err("bad-segment", f"segments[{i}] must be an object",
                            "Replace it with {start, end, text}."))
            continue
        start, end = seg.get("start"), seg.get("end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            errs.append(err("bad-timing", f"segments[{i}] needs numeric start/end",
                            "Set start/end in seconds, e.g. 0.0 and 2.5."))
            continue
        if start < 0 or end <= start:
            errs.append(err("bad-timing",
                            f"segments[{i}] needs 0 <= start < end",
                            "Fix start/end so the cue has positive duration."))
        if start < prev_end - 1e-9:
            errs.append(err("overlap",
                            f"segments[{i}] starts before the previous cue ends",
                            "Re-time the cues so they do not overlap."))
        prev_end = max(prev_end, end)
        if not (seg.get("text") or "").strip():
            errs.append(err("empty-text", f"segments[{i}].text is empty",
                            "Add the spoken text for this cue."))
    return errs


def render_srt(segments: list[dict]) -> str:
    lines = []
    for i, seg in enumerate(segments, 1):
        label = f" [{seg['speaker']}]" if seg.get("speaker") else ""
        lines.append(f"{i}\n{_fmt_srt(seg['start'])} --> {_fmt_srt(seg['end'])}"
                     f"\n{label.strip() + ' ' if label else ''}{seg['text'].strip()}")
    return "\n\n".join(lines) + "\n"


def render_vtt(segments: list[dict]) -> str:
    lines = ["WEBVTT", ""]
    for seg in segments:
        label = f"<v {seg['speaker']}> " if seg.get("speaker") else ""
        lines.append(f"{_fmt_vtt(seg['start'])} --> {_fmt_vtt(seg['end'])}")
        lines.append(f"{label}{seg['text'].strip()}\n")
    return "\n".join(lines)


def _ass_escape(text: str) -> str:
    return text.replace("{", "\\{").replace("}", "\\}").replace("\n", " ")


def render_ass_word_level(segments: list[dict]) -> str:
    """Word-level karaoke ASS: each word's duration sums exactly to
    its cue duration (even split, remainder on the last word)."""
    header = ("[Script Info]\nScriptType: v4.00+\n\n"
              "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, "
              "SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
              "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
              "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, "
              "MarginV, Encoding\n"
              "Style: Default,Arial,20,&H00FFFFFF,&H0000FFFF,&H00000000,"
              "&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1\n\n"
              "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, "
              "MarginR, MarginV, Effect, Text\n")
    events = []
    for seg in segments:
        words = seg["text"].split()
        dur = seg["end"] - seg["start"]
        if not words:
            continue
        # Even split in centiseconds; remainder goes to the last word so
        # the word timings sum exactly to the cue duration.
        total_cs = int(round(dur * 100))
        per = total_cs // len(words)
        cursor = seg["start"]
        parts = []
        for wi, word in enumerate(words):
            w_dur = (total_cs - per * (len(words) - 1)) / 100.0 if wi == len(words) - 1 else per / 100.0
            parts.append(f"{{\\k{int(round(w_dur * 100))}}}{_ass_escape(word)}")
            cursor += w_dur
        events.append(f"Dialogue: 0,{_fmt_ass(seg['start'])},{_fmt_ass(seg['end'])},"
                      f"Default,,0,0,0,,{' '.join(parts)}")
    return header + "\n".join(events) + "\n"


def fit_script_to_segments(segments: list[dict], script: str) -> list[dict]:
    """Fit a voiced script onto source timings: script words are
    distributed across cues in proportion to cue duration (at least
    one word per cue while words remain). Timings are never invented
    beyond the supplied segments — an empty script returns the
    original cue texts."""
    words = script.split()
    if not words:
        return [dict(s) for s in segments]
    total_dur = sum(s["end"] - s["start"] for s in segments) or 1.0
    fitted, idx = [], 0
    for si, seg in enumerate(segments):
        remaining_cues = len(segments) - si
        remaining_words = len(words) - idx
        if si == len(segments) - 1:
            take = remaining_words
        else:
            take = max(1, round((seg["end"] - seg["start"]) / total_dur * len(words)))
            take = min(take, remaining_words - (remaining_cues - 1))
            take = max(take, 1) if remaining_words >= remaining_cues else remaining_words
        fitted.append({**seg, "text": " ".join(words[idx:idx + take])})
        idx += take
    return fitted


def label_segments(segments: list[dict], turns: list[dict]) -> list[dict]:
    """Diarization labels from supplied turn boundaries only.

    ``turns``: [{start, speaker}]. Each segment takes the speaker of
    the turn covering most of its span; segments outside every turn
    keep speaker None (unknown is reported, not guessed).
    """
    out = []
    for seg in segments:
        best, best_overlap = None, 0.0
        for turn in turns:
            overlap = max(0.0, min(seg["end"], turn.get("end", float("inf")))
                          - max(seg["start"], turn.get("start", 0.0)))
            if overlap > best_overlap:
                best, best_overlap = turn.get("speaker"), overlap
        out.append({**seg, "speaker": best})
    return out


# ---------------------------------------------------------------- loudness

def normalize_wav(data: bytes, target_peak: float = 0.89) -> bytes:
    """Peak-normalise 16-bit PCM WAV via stdlib only.

    Raises ValueError for non-WAV / unsupported formats instead of
    producing a fake normalised file. Silence passes through unchanged.
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            params = wav.getparams()
            frames = wav.readframes(wav.getnframes())
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"not a readable WAV file: {exc}") from exc
    if params.sampwidth != 2:
        raise ValueError("only 16-bit PCM WAV is supported for normalisation")
    count = len(frames) // 2
    samples = struct.unpack(f"<{count}h", frames)
    peak = max((abs(s) for s in samples), default=0)
    if peak == 0:
        return data
    scale = (target_peak * 32767) / peak
    scaled = struct.pack(f"<{count}h",
                         *(max(-32768, min(32767, int(round(s * scale)))) for s in samples))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setparams(params)
        out.writeframes(scaled)
    return buf.getvalue()


def join_wav_bytes(parts: list[bytes], gap_ms: int = 250) -> bytes:
    """Concatenate same-format WAV chunks with silence gaps.

    Raises ValueError when chunks are not WAV or formats differ —
    concatenation never silently resamples or truncates.
    """
    if not parts:
        raise ValueError("no audio chunks to join")
    parsed = []
    for part in parts:
        try:
            with wave.open(io.BytesIO(part), "rb") as wav:
                parsed.append((wav.getparams(), wav.readframes(wav.getnframes())))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"chunk is not a readable WAV file: {exc}") from exc
    first = parsed[0][0]
    for params, _ in parsed[1:]:
        if (params.nchannels, params.sampwidth, params.framerate) != \
                (first.nchannels, first.sampwidth, first.framerate):
            raise ValueError("WAV chunks have differing formats; cannot join")
    gap_frames = int(first.framerate * gap_ms / 1000) if gap_ms else 0
    silence = b"\x00" * (gap_frames * first.nchannels * first.sampwidth)
    frames = b""
    for i, (_params, data) in enumerate(parsed):
        if i:
            frames += silence
        frames += data
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setparams(first)
        out.writeframes(frames)
    return buf.getvalue()
