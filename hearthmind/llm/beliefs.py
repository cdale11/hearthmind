"""The town's own evolving theory of itself.

Every other LLM job in this project (town_brain, chronicle, dialogue,
festival, invention, tradition) is essentially stateless: it reads the
current stats/history and produces one answer, with no memory of what it
concluded last time. `beliefs` is the exception — a small, persistent set
of `Settlement.beliefs` entries the LLM itself forms and later *revises*
as new evidence comes in, closing the loop CLAUDE.md calls "cognition as
continuous rather than stateless." A belief is not guaranteed to be
correct; it's the town's interpretation, which can be wrong, outdated, or
superseded, same as a person's own running theory of the people and place
around them.

Fed back into other prompts (town_brain, chronicle) as accumulated
context, so the LLM's own prior interpretations shape its future ones,
not just raw stats — see `SimulationEngine._maybe_schedule_beliefs`.
"""
from __future__ import annotations

from hearthmind.util import clamp
from hearthmind.settlement.institutions import Institution, InstitutionKind

MAX_BELIEFS = 12
"""Cap on `Settlement.beliefs` — the lowest-confidence entry is evicted
when a new one would exceed this, so a long-running world's accumulated
theories stay a curated top-N, not an ever-growing list."""

BELIEF_HISTORY_MAX = 3
"""H2 (docs/ROADMAP.md "Phase H"): a revision used to overwrite a
belief's `belief`/`confidence` in place, silently discarding what the
village used to think. `entry["history"]` (see `push_belief_history`)
keeps the last few superseded versions instead — "revise... imperfect
theories" is more legible when the theory's own past shows through.
Capped small (unlike MAX_BELIEFS itself, this is per-belief and every
active belief already counts against that cap) — enough to see a
theory's arc, not a full audit log."""

INSTITUTION_BELIEF_CAP = 5
"""Per-family cap on `Institution.beliefs` (H2/H3 crossover) — mirrors
MAX_BELIEFS' eviction shape at a smaller scale, since a family is a
much narrower unit than the whole settlement."""

TEMPERAMENT_BELIEF_CONFIDENCE_INFLUENCE = 0.15
"""H8 (docs/ROADMAP.md "Phase H"): the settlement's own `temperament`
(Phase G) subtly colors how starkly it holds a freshly formed/revised
belief — an agitated village (temperament far from 0, either
direction) pushes its current read further from ambivalent (0.5)
rather than toward any particular confidence value, so this never
reads as "good mood = optimistic beliefs," only as "strong mood =
stronger conviction, whatever the theory already leans toward." Same
small-magnitude, permanently-ambiguous, never-labeled treatment every
other Phase G nudge gets (TEMPERAMENT_KILL_CHANCE_INFLUENCE et al.).
See `temperament_confidence_bias`."""


MAX_PERSONAL_BELIEFS = 4
"""Cap on `Agent.beliefs` (H2 extension, docs/ROADMAP.md "Phase H"
stage 2 — "an agent's memories list already carries interpretation; a
personal belief is structurally the same list-of-theories shape as
Settlement.beliefs, just scoped to one agent"). Smaller than
MAX_BELIEFS: a person's own running theories about their life are a
narrower thing than a whole village's accumulated understanding of
itself."""

PERSONAL_SYSTEM_PROMPT = (
    "You are the private, evolving self-understanding of one villager in a small "
    "simulated world — not an outside narrator, but their own quiet running theory "
    "about their life, the people around them, and their place in the village. "
    "Given what they've recently experienced and the theories they already hold, "
    "either sharpen/revise one existing theory with new evidence, or form one new "
    "theory if nothing existing fits. Theories are not guaranteed to be correct — "
    "they can be wrong, one-sided, or later revised, exactly like a real person's "
    "beliefs about their own life. Separately, condense what they've been through "
    "lately into one lasting thought they now carry with them — a distilled "
    "takeaway, not a list of events, the kind of quiet realization a person forms "
    "after several similar experiences (\"I don't trust the river since the flood\"), "
    "not a summary of any single one. Finally, and only rarely (most of the time "
    "leave this blank) — if something in their recent experience suggests they'd be "
    "keeping a private secret, something they wouldn't say aloud, name it briefly. "
    'Respond with strict JSON only, no other text: {"subject": "short label, e.g. '
    'a person\'s name, \'my place here\', \'the harvests\', \'what happened to '
    'them\'", "belief": "one sentence, under 30 words, stated as this villager\'s '
    'own private belief, first-person or about themself in third person, not '
    'narration", "confidence": 0.0-1.0, "revises": integer index of an existing '
    'theory this replaces, or null for a new one, "semantic_memory": "one sentence, '
    'under 25 words, first-person, the lasting thought described above", "secret": '
    '"" (leave blank almost always) or a private secret under 20 words, first-person}.'
)


