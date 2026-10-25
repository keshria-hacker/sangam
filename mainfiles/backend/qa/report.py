"""Test report: passed / failed / skipped / untested, separated.

``untested`` is not inferred — the caller names what was NOT covered
(e.g. endpoints with no recorded case, or spec FRs with no test).
A report that hid untested work inside "passed" would be a lie, so
the four buckets are always reported together, with counts.
"""
from __future__ import annotations


def build_report(results: list[dict], untested: list[str] | None = None) -> dict:
    passed = [r for r in results if r.get("status") == "passed"]
    failed = [r for r in results if r.get("status") == "failed"]
    skipped = [r for r in results if r.get("status") == "skipped"]
    untested_list = list(untested or [])
    total = len(results) + len(untested_list)
    return {
        "total": total,
        "passed": len(passed), "failed": len(failed),
        "skipped": len(skipped), "untested": len(untested_list),
        "passed_cases": [r["case"]["path"] for r in passed],
        "failed_cases": [{"path": r["case"]["path"], "diff": r.get("diff", "")}
                         for r in failed],
        "skipped_cases": [r["case"]["path"] for r in skipped],
        "untested_cases": untested_list,
        "all_passed": not failed and not untested_list,
    }


def render_report_markdown(report: dict) -> str:
    lines = ["# Test report", "",
             f"- total: {report['total']}",
             f"- passed: {report['passed']}",
             f"- failed: {report['failed']}",
             f"- skipped: {report['skipped']}",
             f"- untested: {report['untested']}", ""]
    for f in report["failed_cases"]:
        lines.append(f"- FAILED {f['path']}: {f['diff']}")
    for u in report.get("untested_cases", []):
        lines.append(f"- UNTESTED {u}")
    return "\n".join(lines) + "\n"
