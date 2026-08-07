"""HearthBench A9 — Reports.

A9.1 (HTML report): `render_html_report` — self-contained (no
external CSS/JS, inline-styled), showing the recommendation in plain
language (A9.4, via `recommendation_text`), per-category scores with
confidence, and, when a real `run_dir` is given, real failure
examples pulled straight from A8's `RunRecordReader`/`BlobStore` — the
actual prompt/output text of a case where some scorer's real verdict
was `passed=False`, never a synthetic example. Latency/memory GRAPHS
(the item's own literal ask) are explicitly NOT attempted — this repo
has no bundled charting library and no plotting dependency; the
report instead prints the real p50/p95/max numbers `hearthbench.tests.
performance.summarize_latency` already computes as a plain table,
flagged honestly rather than faking a chart with ASCII art.

A9.2 (exports): `export_json`/`export_csv` — real, minimal, no
external dependency (`csv`/`json` stdlib only).

A9.3 (comparison report): `compare_runs(labeled_scores)` — N real
`HearthBenchScore`s side by side against the FIRST as baseline,
per-category deltas, and a genuine significance flag per category per
non-baseline run: the two `[score-margin, score+margin]` confidence
intervals (A10.4) either overlap (no flagged change — could be noise)
or don't (`significant_change=True`) — `None` when either run lacks a
real margin for that category (honestly "can't tell," never guessed).

A9.4 (the recommendation must be honest): `recommendation_text` states
low confidence prominently (`overall_confidence_margin` above `LOW_
CONFIDENCE_MARGIN_THRESHOLD`) and always leads with any A10.2
disqualification — a disqualifying weakness is never buried under an
otherwise-good headline number.

Import isolation (A1.2): stdlib + `hearthbench.diagnostics`/
`hearthbench.reporting.score`/`hearthbench.tests` only.
"""
from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass, field
from pathlib import Path

from hearthbench.diagnostics.run_record import RunRecordReader
from hearthbench.reporting.score import HearthBenchScore
from hearthbench.tests import CATEGORY_REGISTRY

LOW_CONFIDENCE_MARGIN_THRESHOLD = 15.0
"""A composite whose `overall_confidence_margin` exceeds this (on the
same `[0, 100]` axis as every score) is flagged LOW CONFIDENCE in the
recommendation text — a loosely reasoned starting point, same
"starting point, not a validated target" framing as this package's
other threshold constants."""


def recommendation_text(score: HearthBenchScore, model_label: str = "") -> str:
    """A9.4: plain language, honesty-first. Always leads with any real
    disqualification; states low confidence prominently; never states
    a total when nothing was scored."""
    label = f"{model_label}: " if model_label else ""
    if score.total is None:
        return f"{label}No score — nothing was scored this run (categories_missing={score.categories_missing})."

    lines = []
    for dq in score.disqualifications:
        lines.append(
            f"DISQUALIFYING: {dq['category']} scored {dq['actual']:.1f} (below floor {dq['floor']:.1f}) — "
            f"{dq['reason']}. Total capped at {dq['cap']:.1f}."
        )
    confidence_note = ""
    if score.overall_confidence_margin is not None and score.overall_confidence_margin > LOW_CONFIDENCE_MARGIN_THRESHOLD:
        confidence_note = f" LOW CONFIDENCE (±{score.overall_confidence_margin:.1f}, n={score.n_cases_total} cases — widen the sample before trusting this number)."
    elif score.overall_confidence_margin is not None:
        confidence_note = f" (±{score.overall_confidence_margin:.1f}, n={score.n_cases_total} cases)"

    lines.append(f"{label}Score: {score.total:.1f}/100{confidence_note}")
    if score.categories_missing:
        lines.append(f"Not yet measured: {', '.join(score.categories_missing)} (excluded from the total, not scored as zero).")
    return "\n".join(lines)