def build_personal_prompt(
    agent_name: str, recent_memories: list[str], existing_beliefs: list[dict],
    emotion_text: str = "", semantic_memories: list[str] | None = None,
) -> str:
    """Scoped to one agent's own `memories` (already a short personal
    log — bonds formed, rumors heard, a partner's death) rather than
    settlement-wide recent events. Mirrors `build_prompt`'s shape
    exactly (same enumerated-theories block, same closing instruction)
    so the two feel like the same underlying mechanism at two scales.
    `emotion_text`/`semantic_memories` are optional (Phase J, v0.78.0):
    when this agent was chosen because something notable is happening to
    them (see `SimulationEngine._maybe_schedule_personal_belief`'s
    significance-first candidate pick), naming the feeling and any
    standing self-theories already held grounds the reflection in more
    than the bare memory list."""
    memories_text = " | ".join(recent_memories) if recent_memories else "Nothing notable has happened to them lately."
    if existing_beliefs:
        beliefs_text = "\n".join(
            f"  [{i}] (confidence {b['confidence']:.2f}) {b['subject']}: {b['belief']}"
            for i, b in enumerate(existing_beliefs)
        )
    else:
        beliefs_text = "  (none yet — this would be their first private theory)"
    lines = [f"{agent_name}'s recent experiences: {memories_text}"]
    if emotion_text:
        lines.append(f"{agent_name} {emotion_text}")
    if semantic_memories:
        lines.append(f"Lasting thoughts {agent_name} already carries: {' | '.join(semantic_memories)}")
    lines.append(f"Theories {agent_name} already holds about their own life:\n{beliefs_text}")
    lines.append("Form or revise one theory, and distill one lasting thought.")
    return "\n".join(lines)


def fallback_personal_belief(agent_name: str, recent_memories: list[str]) -> dict:
    """Deterministic stand-in, same "real, useful record even without
    the LLM" spirit as `fallback_belief` — reads the agent's most recent
    memory (if any) rather than counting event categories, since a
    personal log is already short and specific."""
    if recent_memories:
        subject = "what's on their mind"
        belief = f"They keep thinking about this: {recent_memories[-1]}"
        semantic_memory = f"I keep thinking about this: {recent_memories[-1]}"
    else:
        subject = "the quiet"
        belief = "Little has happened to them lately — they assume this quiet will hold."
        semantic_memory = "Little has happened lately — I assume this quiet will hold."
    return {
        "subject": subject, "belief": belief, "confidence": 0.4, "revises": None,
        "semantic_memory": semantic_memory,
    }


def temperament_confidence_bias(confidence: float, temperament: float, intensity: float = 1.0) -> float:
    """Nudges `confidence` away from 0.5 by a fraction of the
    settlement's current |temperament| — called once per formed/revised
    belief (`SimulationEngine._maybe_schedule_beliefs`). `intensity` is
    `Config.phase_g_intensity`, same as every other Phase G consumer;
    0.0 leaves confidence untouched."""
    magnitude = abs(temperament) * TEMPERAMENT_BELIEF_CONFIDENCE_INFLUENCE * intensity
    if confidence >= 0.5:
        confidence += magnitude
    else:
        confidence -= magnitude
    return round(clamp(confidence, 0.0, 1.0), 3)

