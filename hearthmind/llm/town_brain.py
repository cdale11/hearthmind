"""The "town brain": a monthly civic-priority decision — the concrete
expression of "the LLM is the brain of the town" (see CLAUDE.md).
Unlike traditions/festivals/inventions, which are purely narrative-
with-a-side-effect, this decision measurably steers mechanics:
`Settlement.current_priority` feeds `buildings.choose_building_kind`'s
weighting at every future construction founding until the next
monthly decision.

Made deterministic (explicit user directive): "Instead of asking Food?
Health? Construction? Just compute. Highest wins." `compute_priority`
is a plain, legible, ordered read of the settlement's own real numbers
(hunger, illness, coffers, materials, council disposition) — the SAME
priority every time given the same stats, not an LLM impression of
them. The LLM's only remaining job is to write one sentence explaining
the already-decided priority, grounded in the real numbers it's given
— narration, not decision. Player intervention (`POST /intervene/
town-brain`) still folds queued whispers into that narration as one
input, a deliberately subtle nudge, not a command. See docs/
DECISIONS.md, "LLM-as-brain batch."
"""
from __future__ import annotations

_VALID_PRIORITIES = ("growth", "food", "commerce", "education", "health", "defense")

SYSTEM_PROMPT = (
    "You are the quiet civic instinct of a small simulated village — not a "
    "ruler, just the sense of what the village needs most right now. You have "
    "been told the village's ALREADY-DECIDED current priority, computed from "
    "its own real numbers — your only job is to explain it in one sentence, "
    "naming at least one of the actual numbers given, never to choose a "
    "different priority. Beliefs and history are real color for the "
    "explanation but must not override the numbers. "
    'Respond with strict JSON only, no other text: {"rationale": "one '
    'sentence, under 20 words, naming at least one actual number from the '
    'stats given (population, hunger, materials, currency, sick count, or '
    'structure counts)"}.'
)


