"""Automatic diagnostics report for a review-pack export (§8, `llm/
review_pack.py`) — explicit live request: "Every exported review pack
should include an automatic diagnostics report... summarizing prompt/
completion lengths, task distribution, topic and personality diversity,
context usage..., duplicate rates, fallback/parse rates, latency, and
historical trends. The goal is to objectively identify simulator
regressions and improvements before manual review."

Pure, read-only, stdlib-only (no numpy — matches this project's
"prefer stdlib when it's a close call" convention, same choice
`SimulationEngine.llm_prompt_stats_summary`'s char-based token estimate
already made). Operates on the SAME raw archive-line dicts `review_
pack.py` already collects for `export_review_pack`/`export_random_
subset` — no second archive scan, no new I/O.

Every field degrades gracefully across a mixed-vintage archive: a line
that predates a given metadata field (`opportunities`, `context_
available`, `outcome`, ...) simply doesn't contribute to that
diagnostic rather than raising or skewing a rate calculation — the same
`.get(...)`-safe discipline `review_pack.py`/`recorder.py` already
apply throughout.
"""
from __future__ import annotations

import re
from collections import Counter


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _numeric_summary(values: list[float]) -> dict | None:
    """avg/median/min/max/p95 over a numeric column — `None` (not a
    dict of zeros) when there's genuinely no data, so a diagnostics
    consumer can tell "no examples" from "examples all measured 0"."""
    values = [v for v in values if isinstance(v, (int, float))]
    if not values:
        return None
    return {
        "avg": round(sum(values) / len(values), 1),
        "median": round(_percentile(values, 0.5), 1),
        "min": round(min(values), 1),
        "max": round(max(values), 1),
        "p95": round(_percentile(values, 0.95), 1),
        "count": len(values),
    }


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _day_bucket(timestamp: float | None) -> str | None:
    if not isinstance(timestamp, (int, float)):
        return None
    import time
    return time.strftime("%Y-%m-%d", time.gmtime(timestamp))


# Context fields tracked for the "context usage" report — matches the
# `structured_input["context_available"]` keys `SimulationEngine`'s
# dialogue call site records (see hearthmind/simulation/engine.py) plus
# a couple of settlement-job-scoped equivalents that show up under
# different key names on other tasks; any key not present on a given
# task's structured_input simply doesn't contribute a rate for it.
CONTEXT_FIELD_CANDIDATES = (
    "pair_history", "settlement_topic", "place", "village_event", "family",
    "beliefs", "lexicon", "memories", "relationships", "weather", "traditions",
)


def _context_usage_for_task(examples: list[dict]) -> dict[str, float] | None:
    counts: dict[str, int] = {}
    denom = 0
    for ex in examples:
        structured = ex.get("layer1_structured_input") or {}
        available = structured.get("context_available")
        if not isinstance(available, dict):
            continue
        denom += 1
        for field in CONTEXT_FIELD_CANDIDATES:
            if available.get(field):
                counts[field] = counts.get(field, 0) + 1
    if denom == 0:
        return None
    return {field: _rate(n, denom) for field, n in counts.items()}


def _topic_diversity_for_dialogue(examples: list[dict]) -> dict | None:
    """Dialogue's `layer4_parsed_output.topic` (never fabricated for a
    fallback, see `dialogue.parse_dialogue`) is the one place a genuine
    LLM-authored subject is recorded per-exchange — this is the direct
    "is the village actually diversifying what it talks about" signal
    the live request asks for, distinct from `opportunities` below
    (which categories of context WERE OFFERED) vs this (what the model
    actually chose to write about)."""
    topics = [
        ex["layer4_parsed_output"]["topic"].strip().lower()
        for ex in examples
        if isinstance(ex.get("layer4_parsed_output"), dict)
        and isinstance(ex["layer4_parsed_output"].get("topic"), str)
        and ex["layer4_parsed_output"]["topic"].strip()
    ]
    if not topics:
        return None
    counts = Counter(topics)
    total = len(topics)
    unique = len(counts)
    top = counts.most_common(10)
    # Repeat rate: how much of the topic volume is soaked up by the
    # single most common topic — the direct "is one narrative
    # dominating" number the live request is worried about (the
    # "recurring themes such as spring rhythm" example).
    dominant_topic, dominant_count = top[0]
    return {
        "total_with_topic": total,
        "unique_topics": unique,
        "unique_ratio": round(unique / total, 4),
        "top_topics": [{"topic": t, "count": c} for t, c in top],
        "dominant_topic": dominant_topic,
        "dominant_topic_share": round(dominant_count / total, 4),
    }