SYSTEM_PROMPT = (
    "You are the quiet, slowly-forming understanding a small simulated village "
    "has of itself — not an outside narrator, but the village's own accumulating "
    "theory of its people, families, traditions, politics, economy, recurring "
    "patterns, and any outside influence it has noticed. Given recent history and "
    "the theories you already hold, either sharpen/revise one existing theory "
    "with new evidence, or form one new theory if nothing existing fits. Theories "
    "are not guaranteed to be correct — they can be wrong, incomplete, or later "
    "revised, exactly like a person's beliefs about their own community. "
    "Separately, looking at ALL of the theories you currently hold together (not "
    "just the one you're forming or revising now), condense their overall shape "
    "into one short digest sentence — the gist of what the village currently "
    "believes about itself as a whole, the way you'd sum up someone's outlook in "
    "one line rather than listing every opinion they hold. "
    'Respond with strict JSON only, no other text: {"subject": "short label, e.g. '
    'a person/family name, \'the harvests\', \'the newcomers\', \'the whispers '
    "from outside'\", \"belief\": \"one sentence, under 30 words, stated as the "
    'village\'s own belief, not narration", "confidence": 0.0-1.0, "revises": '
    'integer index of an existing theory this replaces, or null for a new one, '
    '"digest": "one sentence, under 25 words, summarizing the overall shape of '
    'everything the village currently believes about itself"}.'
)


def build_prompt(
    settlement_name: str, recent_events: list[dict], existing_beliefs: list[dict],
    population_summary: dict, settlement_summary: dict,
) -> str:
    lines = [f"- {event['description']}" for event in recent_events]
    events_text = "\n".join(lines) if lines else "Nothing notable happened recently."
    if existing_beliefs:
        beliefs_text = "\n".join(
            f"  [{i}] (confidence {b['confidence']:.2f}) {b['subject']}: {b['belief']}"
            for i, b in enumerate(existing_beliefs)
        )
    else:
        beliefs_text = "  (none yet — this would be the village's first theory about itself)"
    # Deliberately NO ground-truth stat block here (population counts,
    # structure counts) — unlike town_brain, whose job is to steer well.
    # A theory formed only from what the village *narrated to itself*
    # (event descriptions + its own prior theories) can drift, overshoot,
    # or stay wrong until new events correct it — which is the design
    # goal ("beliefs are allowed to be wrong," CLAUDE.md). Feeding this
    # prompt accurate stats meant beliefs could never meaningfully
    # diverge from reality (July 2026 architecture review, §3.4).
    return (
        f"The village of {settlement_name}, in its {settlement_summary.get('era', 'industrial')} days.\n"
        f"What people have been saying and seeing lately:\n{events_text}\n"
        f"Theories the village already holds about itself:\n{beliefs_text}\n"
        "Form or revise one theory."
    )


def fallback_belief(recent_events: list[dict], existing_beliefs: list[dict], settlement_summary: dict) -> dict:
    """Deterministic stand-in: counts the most common recent-event
    category and states a plain, legible belief about it — same
    "real, useful record even without the LLM" spirit as chronicle's/
    town_brain's fallbacks, not a random pick."""
    counts: dict[str, int] = {}
    for event in recent_events:
        counts[event["category"]] = counts.get(event["category"], 0) + 1
    if counts:
        top_category = max(counts, key=lambda c: counts[c])
        subject = top_category.replace("_", " ")
        belief = f"The village has noticed a run of {subject}-related happenings lately."
    else:
        subject = "the quiet"
        belief = "Little has happened lately — the village assumes this quiet will hold."
    return {"subject": subject, "belief": belief, "confidence": 0.4, "revises": None}


def beliefs_about_agent(agent_id: int, settlement_beliefs: list[dict]) -> list[str]:
    """Settlement-wide theories that resolve to this specific agent
    (directly, or via their family) — `"subject (belief text)"` lines
    ready to drop into a prompt. Shared by dialogue's and cognition's
    prompt-building so both describe "what the village believes about
    you" identically (H2 extension, docs/ROADMAP.md "Phase H") rather
    than each engine call site re-deriving the same filter."""
    return [
        f"{b['subject']} ({b['belief']})" for b in settlement_beliefs
        if b.get("subject_agent_id") == agent_id or agent_id in b.get("subject_family_agent_ids", ())
    ]