def build_prompt(
    settlement_name: str, priority: str, recent_events: list[dict], population_summary: dict,
    settlement_summary: dict, player_whispers: list[str], beliefs: list[dict] | None = None,
    council_beliefs: list[dict] | None = None, narrative_theme: str = "", belief_digest: str = "",
    culture_digest: str = "", council_faction_name: str = "", prophecy: dict | None = None,
    known_concepts: list[str] | None = None, recent_goal_counts: dict | None = None,
) -> str:
    lines = [f"- {event['description']}" for event in recent_events]
    events_text = "\n".join(lines) if lines else "Nothing notable happened recently."
    whisper_text = (
        f"\nSome in the village have been murmuring: {'; '.join(player_whispers)}."
        if player_whispers else ""
    )
    # Intelligent summary (llm.beliefs.parse_digest) over the village's
    # FULL current belief set, same treatment as chronicle.py's — a
    # digest reflects everything, where a raw recency slice (`beliefs`,
    # now just the one or two newest) would silently drop the rest.
    digest_text = f"\nThe village's general sense of itself: {belief_digest}" if belief_digest else ""
    # Same treatment as digest_text, but for accumulated culture/history
    # (llm/culture_digest.py's quarterly job) rather than beliefs.
    culture_digest_text = (
        f"\nThe village's general sense of its own history: {culture_digest}" if culture_digest else ""
    )
    beliefs_text = (
        "\nSpecific recent theories: "
        + "; ".join(f"{b['subject']} ({b['belief']})" for b in beliefs)
        + "."
        if beliefs else ""
    )
    # Integration milestone: a sitting council of elders is a second,
    # narrower voice alongside the village's own general theories —
    # its own accumulated civic positions (llm/beliefs.sync_council_
    # beliefs), not a repeat of the settlement-wide belief list. Only
    # present once the council has actually formed an opinion; a
    # freshly-seated council with no beliefs yet says nothing here
    # rather than an empty aside.
    council_text = (
        "\nThe council of elders holds its own views: "
        + "; ".join(f"{b['subject']} ({b['belief']})" for b in council_beliefs)
        + "."
        if council_beliefs else ""
    )
    # v0.87.15 "emergent leadership" (docs/IDEAS-2026-07-EMERGENCE.md
    # §7): a council no longer reads as one neutral civic voice once a
    # single faction holds a majority of its living seats — ambient
    # framing only, this never changes which `_VALID_PRIORITIES` value
    # is available, just colors how "the council's own views" above
    # should be read.
    faction_leaning_text = (
        f"\nThe council of elders is currently dominated by {council_faction_name}."
        if council_faction_name else ""
    )
    # §3 "self-fulfilling prophecy": same "texture, never a required
    # thread" treatment as narrative_theme below — a pending prophecy
    # is offered as one more ambient input the priority MAY lean toward
    # (ominous -> caution, hopeful -> ambition), never a directive.
    prophecy_text = (
        f"\nThere's a half-remembered {prophecy['tone']} saying going around: \"{prophecy['text']}\""
        if prophecy else ""
    )
    # player_standing (Settlement.player_standing) is one more quiet
    # input, same "folded in, never a command" treatment as whispers —
    # only mentioned at all once it's notably warm/cold, and even then
    # phrased as an ambient feeling, not an instruction to act on it.
    # See docs/DECISIONS.md, "town's opinion of the player" pass.
    standing = settlement_summary.get("player_standing", 0.0)
    standing_text = (
        "\nThe village has come to feel genuinely looked-after by whatever quiet hand nudges it."
        if standing > 0.4 else
        "\nThe village has grown a little wary of the outside hand that occasionally nudges it."
        if standing < -0.4 else ""
    )
    # Phase 1 "self-evolving world" (docs/VISION-2026-07-21-
    # SELFEVOLVING.md): established InventedConcepts are real,
    # referenceable history — the concrete proof that ANY system can
    # read what the Innovation Layer has produced, not just narrate
    # around it. Ambient grounding only, same "texture, never a
    # directive" treatment as narrative_theme.
    concepts_text = (
        "\nIdeas the village has come to rely on: " + "; ".join(known_concepts) + "."
        if known_concepts else ""
    )
    # Phase 1.C "self-evolving world": what villagers have actually
    # been DOING lately, not just the settlement's instantaneous
    # numbers — a real NPC-behavior signal `population_summary`/
    # `settlement_summary` don't carry (those are snapshots, this is a
    # trend). Top 3 goals only, most-common first, so a long tail of
    # one-off choices doesn't drown out the real pattern.
    goal_activity_text = ""
    if recent_goal_counts:
        top = sorted(recent_goal_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]
        goal_activity_text = (
            "\nLately, villagers have mostly been: "
            + ", ".join(f"{goal} ({count} times)" for goal, count in top) + "."
        )
    sick_count = population_summary.get("sick_count", 0)
    sickness_text = (
        f", {sick_count} currently ill" if sick_count else ""
    )
    stat_block = (
        f"The village of {settlement_name}: population {population_summary.get('total', 0)} "
        f"(avg hunger {population_summary.get('avg_hunger', 0):.2f}{sickness_text}), "
        f"materials {settlement_summary.get('materials', 0):.1f}/{settlement_summary.get('materials_capacity', 0):.0f}, "
        f"currency {settlement_summary.get('currency', 0):.1f}/{settlement_summary.get('currency_capacity', 0):.0f}, "
        f"education {settlement_summary.get('education_level', 0):.2f}, "
        f"{settlement_summary.get('standing', 0)} standing structures "
        f"({settlement_summary.get('hospitals', 0)} hospitals, {settlement_summary.get('schools', 0)} schools, "
        f"{settlement_summary.get('workshops', 0)} workshops)."
    )
    # P2.5 (docs/AUDIT-2026-07-20.md): a live example showed the model
    # citing the soil belief for its rationale while the objective stat
    # block — materials 1.7/30, 1 structure, 10 ill — sat unused, a
    # page above the actual ask. Small models weight recency; the fix
    # is to restate the stats immediately before the ask instead of
    # trusting the model to look back up past a page of history/
    # beliefs/theme text. Beliefs/history stay exactly where they were
    # (subjective bias is the design, not a bug) — this only ensures
    # the objective numbers are the LAST thing read before the ask, not
    # the first thing forgotten.
    return (
        f"{stat_block}\n"
        f"Recent history:\n{events_text}{whisper_text}{digest_text}{culture_digest_text}{beliefs_text}{council_text}{faction_leaning_text}{standing_text}{prophecy_text}{concepts_text}{goal_activity_text}"
        # Phase M "Narrative Direction": ambient bias only, never a
        # directive — the theme colors how this decision is framed, it
        # never dictates it.
        + (f"\nThe recent theme of village life has been {narrative_theme}." if narrative_theme else "")
        + f"\nThe numbers again, right before you decide: {stat_block}"
        + f"\nThe village's current priority is already decided: {priority}. "
        "Explain why in one sentence, naming at least one of these actual numbers."
    )


COUNCIL_DISPOSITION_TIEBREAK_THRESHOLD = 0.15
"""Integration milestone: how far a sitting council's average trait
must lean before it tips `compute_priority`'s otherwise-arbitrary
final "growth vs. defense" catchall — deliberately small and applied
only at the bottom of the chain (nothing urgent like hunger/illness/
coffers is ever overridden by council mood), same "real but never
dominant" magnitude every other cross-system nudge in this project
uses (temperament's *_INFLUENCE constants, trait step sizes)."""