def _opportunity_diversity_for_dialogue(examples: list[dict]) -> dict | None:
    """Which conversation-opportunity categories (`dialogue.
    build_opportunity_candidates`) actually got selected across these
    examples — the "is the selector itself well-balanced" companion to
    `_topic_diversity_for_dialogue` (what got OFFERED vs what the model
    actually wrote about)."""
    counts: Counter = Counter()
    denom = 0
    for ex in examples:
        structured = ex.get("layer1_structured_input") or {}
        opportunities = structured.get("opportunities")
        if not isinstance(opportunities, list):
            continue
        denom += 1
        counts.update(opportunities)
    if denom == 0:
        return None
    return {
        "exchanges_with_opportunity_data": denom,
        "category_share": {cat: _rate(n, denom) for cat, n in counts.most_common()},
    }


def _personality_diversity(examples: list[dict]) -> dict | None:
    """Coarse proxy for "are we hearing from the same handful of NPCs
    over and over": distinct `npc_ids` touched vs total examples with
    any NPC recorded. A low ratio (many examples, few unique NPCs)
    flags an LLM-call-volume imbalance across the core cast worth
    investigating manually — this diagnostic can't see WHY, only THAT."""
    npc_appearances = 0
    unique_npcs: set = set()
    for ex in examples:
        npc_ids = ex.get("npc_ids")
        if not npc_ids:
            continue
        npc_appearances += len(npc_ids)
        unique_npcs.update(npc_ids)
    if npc_appearances == 0:
        return None
    return {
        "unique_npcs_seen": len(unique_npcs),
        "total_npc_appearances": npc_appearances,
        "diversity_ratio": round(len(unique_npcs) / npc_appearances, 4),
    }


# "Context Influence" (explicit user request, "Improve Context
# Utilization" pass): the prompts already supply rich context, but a
# small model's own default instinct is to key off the single loudest
# cue and let the rest go unreflected in its own output. This is the
# measurable counterpart to the prompt-design change in `llm/
# cognition.py` — a cheap, stdlib-only, deliberately approximate lexical
# heuristic (word-overlap between each supplied context thread and the
# model's own free-text output), same "real, if crude" honesty the
# project's other heuristic diagnostics (`_personality_diversity`, topic
# diversity) already carry. It cannot tell whether a reference is
# genuinely load-bearing to the decision or coincidental vocabulary
# overlap — only a real regression signal for "did the output's
# vocabulary touch more than one of the things it was given," tracked
# over time the same way every other diagnostic here is.
_CONTEXT_INFLUENCE_STOPWORDS = frozenset({
    "about", "after", "again", "against", "already", "always", "another",
    "around", "because", "been", "before", "being", "between", "could",
    "doesn't", "during", "each", "even", "ever", "every", "feels",
    "feeling", "felt", "focused", "focus", "from", "gather", "goal",
    "going", "have", "here", "home", "into", "just", "know", "later",
    "life", "like", "little", "live", "lived", "look", "maybe", "might",
    "more", "most", "much", "nearby", "never", "night", "nothing", "often",
    "once", "only", "other", "ought", "over", "people", "perhaps",
    "person", "place", "quite", "rather", "reason", "really", "right",
    "seek", "should", "since", "small", "some", "something", "still",
    "such", "than", "that", "their", "them", "then", "there", "these",
    "they", "thing", "think", "this", "those", "though", "through",
    "time", "today", "toward", "under", "until", "very", "wander",
    "want", "wants", "weather", "week", "were", "what", "when", "where",
    "which", "while", "will", "with", "would", "years",
})
"""Domain-generic/function words filtered out of keyword sets before
overlap checks — words this prompt's own boilerplate sprinkles into
almost every field (weather, seek, wander, gather...) or that carry no
real content on their own. Deliberately conservative (errs toward
excluding a borderline word) since a false "referenced" hit is worse
for this diagnostic's credibility than a missed one."""