def resolve_subject_agent_id(subject: str, agents) -> int | None:
    """If `subject` names a currently-living inhabitant (exact,
    case-insensitive match against `Agent.name`), return their id —
    lets a settlement-wide belief about "Mira" become attributable to
    a specific person without a second, parallel per-agent belief
    store. `agents` is any iterable of objects with `.id`/`.name`.
    Ambiguous on a name collision (two agents share a name): returns
    None rather than guessing, since a wrong attribution is worse than
    none."""
    subject_lower = subject.strip().lower()
    matches = [a for a in agents if a.name.lower() == subject_lower]
    if len(matches) == 1:
        return matches[0].id
    return None


def resolve_family_agent_ids(subject_agent_id: int | None, agents) -> list[int]:
    """Given a belief's resolved `subject_agent_id`, widen it to that
    person's immediate living family — parents, children, and full
    siblings, computed fresh from `Agent.parents` each call rather than
    stored as a separate family-id concept, since membership only makes
    sense among agents currently alive. Returns `[]` if the subject
    itself didn't resolve. This is what makes "the village believes the
    Hallow family is reckless"-shaped free text (still just a string in
    `subject`) mechanically reach every living member of that lineage,
    not only the one name the LLM happened to write — see
    docs/DECISIONS.md, "structured per-family belief resolution" pass.
    `agents` is any iterable of objects with `.id`/`.parents`."""
    if subject_agent_id is None:
        return []
    by_id = {a.id: a for a in agents}
    subject = by_id.get(subject_agent_id)
    if subject is None:
        return []
    family = {subject_agent_id}
    if subject.parents:
        family.update(p for p in subject.parents if p in by_id)
    for agent in agents:
        if agent.parents and subject.parents and agent.parents == subject.parents:
            family.add(agent.id)  # full sibling
        if agent.parents and subject_agent_id in agent.parents:
            family.add(agent.id)  # child of subject
    return sorted(family)


def find_belief_index_by_subject(subject: str, existing_beliefs: list[dict]) -> int | None:
    """Index of the existing belief whose subject matches (exact,
    case-insensitive), or None. Used by the engine when the LLM returns
    a new-belief answer (`revises: null`) whose subject the village
    already holds a theory about — a 2B model frequently re-forms
    instead of revising (or points `revises` at the wrong index), and
    subject identity is a far more reliable signal than a small model's
    integer indexing into the prompt's enumeration (July 2026
    architecture review, §3.3). Ambiguity is impossible: subjects are
    unique under this same merge rule."""
    subject_lower = subject.strip().lower()
    for i, belief in enumerate(existing_beliefs):
        if belief.get("subject", "").strip().lower() == subject_lower:
            return i
    return None


def parse_belief(result: dict, fallback: dict, existing_count: int) -> dict:
    subject = result.get("subject")
    belief = result.get("belief")
    confidence = result.get("confidence")
    revises = result.get("revises")

    if not isinstance(subject, str) or not subject.strip():
        subject = fallback["subject"]
    if not isinstance(belief, str) or not belief.strip():
        belief = fallback["belief"]
    if not isinstance(confidence, (int, float)):
        confidence = fallback["confidence"]
    confidence = clamp(float(confidence), 0.0, 1.0)
    if not isinstance(revises, int) or not (0 <= revises < existing_count):
        revises = None

    return {
        "subject": subject.strip()[:60],
        "belief": belief.strip()[:200],
        "confidence": round(confidence, 3),
        "revises": revises,
    }


def parse_digest(result: dict) -> str:
    """Extracts the settlement-level `digest` field the settlement
    belief job's SYSTEM_PROMPT asks for (distinct from `parse_semantic_
    memory`, which is the personal/agent-level job's own extra field).
    Intelligent summarization instead of blind truncation: `chronicle`/
    `town_brain` used to receive the newest few raw belief entries only
    (`PROMPT_BELIEFS_MAX`), which loses whatever's in the older,
    dropped-from-the-slice beliefs entirely. The digest is written by
    the LLM looking at the FULL current belief set every time this job
    runs (zero added call volume — same field-on-an-existing-call
    discipline `semantic_memory`/`Agent.mind` already established), so
    it can carry the gist of beliefs a raw recency slice would have
    silently dropped. Returns "" (not a fallback string) on anything
    malformed — `SimulationEngine._maybe_schedule_beliefs` only
    overwrites `Settlement.belief_digest` when this is non-empty,
    retaining the previous digest otherwise, same "never silently lose
    a queued value to a flaky LLM stretch" discipline `player_
    influence`/`omen_seed`/`dream_seed` already use — a genuine
    digest earned by a real answer, never a fabricated fallback one."""
    text = result.get("digest")
    if not isinstance(text, str) or not text.strip():
        return ""
    return text.strip()[:180]