def compute_priority(
    population_summary: dict, settlement_summary: dict, council_disposition: dict | None = None,
    village_pillar_lean: float = 0.0,
) -> dict:
    """THE decision — not a fallback. "Instead of asking Food? Health?
    Construction? Just compute. Highest wins." A plain, legible,
    ordered read of the settlement's own real numbers (hunger, illness,
    coffers, materials, council disposition), always producing the same
    priority for the same stats. `rationale` here is only ever used as
    the deterministic narration fallback when the LLM call itself can't
    happen — the priority value is authoritative either way."""
    avg_hunger = population_summary.get("avg_hunger", 0.0)
    materials_frac = (
        settlement_summary.get("materials", 0.0) / settlement_summary.get("materials_capacity", 1.0)
        if settlement_summary.get("materials_capacity") else 0.0
    )
    currency_frac = (
        settlement_summary.get("currency", 0.0) / settlement_summary.get("currency_capacity", 1.0)
        if settlement_summary.get("currency_capacity") else 0.0
    )
    deaths_predator = population_summary.get("deaths_predator", 0)
    sick_count = population_summary.get("sick_count", 0)
    total = population_summary.get("total", 0) or 1
    hospitals = settlement_summary.get("hospitals", 0)
    schools = settlement_summary.get("schools", 0)
    granary_food = settlement_summary.get("granary_food", 0.0)
    granary_capacity = settlement_summary.get("granary_capacity", 0.0) or 1.0

    # The empty-granary arm additionally requires people to actually be
    # somewhat hungry: the old bare fill-ratio test locked the fallback
    # onto "food" for entire 30k-tick runs, because the ratio's
    # denominator (total granary capacity) grows with every granary the
    # "food" priority itself causes to be built — a self-reinforcing
    # loop the July 2026 architecture review measured directly. A town
    # with lightly-stocked granaries but well-fed people has no food
    # problem; let the other arms speak.
    if avg_hunger > 0.5 or (
        granary_capacity and granary_food / granary_capacity < 0.2 and avg_hunger > 0.3
    ):
        return {"priority": "food", "rationale": "Too many go hungry — the village needs food security."}
    # A real, measurable illness burden (not just "no hospital yet and a
    # predator once got someone") — sick_count is population.py's
    # disease mechanic (see docs/DECISIONS.md, "population control:
    # disease" pass), so this arm now fires whenever illness is actually
    # spreading, before the food/hunger check would otherwise dominate
    # every season a settlement happens to be lean on granaries too.
    if sick_count / total > 0.05 and hospitals == 0:
        return {"priority": "health", "rationale": "Illness is spreading and there is no hospital to turn to."}
    if deaths_predator > 0 and hospitals == 0:
        return {"priority": "health", "rationale": "No hospital yet, and the village has already lost people to danger."}
    if currency_frac < 0.2:
        return {"priority": "commerce", "rationale": "The village's coffers are thin — commerce would help."}
    if schools == 0 and materials_frac > 0.3:
        return {"priority": "education", "rationale": "There's material to spare and no school yet."}
    if materials_frac < 0.15:
        return {"priority": "growth", "rationale": "Little on hand yet — the basics still need building."}
    # Nothing urgent is pulling the decision either way — this is the
    # one point in the chain where a sitting council's own disposition
    # gets a say (see COUNCIL_DISPOSITION_TIEBREAK_THRESHOLD): an
    # ambitious council leans the village toward growth, a resilience-
    # minded one toward looking after what it already has. Neither
    # reading is "correct" — same real-but-secondary treatment every
    # other trait/temperament nudge in this project gets.
    if council_disposition:
        avg_ambition = council_disposition.get("avg_ambition", 0.0)
        avg_resilience = council_disposition.get("avg_resilience", 0.0)
        if avg_ambition - avg_resilience > COUNCIL_DISPOSITION_TIEBREAK_THRESHOLD:
            return {"priority": "growth", "rationale": "The council of elders is eager to see the village grow."}
        if avg_resilience - avg_ambition > COUNCIL_DISPOSITION_TIEBREAK_THRESHOLD:
            return {"priority": "defense", "rationale": "The council of elders would rather see the village secure than grow further."}
    # Tier 0's first mirror-write -> pillar-AUTHORED-decision conversion
    # (docs/ROADMAP-2026-07-REMAINING.md, item 0's closing note): the
    # Village pillar's own accumulated confidence about growth-leaning
    # vs. safety-leaning subjects gets the SAME bounded, secondary-only
    # say `council_disposition` already has just above — never
    # overriding an urgent arm earlier in this function, only breaking
    # the final catchall tie. `village_pillar_lean` is precomputed by
    # the caller (positive = pillar leans growth, negative = leans
    # safety/caution) via `Pillar.subject_confidence` — a plain read of
    # already-persisted state, so this stays fully deterministic and
    # legible ("just compute, highest wins" and "pillar-authored" are
    # compatible exactly because the lean itself is computed, never a
    # fresh LLM opinion overriding the numbers).
    if village_pillar_lean > COUNCIL_DISPOSITION_TIEBREAK_THRESHOLD:
        return {"priority": "growth", "rationale": "The village's own accumulated sense of itself leans toward growth."}
    if village_pillar_lean < -COUNCIL_DISPOSITION_TIEBREAK_THRESHOLD:
        return {"priority": "defense", "rationale": "The village's own accumulated sense of itself leans toward caution."}
    return {"priority": "defense", "rationale": "The essentials are covered; time to look after the village's safety."}


def parse_rationale(result: dict, fallback: dict) -> str:
    rationale = result.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        rationale = fallback["rationale"]
    return rationale.strip()[:200]