def _context_keywords(text: str, min_len: int = 4) -> set[str]:
    words = re.findall(r"[a-zA-Z']+", text.lower())
    return {w for w in words if len(w) >= min_len and w not in _CONTEXT_INFLUENCE_STOPWORDS}


def _context_text_threads(structured_input: dict) -> dict[str, str]:
    """The free-text context fields worth checking for influence —
    non-empty strings, or lists of strings joined into one (e.g.
    `beliefs_about`) — skipping scalars (hunger, energy, agent_id,
    numeric traits/emotions dicts) that were never going to show up as
    shared vocabulary in a first-person sentence."""
    threads: dict[str, str] = {}
    for key, value in structured_input.items():
        if isinstance(value, str) and value.strip():
            threads[key] = value
        elif isinstance(value, list) and value and all(isinstance(v, str) for v in value):
            joined = " ".join(value)
            if joined.strip():
                threads[key] = joined
    return threads


def _context_influence_for_task(examples: list[dict], output_field: str) -> dict | None:
    """Per example: how many DISTINCT supplied context threads share a
    content keyword with the model's own `output_field` text. Only
    scores examples that actually had ≥1 real text thread available AND
    a non-empty output — an example with nothing to synthesize (a
    routine day, no memories/beliefs/plan offered) correctly contributes
    no data point rather than dragging the rate toward zero for a
    situation where synthesis was never possible in the first place."""
    threads_referenced: list[int] = []
    threads_available: list[int] = []
    for ex in examples:
        structured = ex.get("layer1_structured_input")
        output = ex.get("layer4_parsed_output")
        if not isinstance(structured, dict) or not isinstance(output, dict):
            continue
        output_text = output.get(output_field)
        if not isinstance(output_text, str) or not output_text.strip():
            continue
        text_threads = _context_text_threads(structured)
        if not text_threads:
            continue
        output_keywords = _context_keywords(output_text)
        referenced = sum(
            1 for field_text in text_threads.values()
            if output_keywords & _context_keywords(field_text)
        )
        threads_referenced.append(referenced)
        threads_available.append(len(text_threads))
    if not threads_referenced:
        return None
    n = len(threads_referenced)
    return {
        "examples_scored": n,
        "avg_threads_available": round(sum(threads_available) / n, 2),
        "avg_threads_referenced": round(sum(threads_referenced) / n, 2),
        "any_context_reflected_rate": _rate(sum(1 for c in threads_referenced if c >= 1), n),
        "multi_context_synthesis_rate": _rate(sum(1 for c in threads_referenced if c >= 2), n),
    }


_CONTEXT_INFLUENCE_OUTPUT_FIELD = {
    "cognition": "reason",
}
"""Which `layer4_parsed_output` field carries the model's own free-text
reasoning, per task — only tasks with a genuine first-person
explanatory field are scored (cognition's `reason` is the one this
pass targets explicitly). Extend this dict, not the function above, to
score another task later (e.g. a dispute/diplomacy rationale field)."""