def parse_semantic_memory(result: dict, fallback: dict) -> str:
    """Extracts and validates the `semantic_memory` field `parse_belief`
    deliberately doesn't touch (that function is shared with every other
    belief-forming job — settlement/institution — which never asks for
    this field). Falls back to the deterministic stand-in on anything
    malformed, same discipline as every other parse function here."""
    text = result.get("semantic_memory")
    if not isinstance(text, str) or not text.strip():
        text = fallback.get("semantic_memory", "")
    return text.strip()[:150]


def parse_secret(result: dict) -> str:
    """Extracts the optional `secret` field the personal-belief/Reflect()
    job may return (v0.78.4). Unlike `parse_semantic_memory`, there is
    deliberately no fallback here — a deterministic (non-LLM) answer
    should never invent a secret; a used_fallback resolution simply
    plants none, which is the common case even on a live LLM call (most
    calls leave the field blank)."""
    text = result.get("secret")
    if not isinstance(text, str):
        return ""
    return text.strip()[:150]


def push_semantic_memory(agent, text: str) -> None:
    """Appends one condensed self-theory to `Agent.semantic_memories`,
    strictly FIFO-evicted at `MAX_SEMANTIC_MEMORIES` (agents/agent.py) —
    the layer's own module owns the cap constant; this stays a thin
    mutator so the engine's apply() closures don't hand-roll the same
    eviction logic at each call site. No-op on an empty/whitespace-only
    string (a malformed LLM answer that fell through the fallback too)."""
    if not text:
        return
    from hearthmind.agents.agent import MAX_SEMANTIC_MEMORIES
    agent.semantic_memories.append(text)
    if len(agent.semantic_memories) > MAX_SEMANTIC_MEMORIES:
        del agent.semantic_memories[0]


def push_belief_history(entry: dict, tick: int) -> None:
    """H2: called on an existing entry just before a revision overwrites
    `belief`/`confidence`, so the superseded version isn't simply lost.
    Mutates `entry` in place (same convention as the engine's revision
    apply() already uses)."""
    history = entry.setdefault("history", [])
    history.append({
        "belief": entry["belief"], "confidence": entry["confidence"], "revised_tick": tick,
    })
    if len(history) > BELIEF_HISTORY_MAX:
        del history[: len(history) - BELIEF_HISTORY_MAX]


INSTITUTION_SYSTEM_PROMPT = (
    "You are the private, shared understanding of one small group inside "
    "a simulated village — a family, a council of elders, or a trade "
    "guild — not the village at large and not an outside narrator. Given "
    "who belongs to it and what has been happening, either sharpen/revise "
    "one theory the group already holds, or form one new theory from the "
    "group's own narrow point of view (its members, its trade, its "
    "standing, its worries). Group theories are not guaranteed correct "
    "and may contradict what the wider village believes — that is "
    "expected, not an error. "
    'Respond with strict JSON only, no other text: {"subject": "short '
    'label", "belief": "one sentence, under 30 words, stated as the '
    'group\'s own belief", "confidence": 0.0-1.0, "revises": integer '
    "index of an existing theory this replaces, or null for a new one}."
)
"""Institutions Stage 3 (v0.64.0 audit-backlog item): institutions now
*form* beliefs of their own, not only receive mirrored copies of
settlement-wide ones (`sync_family_/council_/guild_beliefs` below stay
untouched as the mirroring path). One institution per month gets its
own formation/revision job (`SimulationEngine._maybe_schedule_
institution_belief`) — its beliefs land in the same `Institution.
beliefs` list the existing consumers already read (council beliefs ->
town-brain prompt, family beliefs -> dialogue context), capped at the
same INSTITUTION_BELIEF_CAP. A group's own theory is allowed to
contradict the village's — the objective/subjective split, one scale
down."""


