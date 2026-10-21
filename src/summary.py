"""Check the summary the CLI wrote and render it for GitHub.

The eval process exit code decides the check. This module only refuses a
summary that cannot be trusted (missing, unreadable, or disagreeing with the
process) and turns a trusted one into a pull request comment, a job summary,
and step outputs. Standard library only, Python 3.8+.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

EXIT_SUMMARY = 5
SUPPORTED_SCHEMA = 1

GATE_LABELS = {
    "min_pass_rate": "Min pass rate",
    "max_drop": "Max drop",
    "max_task_cost_increase": "Max task cost increase",
    "max_judge_cost_increase": "Max judge cost increase",
    "max_latency_increase": "Max latency increase",
    "baseline_experiment_id": "Baseline",
}


def comment_marker(key: str) -> str:
    """HTML marker that identifies this job's comment. Only safe characters survive."""
    safe = re.sub(r"[^A-Za-z0-9._/]+", "-", key or "").strip("-") or "eval"
    return f"<!-- traccia-eval:{safe} -->"


def load(path: str, status: int) -> Tuple[Dict[str, Any], Optional[str]]:
    """Return (summary, problem). A problem means the check must exit 5."""
    if not os.path.isfile(path):
        return {}, "The eval did not write a summary file."
    try:
        with open(path, encoding="utf-8") as handle:
            body = json.load(handle)
    except (OSError, ValueError):
        return {}, "The summary file is not valid JSON."
    if not isinstance(body, dict):
        return {}, "The summary file is not a JSON object."
    recorded = body.get("exit_code")
    if isinstance(recorded, bool) or not isinstance(recorded, int):
        return body, "The summary file has no integer exit_code."
    if recorded != status:
        return body, f"The summary says exit {recorded} but the eval process exited {status}."
    return body, None


def summary_failure(problem: str) -> Dict[str, Any]:
    return {
        "schema_version": SUPPORTED_SCHEMA,
        "exit_code": EXIT_SUMMARY,
        "code": "summary_failed",
        "label": "Failed",
        "quality_gate": False,
        "failures": [{"code": "summary_failed", "message": problem}],
    }


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(float(value)) else None


def _percent(value: Any) -> str:
    number = _number(value)
    return "—" if number is None else f"{number * 100:.1f}%"


def _points(candidate: Any, baseline: Any) -> str:
    a, b = _number(candidate), _number(baseline)
    if a is None or b is None:
        return "—"
    delta = (a - b) * 100
    if abs(delta) < 0.05:
        return "0.0 pts"
    sign = "+" if delta > 0 else "−"
    return f"{sign}{abs(delta):.1f} pts"


def _cell(text: Any) -> str:
    """Make arbitrary text safe inside a Markdown table cell or list item."""
    value = str(text if text is not None else "")
    value = value.replace("\r", " ").replace("\n", " ").replace("|", "\\|")
    return value.replace("<", "&lt;").replace(">", "&gt;").strip()


def _safe_url(value: Any) -> Optional[str]:
    if isinstance(value, str) and re.match(r"^https?://[^\s<>()]+$", value.strip()):
        return value.strip()
    return None


def _gate_value(key: str, value: Any) -> str:
    if key == "baseline_experiment_id":
        return f"`{_cell(value)[:12]}`"
    number = _number(value)
    if number is None:
        return _cell(value)
    if key == "min_pass_rate":
        return f"{number * 100:g}%"
    if key == "max_drop":
        return f"{number * 100:g} pts"
    return f"+{number * 100:g}%"


def headline(body: Dict[str, Any]) -> str:
    code = body.get("exit_code")
    if code == 0 and body.get("quality_gate"):
        return "✅ **Traccia Eval passed** · Quality Gate"
    if code == 0:
        return "✅ **Traccia Eval passed** · Execution Only (no pass-rate gate)"
    reason = body.get("code") or "failed"
    return f"❌ **Traccia Eval failed** · `{_cell(reason)}` (exit {code})"