def _context_influence(raw_examples: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for task, output_field in _CONTEXT_INFLUENCE_OUTPUT_FIELD.items():
        task_examples = [ex for ex in raw_examples if ex.get("task") == task]
        if not task_examples:
            continue
        scored = _context_influence_for_task(task_examples, output_field)
        if scored:
            result[task] = scored
    return result


def _duplicate_rates(examples: list[dict]) -> dict:
    prompt_hashes = [ex.get("prompt_hash") for ex in examples if ex.get("prompt_hash")]
    structured_hashes = [ex.get("structured_input_hash") for ex in examples if ex.get("structured_input_hash")]

    def _dupe_rate(hashes: list) -> float | None:
        if not hashes:
            return None
        counts = Counter(hashes)
        duplicated = sum(c - 1 for c in counts.values() if c > 1)
        return round(duplicated / len(hashes), 4)

    return {
        "prompt_duplicate_rate": _dupe_rate(prompt_hashes),
        "structured_input_duplicate_rate": _dupe_rate(structured_hashes),
    }


def _historical_trends(examples: list[dict]) -> list[dict]:
    """One row per UTC day present in the archive slice — fallback
    rate, avg prompt tokens, and dialogue topic diversity per day, so a
    reviewer (or a future automated regression check) can see whether
    a config/prompt change moved these numbers, not just their
    all-time average. Sorted chronologically."""
    by_day: dict[str, list[dict]] = {}
    for ex in examples:
        day = _day_bucket(ex.get("timestamp"))
        if day is None:
            continue
        by_day.setdefault(day, []).append(ex)
    rows = []
    for day in sorted(by_day):
        day_examples = by_day[day]
        fallback_count = sum(1 for ex in day_examples if ex.get("fallback_used"))
        prompt_tokens = [
            ex.get("estimated_prompt_tokens") for ex in day_examples
            if isinstance(ex.get("estimated_prompt_tokens"), (int, float))
        ]
        latencies = [
            ex.get("latency_ms") for ex in day_examples if isinstance(ex.get("latency_ms"), (int, float))
        ]
        dialogue_examples = [ex for ex in day_examples if ex.get("task") == "dialogue"]
        topic_diversity = _topic_diversity_for_dialogue(dialogue_examples)
        rows.append({
            "date": day,
            "example_count": len(day_examples),
            "fallback_rate": _rate(fallback_count, len(day_examples)),
            "avg_prompt_tokens": round(sum(prompt_tokens) / len(prompt_tokens), 1) if prompt_tokens else None,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
            "dialogue_unique_topics": topic_diversity["unique_topics"] if topic_diversity else None,
            "dialogue_dominant_topic_share": topic_diversity["dominant_topic_share"] if topic_diversity else None,
        })
    return rows


def compute_diagnostics(raw_examples: list[dict]) -> dict:
    """Computes the full diagnostics report from a list of raw archive
    example dicts (the SAME dicts `review_pack.py` already collected —
    the full internal shape, not the trimmed `REVIEW_PACK_FIELDS`
    subset, since several diagnostics need fields review examples
    deliberately drop, like `npc_ids`/`prompt_hash`)."""
    task_distribution: dict[str, int] = {}
    for ex in raw_examples:
        task = ex.get("task")
        if task:
            task_distribution[task] = task_distribution.get(task, 0) + 1

    prompt_tokens = [ex.get("estimated_prompt_tokens") for ex in raw_examples]
    completion_tokens = [ex.get("estimated_completion_tokens") for ex in raw_examples]
    prompt_chars = [len(ex["layer2_prompt"]) for ex in raw_examples if isinstance(ex.get("layer2_prompt"), str)]
    latencies = [ex.get("latency_ms") for ex in raw_examples]

    fallback_count = sum(1 for ex in raw_examples if ex.get("fallback_used"))
    parse_repaired_count = sum(1 for ex in raw_examples if ex.get("parse_repaired"))

    per_task_fallback: dict[str, dict] = {}
    per_task_latency: dict[str, dict] = {}
    per_task_context_usage: dict[str, dict] = {}
    dialogue_examples: list[dict] = []
    for task, count in task_distribution.items():
        task_examples = [ex for ex in raw_examples if ex.get("task") == task]
        task_fallbacks = sum(1 for ex in task_examples if ex.get("fallback_used"))
        per_task_fallback[task] = {"count": count, "fallback_rate": _rate(task_fallbacks, count)}
        task_latencies = [ex.get("latency_ms") for ex in task_examples]
        latency_summary = _numeric_summary([v for v in task_latencies if isinstance(v, (int, float))])
        if latency_summary:
            per_task_latency[task] = latency_summary
        usage = _context_usage_for_task(task_examples)
        if usage:
            per_task_context_usage[task] = usage
        if task == "dialogue":
            dialogue_examples = task_examples

    return {
        "example_count": len(raw_examples),
        "task_distribution": task_distribution,
        "prompt_length": {
            "estimated_tokens": _numeric_summary(prompt_tokens),
            "chars": _numeric_summary(prompt_chars),
        },
        "completion_length": {
            "estimated_tokens": _numeric_summary(completion_tokens),
        },
        "latency_ms": {
            "overall": _numeric_summary([v for v in latencies if isinstance(v, (int, float))]),
            "per_task": per_task_latency,
        },
        "fallback_rate": {
            "overall": _rate(fallback_count, len(raw_examples)),
            "per_task": per_task_fallback,
        },
        "parse_repaired_rate": {
            "overall": _rate(parse_repaired_count, len(raw_examples)),
        },
        "duplicate_rates": _duplicate_rates(raw_examples),
        "context_usage": {
            "per_task": per_task_context_usage,
        },
        "topic_diversity": {
            "dialogue": _topic_diversity_for_dialogue(dialogue_examples),
        },
        "opportunity_diversity": {
            "dialogue": _opportunity_diversity_for_dialogue(dialogue_examples),
        },
        "personality_diversity": _personality_diversity(raw_examples),
        "context_influence": _context_influence(raw_examples),
        "historical_trends": {
            "daily": _historical_trends(raw_examples),
        },
    }


def _fmt_summary(summary: dict | None, unit: str = "") -> str:
    if not summary:
        return "n/a"
    return (
        f"avg {summary['avg']}{unit}, median {summary['median']}{unit}, "
        f"p95 {summary['p95']}{unit}, max {summary['max']}{unit} (n={summary['count']})"
    )


def diagnostics_to_markdown(diag: dict) -> str:
    """Human-readable counterpart to `diagnostics.json` — the same
    numbers, formatted for a reviewer to skim before opening any actual
    example. Every section degrades to "n/a"/omitted when its
    underlying data isn't present, never a crash or a misleading zero."""
    lines = ["# Hearthmind Review Pack — Diagnostics", ""]
    lines.append(f"**Examples analyzed:** {diag['example_count']}")
    lines.append("")

    lines.append("## Task distribution")
    for task, count in sorted(diag["task_distribution"].items(), key=lambda kv: -kv[1]):
        lines.append(f"- `{task}`: {count}")
    lines.append("")

    lines.append("## Prompt / completion length")
    lines.append(f"- Prompt (estimated tokens): {_fmt_summary(diag['prompt_length']['estimated_tokens'])}")
    lines.append(f"- Prompt (chars): {_fmt_summary(diag['prompt_length']['chars'])}")
    lines.append(f"- Completion (estimated tokens): {_fmt_summary(diag['completion_length']['estimated_tokens'])}")
    lines.append("")

    lines.append("## Latency")
    lines.append(f"- Overall: {_fmt_summary(diag['latency_ms']['overall'], 'ms')}")
    for task, summary in diag["latency_ms"]["per_task"].items():
        lines.append(f"  - `{task}`: {_fmt_summary(summary, 'ms')}")
    lines.append("")

    lines.append("## Fallback / parse-repair rates")
    overall_fb = diag["fallback_rate"]["overall"]
    lines.append(f"- Overall fallback rate: {overall_fb if overall_fb is not None else 'n/a'}")
    for task, row in diag["fallback_rate"]["per_task"].items():
        lines.append(f"  - `{task}`: {row['fallback_rate']} (n={row['count']})")
    parse_rate = diag["parse_repaired_rate"]["overall"]
    lines.append(f"- Parse-repaired rate: {parse_rate if parse_rate is not None else 'n/a'}")
    lines.append("")

    lines.append("## Duplicate rates")
    dupes = diag["duplicate_rates"]
    lines.append(f"- Prompt duplicate rate: {dupes['prompt_duplicate_rate']}")
    lines.append(f"- Structured-input duplicate rate: {dupes['structured_input_duplicate_rate']}")
    lines.append("")

    lines.append("## Context usage (per task, fraction of examples with each context field present)")
    for task, usage in diag["context_usage"]["per_task"].items():
        lines.append(f"- `{task}`:")
        for field, rate in sorted(usage.items(), key=lambda kv: -kv[1]):
            lines.append(f"  - {field}: {rate}")
    lines.append("")

    topic = diag["topic_diversity"]["dialogue"]
    lines.append("## Dialogue topic diversity")
    if topic:
        lines.append(f"- Unique topics: {topic['unique_topics']} / {topic['total_with_topic']} exchanges "
                      f"(ratio {topic['unique_ratio']})")
        lines.append(f"- Dominant topic: \"{topic['dominant_topic']}\" ({topic['dominant_topic_share']*100:.1f}% of exchanges)")
        lines.append("- Top topics: " + ", ".join(f"{t['topic']} ({t['count']})" for t in topic["top_topics"][:5]))
    else:
        lines.append("- n/a (no dialogue examples with a recorded topic)")
    lines.append("")

    opp = diag["opportunity_diversity"]["dialogue"]
    lines.append("## Dialogue conversation-opportunity balance")
    if opp:
        for cat, share in sorted(opp["category_share"].items(), key=lambda kv: -kv[1]):
            lines.append(f"- {cat}: {share}")
    else:
        lines.append("- n/a (no dialogue examples with recorded opportunity selection)")
    lines.append("")

    personality = diag["personality_diversity"]
    lines.append("## Personality / NPC diversity")
    if personality:
        lines.append(f"- Unique NPCs seen: {personality['unique_npcs_seen']}")
        lines.append(f"- Diversity ratio (unique / total appearances): {personality['diversity_ratio']}")
    else:
        lines.append("- n/a")
    lines.append("")

    lines.append("## Context influence (does reasoning reflect the supplied context?)")
    influence = diag.get("context_influence") or {}
    if influence:
        for task, row in influence.items():
            lines.append(f"- `{task}` (n={row['examples_scored']}):")
            lines.append(f"  - Avg context threads available: {row['avg_threads_available']}")
            lines.append(f"  - Avg context threads referenced in output: {row['avg_threads_referenced']}")
            lines.append(f"  - Any-context-reflected rate: {row['any_context_reflected_rate']}")
            lines.append(f"  - Multi-context synthesis rate (≥2 threads): {row['multi_context_synthesis_rate']}")
    else:
        lines.append("- n/a (no scored examples — needs both structured_input text fields and a parsed output field)")
    lines.append("")

    lines.append("## Historical trends (daily)")
    daily = diag["historical_trends"]["daily"]
    if daily:
        lines.append("| date | examples | fallback rate | avg prompt tokens | avg latency ms | dialogue unique topics | dominant topic share |")
        lines.append("|---|---|---|---|---|---|---|")
        for row in daily:
            lines.append(
                f"| {row['date']} | {row['example_count']} | {row['fallback_rate']} | "
                f"{row['avg_prompt_tokens']} | {row['avg_latency_ms']} | "
                f"{row['dialogue_unique_topics']} | {row['dialogue_dominant_topic_share']} |"
            )
    else:
        lines.append("- n/a (no timestamped examples)")
    lines.append("")

    return "\n".join(lines)