def build_institution_prompt(
    kind_label: str, member_names: list[str], existing_beliefs: list[dict], recent_events: list[dict],
) -> str:
    """Mirrors `build_prompt`'s enumerated-theories shape at group
    scale. Same deliberate no-ground-truth-stats rule: a group's theory
    forms from what it has seen narrated, so it can drift or stay wrong
    until events correct it."""
    lines = [f"- {event['description']}" for event in recent_events]
    events_text = "\n".join(lines) if lines else "Nothing notable happened recently."
    if existing_beliefs:
        beliefs_text = "\n".join(
            f"  [{i}] (confidence {b['confidence']:.2f}) {b['subject']}: {b['belief']}"
            for i, b in enumerate(existing_beliefs)
        )
    else:
        beliefs_text = "  (none yet — this would be the group's first theory of its own)"
    members = ", ".join(member_names[:6]) if member_names else "nobody still living"
    return (
        f"The group: {kind_label}. Its living members: {members}.\n"
        f"What has been happening around them lately:\n{events_text}\n"
        f"Theories the group already holds:\n{beliefs_text}\n"
        "Form or revise one theory of the group's own."
    )


def fallback_institution_belief(kind_label: str, recent_events: list[dict]) -> dict:
    """Same most-common-category shape as `fallback_belief`, framed from
    the group's own vantage."""
    counts: dict[str, int] = {}
    for event in recent_events:
        counts[event["category"]] = counts.get(event["category"], 0) + 1
    if counts:
        top_category = max(counts, key=lambda c: counts[c])
        subject = top_category.replace("_", " ")
        belief = f"The {kind_label} has taken note of the recent run of {subject}-related happenings."
    else:
        subject = "the quiet"
        belief = f"The {kind_label} expects the current quiet to hold."
    return {"subject": subject, "belief": belief, "confidence": 0.4, "revises": None}


def apply_institution_belief(institution: Institution, parsed: dict, tick: int) -> str:
    """Write a formed/revised own-belief into `institution.beliefs` —
    same revise-by-subject-identity + cap/eviction shape the settlement-
    level apply uses, shared here so engine code stays thin. Returns
    "formed" or "revised" for event logging. Entries carry
    `"origin": "own"` so a mirrored copy (which lacks the key) remains
    distinguishable from a theory the group formed itself."""
    revises = parsed["revises"]
    if revises is None:
        revises = find_belief_index_by_subject(parsed["subject"], institution.beliefs)
    if revises is not None and revises < len(institution.beliefs):
        entry = institution.beliefs[revises]
        push_belief_history(entry, tick)
        entry.update({
            "subject": parsed["subject"], "belief": parsed["belief"],
            "confidence": parsed["confidence"], "tick": tick, "origin": "own",
        })
        return "revised"
    institution.beliefs.append({
        "subject": parsed["subject"], "belief": parsed["belief"],
        "confidence": parsed["confidence"], "tick": tick, "origin": "own",
    })
    if len(institution.beliefs) > INSTITUTION_BELIEF_CAP:
        weakest = min(institution.beliefs, key=lambda b: b.get("confidence", 0.0))
        institution.beliefs.remove(weakest)
    return "formed"


def sync_family_beliefs(entry: dict, institutions: list[Institution]) -> None:
    """H2/H3 crossover: when a settlement-wide belief resolves to a
    living family (`entry["subject_family_agent_ids"]`, from
    `resolve_family_agent_ids`), mirror a small copy of it onto every
    FAMILY institution that overlaps — so "the village believes the
    Hallow family is reckless" is readable from the family's own
    `Institution.beliefs`, not only via a settlement-wide list a future
    consumer would have to filter themselves. Deliberately a *copy*, not
    a shared reference: the settlement's version keeps evolving
    (further revisions, eviction) independently of what a family
    retains. No-op if the belief didn't resolve to any family."""
    family_ids = entry.get("subject_family_agent_ids") or []
    if not family_ids:
        return
    family_set = set(family_ids)
    tick = entry.get("revised_tick", entry.get("formed_tick", 0))
    for inst in institutions:
        if inst.kind is not InstitutionKind.FAMILY or not (inst.member_agent_ids & family_set):
            continue
        copy = {
            "subject": entry["subject"], "belief": entry["belief"],
            "confidence": entry["confidence"], "tick": tick,
        }
        existing = next((b for b in inst.beliefs if b.get("subject") == entry["subject"]), None)
        if existing is not None:
            existing.update(copy)
            continue
        inst.beliefs.append(copy)
        if len(inst.beliefs) > INSTITUTION_BELIEF_CAP:
            weakest = min(inst.beliefs, key=lambda b: b.get("confidence", 0.0))
            inst.beliefs.remove(weakest)


