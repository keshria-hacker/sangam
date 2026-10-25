"""backend/qa/ — test recorder + replay + GreenContract (Cluster J).

Smallest faithful port of the record/replay idea: no eBPF, no kernel
hooks, no time-freeze claims. Real API traffic recorded through a
TestClient is stored as JSON cassettes with noise handling for
timestamps/random IDs; replay re-issues the same requests (no model
call) and compares normalized responses; output is a pytest file
that CI can run, plus a report separating passed / failed / skipped /
untested.
"""
from .greencontract import LEVELS, graduated_satisfied, next_level
from .noise import normalize_json, normalize_text
from .recorder import Recorder, load_cassette, save_cassette
from .replay import replay_cases
from .report import build_report

__all__ = [
    "LEVELS", "graduated_satisfied", "next_level",
    "normalize_json", "normalize_text",
    "Recorder", "load_cassette", "save_cassette",
    "replay_cases", "build_report",
]
