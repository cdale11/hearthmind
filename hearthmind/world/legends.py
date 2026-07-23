"""A21 "Temporal compression (event->legend->myth)" (docs/MASTERCHECKLIST-
2026-07-22.md, Part A, Stage IV step 30), first slice.

The doc's own worked pipeline shape: "deterministic event-aggregate ->
LLM-narrate-significant -> deterministic-legend-detection -> myth/
tradition pipeline, replacing today's more ad-hoc chronicle/folklore
chain." A prior pass audited `Settlement.folklore` (Phase K's rumor-
condensation mechanism) and found it carries only a bare `{"tale": str}`
per entry — no structured subject/entity reference a deterministic
detector could aggregate against without a fragile text-matching
heuristic. Rather than build one, this module reuses A22's Emergence
API stream (`World.emergence_log`) instead: every entry there already
carries a real `subsystem` tag, a `settlement` name, and an optional
`magnitude` — genuinely structured, already-collected data, not new
raw text.

Deliberately NOT a replacement for folklore/chronicle (the doc's own
"replacing" is aspirational for a full pipeline; this first slice adds
a second, parallel, more selective mechanism rather than touching the
existing one). A "legend" here is rarer and more significant than an
ordinary folk tale: it takes several repeated noteworthy observations
from the SAME subsystem, for the SAME settlement, before the pattern
is legend-worthy — see LEGEND_SUBSYSTEM_THRESHOLD."""
from __future__ import annotations

LEGEND_SUBSYSTEM_THRESHOLD = 5
"""How many of a settlement's recent Emergence API observations must
share the same `subsystem` tag before that recurring pattern becomes
legend-worthy — e.g. five separate disaster-recovery or invention-
adoption observations reads as "this keeps happening here," the real
signal a legend should form around, not a single one-off event
(chronicle/highlights already cover single events)."""

LEGEND_LOOKBACK = 150
"""How many of the most recent `World.emergence_log` entries (world-
wide, all settlements) the deterministic detector considers — bounded
so a very long-running world doesn't re-scan its entire history every
time this fires; `emergence_log` itself is already capped much larger
(`EMERGENCE_LOG_MAX_STORED`), so this is a recency window, not the
storage limit."""


def detect_legend_candidate(
    emergence_log: list[dict], settlement_name: str, already_legendary_subsystems: set[str],
) -> dict | None:
    """Deterministic aggregation step. Scans the most recent
    `LEGEND_LOOKBACK` entries of `emergence_log` for ones tagged with
    this settlement's name, groups them by `subsystem`, and returns the
    first subsystem (in observation order — stable, not scanning-order-
    dependent since dict insertion order follows `emergence_log`'s own
    append order) that both crosses `LEGEND_SUBSYSTEM_THRESHOLD` and
    isn't already in `already_legendary_subsystems` — a subsystem that
    has already produced one legend for this settlement doesn't mint a
    second (first-slice scope limit: `Settlement.legends`' own
    `subsystem` values ARE `already_legendary_subsystems`, so this is a
    simple one-legend-per-subsystem-per-settlement-lifetime rule, no
    extra state needed).

    Returns `None` when nothing qualifies yet — the common case, same
    "most months nothing happens" discipline `llm/folklore.py`'s own
    detector already follows. On a match, returns `{"subsystem": str,
    "summaries": list[str]}` — the raw grounding material for the LLM
    narration step (`llm/legend.py`), not yet a legend itself."""
    recent = emergence_log[-LEGEND_LOOKBACK:]
    by_subsystem: dict[str, list[dict]] = {}
    for entry in recent:
        if entry.get("settlement") != settlement_name:
            continue
        by_subsystem.setdefault(entry["subsystem"], []).append(entry)
    for subsystem, entries in by_subsystem.items():
        if subsystem in already_legendary_subsystems:
            continue
        if len(entries) < LEGEND_SUBSYSTEM_THRESHOLD:
            continue
        return {"subsystem": subsystem, "summaries": [e["summary"] for e in entries]}
    return None