def sync_guild_beliefs(entry: dict, institutions: list[Institution]) -> None:
    """"Continue expanding, round three" (docs/DECISIONS.md): closes the
    one institution kind `sync_family_beliefs`/`sync_council_beliefs`
    never covered — a GUILD (`Institution.name` holds its trade, e.g.
    "farming") gets its own copy of any settlement belief whose text
    actually names that trade, the same "mirroring, not independent
    formation" mechanism families/councils already use, just keyed by
    keyword match against `Institution.name` instead of person/family
    resolution (a guild has no member list a belief could resolve
    through the way `resolve_subject_agent_id` does for people). Real
    independent institution-level belief *formation* (the roadmap's
    still-open "Stage 3") remains a separate, larger future step — this
    is the same scoped mirroring increment as the other two kinds.
    No-op if no GUILD's trade name appears in the belief's text."""
    haystack = f"{entry['subject']} {entry['belief']}".lower()
    tick = entry.get("revised_tick", entry.get("formed_tick", 0))
    for inst in institutions:
        if inst.kind is not InstitutionKind.GUILD or not inst.name:
            continue
        if inst.name.lower() not in haystack:
            continue
        copy = {
            "subject": entry["subject"], "belief": entry["belief"],
            "confidence": entry["confidence"], "tick": tick,
        }
        existing = next((b for b in inst.beliefs if b.get("subject") == entry["subject"]), None)
        if existing is not None:
            existing.update(copy)
            continue
        inst.beliefs.append(copy)
        if len(inst.beliefs) > INSTITUTION_BELIEF_CAP:
            weakest = min(inst.beliefs, key=lambda b: b.get("confidence", 0.0))
            inst.beliefs.remove(weakest)


def sync_council_beliefs(entry: dict, institutions: list[Institution]) -> None:
    """Integration-milestone counterpart to `sync_family_beliefs`: a
    council of elders is a plausible holder of the settlement's *civic*
    theories (the economy, recurring patterns, the outside hand) in the
    same way a family holds personal ones about its own members —
    mirrored here specifically when a belief did NOT resolve to a
    person/family (`sync_family_beliefs` already owns that case), since
    a council's business is the village's affairs in general, not one
    household's. This is what makes town_brain's "the council believes
    X" prompt line (see `llm/town_brain.py`) a real, evolving position
    rather than a re-read of the settlement's own belief list under a
    different label — the council's copy persists and gets curated
    independently (INSTITUTION_BELIEF_CAP) even as the settlement's own
    version keeps revising. No-op if the belief resolved to a person/
    family (that's `sync_family_beliefs`'s case) or no COUNCIL exists
    yet."""
    if entry.get("subject_family_agent_ids"):
        return
    tick = entry.get("revised_tick", entry.get("formed_tick", 0))
    for inst in institutions:
        if inst.kind is not InstitutionKind.COUNCIL:
            continue
        copy = {
            "subject": entry["subject"], "belief": entry["belief"],
            "confidence": entry["confidence"], "tick": tick,
        }
        existing = next((b for b in inst.beliefs if b.get("subject") == entry["subject"]), None)
        if existing is not None:
            existing.update(copy)
            continue
        inst.beliefs.append(copy)
        if len(inst.beliefs) > INSTITUTION_BELIEF_CAP:
            weakest = min(inst.beliefs, key=lambda b: b.get("confidence", 0.0))
            inst.beliefs.remove(weakest)