def scorer_table(body: Dict[str, Any]) -> List[str]:
    scorers = [s for s in body.get("scorers") or [] if isinstance(s, dict)]
    if not scorers:
        return []
    has_baseline = any(s.get("baseline_pass_rate") is not None for s in scorers)
    header = ["Scorer", "Pass rate"] + (["Baseline", "Change"] if has_baseline else []) + ["Graded"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for scorer in scorers:
        name = _cell(scorer.get("name") or "scorer")
        if scorer.get("informational"):
            name += " _(informational)_"
        rate = scorer.get("pass_rate")
        rate_text = _percent(rate) if rate is not None else "incomplete"
        row = [f"`{name}`" if not scorer.get("informational") else name, rate_text]
        if has_baseline:
            row += [_percent(scorer.get("baseline_pass_rate")), _points(rate, scorer.get("baseline_pass_rate"))]
        expected, completed = scorer.get("expected"), scorer.get("completed")
        graded = f"{completed}/{expected}" if isinstance(expected, int) and isinstance(completed, int) else "—"
        problems = []
        for key in ("missing", "errored", "duplicate"):
            count = scorer.get(key)
            if isinstance(count, int) and count:
                problems.append(f"{count} {key}")
        if problems:
            graded += " (" + ", ".join(problems) + ")"
        row.append(graded)
        lines.append("| " + " | ".join(row) + " |")
    return lines


def render(body: Dict[str, Any], *, marker: str, checkout_sha: str, run_url: Optional[str]) -> str:
    lines = [marker, headline(body), ""]
    table = scorer_table(body)
    if table:
        lines += table + [""]
    failures = [f for f in body.get("failures") or [] if isinstance(f, dict)]
    if failures:
        lines.append("**Failures**")
        lines += [f"- `{_cell(f.get('code') or 'failed')}` {_cell(f.get('message'))}".rstrip() for f in failures]
        lines.append("")
    gates = body.get("gates") if isinstance(body.get("gates"), dict) else {}
    if gates:
        parts = [f"{GATE_LABELS.get(k, _cell(k))} {_gate_value(k, v)}" for k, v in gates.items() if v is not None]
        lines += ["**Gates:** " + " · ".join(parts), ""]
    links = []
    experiment = _safe_url(body.get("url"))
    if experiment:
        links.append(f"[Open experiment]({experiment})")
    if run_url:
        links.append(f"[View run]({run_url})")
    if checkout_sha:
        links.append(f"commit `{checkout_sha[:7]}`")
    if links:
        lines.append(" · ".join(links))
    version = body.get("schema_version")
    if version not in (None, SUPPORTED_SCHEMA):
        lines += ["", f"> Summary schema {_cell(version)} is newer than this action understands. Upgrade the action."]
    return "\n".join(lines).rstrip() + "\n"


def outputs(body: Dict[str, Any], summary_path: str) -> Dict[str, str]:
    return {
        "exit_code": str(body.get("exit_code")),
        "code": str(body.get("code") or ""),
        "label": str(body.get("label") or ""),
        "quality_gate": "true" if body.get("quality_gate") is True else "false",
        "experiment_id": str(body.get("experiment_id") or ""),
        "experiment_url": _safe_url(body.get("url")) or "",
        "summary_path": os.path.abspath(summary_path),
    }


def _append(path: Optional[str], text: str) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--status", required=True, type=int)
    parser.add_argument("--checkout-sha", default="")
    parser.add_argument("--comment-key", default="")
    parser.add_argument("--run-url", default="")
    parser.add_argument("--comment-out", required=True, help="Where to write the comment Markdown")
    parser.add_argument("--status-out", required=True, help="Where to write the exit status for the step")
    args = parser.parse_args(argv)

    body, problem = load(args.summary, args.status)
    if problem:
        print(f"::error title=Traccia Eval::{problem}", file=sys.stderr)
        body = summary_failure(problem)

    comment = render(
        body,
        marker=comment_marker(args.comment_key),
        checkout_sha=args.checkout_sha,
        run_url=_safe_url(args.run_url),
    )
    with open(args.comment_out, "w", encoding="utf-8") as handle:
        handle.write(comment)

    details = json.dumps(body, indent=2, sort_keys=True)
    _append(
        os.environ.get("GITHUB_STEP_SUMMARY"),
        f"{comment}\n<details><summary>summary.json</summary>\n\n```json\n{details}\n```\n\n</details>\n\n",
    )
    values = outputs(body, args.summary)
    lines = "".join(f"{k}={' '.join(v.split())}\n" for k, v in values.items())
    _append(os.environ.get("GITHUB_OUTPUT"), lines)
    with open(args.status_out, "w", encoding="utf-8") as handle:
        handle.write(str(int(body["exit_code"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