def export_json(score: HearthBenchScore, path: "str | Path") -> None:
    """A9.2: a plain, complete JSON dump of `score`'s own fields."""
    payload = {
        "total": score.total, "category_scores": score.category_scores,
        "category_confidence_margin": score.category_confidence_margin,
        "categories_used": score.categories_used, "categories_missing": score.categories_missing,
        "weights_used": score.weights_used, "disqualifications": score.disqualifications,
        "overall_confidence_margin": score.overall_confidence_margin,
        "n_cases_total": score.n_cases_total, "rubric_version": score.rubric_version,
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)


def export_csv(score: HearthBenchScore, path: "str | Path") -> None:
    """A9.2: one row per category actually scored, `id,name,score,
    weight_used,confidence_margin`."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["category_id", "category_name", "score", "weight_used", "confidence_margin"])
        for category_id in score.categories_used:
            name = CATEGORY_REGISTRY[category_id].name if category_id in CATEGORY_REGISTRY else category_id
            writer.writerow([
                category_id, name,
                f"{score.category_scores[category_id]:.4f}",
                f"{score.weights_used[category_id]:.4f}",
                "" if score.category_confidence_margin.get(category_id) is None else f"{score.category_confidence_margin[category_id]:.4f}",
            ])


def _find_failure_examples(run_dir: "str | Path", max_examples: int) -> list:
    """A9.1's real failure-example source: any committed `CaseRecord`
    where at least one real scorer's `passed` came back `False`, with
    the actual prompt/completion text resolved through A8's own
    `BlobStore`. Bounded by `max_examples`, first-found order (the
    order cases were committed in — no ranking claimed)."""
    reader = RunRecordReader(run_dir)
    examples = []
    for record in reader.iter_case_records():
        failing = {sid: d for sid, d in (record.scores or {}).items() if d.get("passed") is False}
        if not failing:
            continue
        examples.append({
            "case_id": record.case_id, "category": record.category,
            "prompt": reader.blobs.get(record.prompt_hash) or "",
            "completion": reader.blobs.get(record.completion_hash) or "",
            "failing_scorers": failing,
        })
        if len(examples) >= max_examples:
            break
    return examples


def render_html_report(
    score: HearthBenchScore, run_dir: "str | Path | None" = None,
    model_label: str = "", latency_stats: "dict | None" = None, max_failure_examples: int = 3,
) -> str:
    """A9.1: a self-contained HTML string (write it to a file
    yourself — this function has no I/O of its own beyond A9's real
    failure-example lookup, which only touches `run_dir` when given)."""
    esc = html.escape
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>HearthBench report{' — ' + esc(model_label) if model_label else ''}</title>",
        "<style>body{font-family:sans-serif;max-width:900px;margin:2em auto;color:#222}"
        "table{border-collapse:collapse;width:100%;margin:1em 0}"
        "td,th{border:1px solid #ccc;padding:6px 10px;text-align:left}"
        ".rec{white-space:pre-wrap;background:#f6f6f6;padding:1em;border-radius:6px}"
        ".dq{color:#b00}.example{background:#fff8f8;border:1px solid #e0b0b0;border-radius:6px;padding:1em;margin:0.5em 0}"
        ".example pre{white-space:pre-wrap;word-break:break-word}</style></head><body>",
        f"<h1>HearthBench report{' — ' + esc(model_label) if model_label else ''}</h1>",
        f"<div class='rec'>{esc(recommendation_text(score, model_label))}</div>",
    ]

    parts.append("<h2>Categories</h2><table><tr><th>Category</th><th>Score</th><th>Weight used</th><th>±95% CI</th></tr>")
    for category_id in score.categories_used:
        name = CATEGORY_REGISTRY[category_id].name if category_id in CATEGORY_REGISTRY else category_id
        margin = score.category_confidence_margin.get(category_id)
        parts.append(
            f"<tr><td>{esc(name)}</td><td>{score.category_scores[category_id]:.1f}</td>"
            f"<td>{score.weights_used[category_id]:.2%}</td>"
            f"<td>{'—' if margin is None else f'±{margin:.1f}'}</td></tr>"
        )
    parts.append("</table>")

    if score.categories_missing:
        parts.append("<h2>Not yet measured</h2><p>" + esc(", ".join(score.categories_missing)) + "</p>")

    if latency_stats:
        parts.append("<h2>Latency (raw measurements)</h2><table><tr><th>Metric</th><th>p50</th><th>p95</th><th>max</th><th>mean</th><th>N</th></tr>")
        for metric_name in ("latency_ms", "ttft_ms", "completion_tokens_per_sec"):
            stats = latency_stats.get(metric_name) or {}
            row = [stats.get(k) for k in ("p50", "p95", "max", "mean", "n")]
            cells = "".join(f"<td>{'—' if v is None else (f'{v:.1f}' if isinstance(v, float) else v)}</td>" for v in row)
            parts.append(f"<tr><td>{esc(metric_name)}</td>{cells}</tr>")
        parts.append("</table><p><em>Latency/memory graphs are not built — this project bundles no charting "
                      "library; the numbers above are the real measured data a future chart would render.</em></p>")

    if run_dir is not None:
        examples = _find_failure_examples(run_dir, max_failure_examples)
        if examples:
            parts.append("<h2>Failure examples</h2>")
            for ex in examples:
                failing_names = ", ".join(ex["failing_scorers"].keys())
                parts.append(
                    f"<div class='example'><b>{esc(ex['category'])}</b> "
                    f"<span class='dq'>failed: {esc(failing_names)}</span>"
                    f"<pre><b>Prompt:</b>\n{esc(ex['prompt'])}</pre>"
                    f"<pre><b>Completion:</b>\n{esc(ex['completion'])}</pre></div>"
                )

    parts.append("</body></html>")
    return "".join(parts)


@dataclass
class CategoryComparison:
    category_id: str
    scores: dict = field(default_factory=dict)
    delta_from_baseline: dict = field(default_factory=dict)
    significant_change: dict = field(default_factory=dict)


@dataclass
class ComparisonReport:
    labels: list = field(default_factory=list)
    totals: dict = field(default_factory=dict)
    categories: dict = field(default_factory=dict)


def _intervals_overlap(a_center, a_margin, b_center, b_margin) -> "bool | None":
    if a_margin is None or b_margin is None:
        return None
    a_lo, a_hi = a_center - a_margin, a_center + a_margin
    b_lo, b_hi = b_center - b_margin, b_center + b_margin
    return not (a_hi < b_lo or b_hi < a_lo)


def compare_runs(labeled_scores: list) -> ComparisonReport:
    """A9.3: `labeled_scores` is `[(label, HearthBenchScore), ...]`,
    the FIRST entry treated as the baseline every other entry is
    compared against — real per-category deltas and a real
    significance flag (`True` = confidence intervals genuinely don't
    overlap, `False` = they do (could be noise), `None` = can't tell,
    a real margin is missing on one side)."""
    if not labeled_scores:
        return ComparisonReport()

    labels = [label for label, _ in labeled_scores]
    baseline_label, baseline_score = labeled_scores[0]
    totals = {label: score.total for label, score in labeled_scores}

    all_category_ids = set()
    for _, score in labeled_scores:
        all_category_ids.update(score.categories_used)

    categories = {}
    for category_id in sorted(all_category_ids):
        comp = CategoryComparison(category_id=category_id)
        baseline_value = baseline_score.category_scores.get(category_id)
        baseline_margin = baseline_score.category_confidence_margin.get(category_id)
        for label, score in labeled_scores:
            value = score.category_scores.get(category_id)
            comp.scores[label] = value
            if label == baseline_label:
                continue
            comp.delta_from_baseline[label] = None if (value is None or baseline_value is None) else value - baseline_value
            if value is None or baseline_value is None:
                comp.significant_change[label] = None
            else:
                overlap = _intervals_overlap(
                    baseline_value, baseline_margin, value, score.category_confidence_margin.get(category_id),
                )
                comp.significant_change[label] = None if overlap is None else (not overlap)
        categories[category_id] = comp

    return ComparisonReport(labels=labels, totals=totals, categories=categories)
