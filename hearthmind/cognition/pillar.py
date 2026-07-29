"""B1 "The Pillar abstraction" (docs/MASTERCHECKLIST-2026-07-22.md,
Part B, Stage II step 4 — "the keystone"): the shape a persistent
conscious entity needs — identity, self-model, world-model (typed
theories distinguishing observation from hypothesis), living memory,
objectives, inbox/outbox — proven against ONE pillar (Nature) before
being replicated across the other four, per the roadmap's own
sequencing ("proving the shape before replicating it four more
times").

This is deliberately NOT the "refactor the ~55 scattered jobs into
acts of five pillars" the checklist's B1 spec ultimately asks for —
that's the rest of Stage II (B2's continuous cognitive cycle, B3's
attention scheduler, B4's inter-pillar bus, B7/B9 generalizing this
shape to Humans/Village/Innovation/Reflection). This pass gives
Nature's existing belief-forming job (`llm/nature_mind.py`,
unchanged) a real persistent structure to write into ALONGSIDE the
untouched `World.nature_beliefs` list every existing consumer already
reads — proof the shape holds against a genuine production call site,
not a standalone demo.

`inbox`/`outbox` are structurally present (B4's typed message
vocabulary, `MESSAGE_KINDS`) but stay empty for Nature — a message
needs a second pillar to send to/receive from, which doesn't exist
until a future step.

Also carries B2 "The continuous cognitive cycle"'s minimal real
implementation: `cycle_stage`/`CYCLE_STAGES`/`working_memory`/
`note_observation`/`set_cycle_stage`. Nature's turn genuinely
alternates between two persisted stops — a cheap `observe` turn
(reads the Emergence API into bounded `working_memory`, zero LLM cost)
and an `interpret` turn (the one real LLM call, which performs
remember/plan/act/reflect synchronously before returning to
`observe`) — see `SimulationEngine._maybe_schedule_nature_mind`.

B1/B2/B3 (this module's `Pillar` shape, the observe/interpret cycle,
and the attention-scheduler backpressure fraction) were generalized
from Nature-only to all five pillars (Village/Humans/Innovation/
Reflection) in a later pass — see `default_village_pillar`/`default_
humans_pillar`/`default_innovation_pillar`/`default_reflection_pillar`
below and `SimulationEngine`'s shared `_pillar_observe_turn`/`_pillar_
interpret_backpressured`/`_pillar_close_cycle` helpers. B8 "Living
memory & consolidation" (roadmap Stage II step 8) followed: `consolidate()`
below, called once per closed cycle via `_pillar_close_cycle`.

B4 "Inter-pillar consciousness bus" (roadmap Stage III step 11) makes
`inbox`/`outbox` real: `send_message`/`receive_message` below are the
mutators, `SimulationEngine._send_pillar_message` is the one call site
that constructs a `make_message()` and drives both sides of a send.
`disagrees_with`/`word_overlap` give "disagreement persists and drives
behavior" a concrete, mechanical definition — two pillars holding
confident, substantially-overlapping-in-subject theories, not a
semantic judgment call — see their own docstrings."""
from __future__ import annotations

import re

_MESSAGE_WORD_RE = re.compile(r"[a-z']+")


def word_overlap(a: str, b: str) -> float:
    """Jaccard word overlap between two lowercased strings — the same
    cheap "is this about the same thing" primitive `llm/beliefs.py`'s
    `is_noop_belief_revision`/`llm/ontology.py`'s near-duplicate check
    already use independently, pulled out here so `Pillar.disagrees_
    with` (B4) doesn't need its own third copy. `0.0` if either string
    has no recognizable words."""
    words_a = set(_MESSAGE_WORD_RE.findall(a.lower()))
    words_b = set(_MESSAGE_WORD_RE.findall(b.lower()))
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)

WORLD_MODEL_STATUSES = ("observation", "hypothesis")
"""Distinguishes a directly-observed fact from a theory the pillar has
formed but not confirmed — B9's "distinguishing observation from
hypothesis" line. Every entry written by an LLM belief-forming job
today is a `hypothesis` (a belief can always turn out wrong); a future
producer that mirrors real Body state verbatim could write
`observation` instead."""

MESSAGE_KINDS = (
    "observation", "question", "theory", "hypothesis", "warning",
    "request", "discovery", "disagreement",
)
"""B4's typed inter-pillar message vocabulary, defined here as the
shared contract every pillar's inbox/outbox will use once a second
pillar exists to send/receive with (a later step)."""


def make_world_model_entry(
    entry_id: int, tick: int, subject: str, belief: str, confidence: float,
    status: str = "hypothesis", source: str = "",
) -> dict:
    """One theory a pillar holds about itself or its domain — same
    subject/belief/confidence/revisable shape `Settlement.beliefs`/
    `World.nature_beliefs` already use, plus the explicit
    observation-vs-hypothesis status B9 asks for."""
    if status not in WORLD_MODEL_STATUSES:
        raise ValueError(f"unknown world-model status {status!r}, expected one of {WORLD_MODEL_STATUSES}")
    return {
        "id": entry_id, "tick": tick, "subject": subject, "belief": belief,
        "confidence": max(0.0, min(1.0, confidence)), "status": status, "source": source,
    }


def make_message(
    message_id: int, tick: int, from_pillar: str, to_pillar: str, kind: str,
    summary: str, data: dict | None = None,
) -> dict:
    """One B4 inter-pillar message. Validates `kind` against the closed
    vocabulary above — same "fail loudly at the producer" discipline as
    `world.emergence.make_observation`."""
    if kind not in MESSAGE_KINDS:
        raise ValueError(f"unknown message kind {kind!r}, expected one of {MESSAGE_KINDS}")
    return {
        "id": message_id, "tick": tick, "from_pillar": from_pillar, "to_pillar": to_pillar,
        "kind": kind, "summary": summary, "data": data or {},
    }


class Pillar:
    """One persistent conscious entity's full state. Plain-dict-backed
    (`to_dict`/`from_dict`), same persistence convention as every other
    World-scoped store — no ORM, no separate schema per pillar type."""

    MEMORY_MAX = 40
    """Hard FIFO safety-net cap on `memory` — should now rarely if ever
    trigger in practice, since `consolidate()` (B8) proactively folds
    entries well before this point; kept as defense-in-depth per the
    standing memory-leak-audit discipline (CLAUDE.md's "Memory-leak
    pattern to audit first") in case a pillar's cycle stalls for a long
    stretch (deferred critical jobs, LLM disabled) and `consolidate()`
    never gets called."""

    MEMORY_CONSOLIDATE_THRESHOLD = 30
    MEMORY_CONSOLIDATE_BATCH = 8
    """B8 "Living memory & consolidation" (docs/MASTERCHECKLIST-2026-07-
    22.md, roadmap Stage II step 8): "consolidate detailed experience
    into higher-level knowledge periodically; forget trivia; ...
    connect into concepts. Keeps years cognitively manageable while
    preserving identity." Deliberately zero-LLM-cost, matching "maximize
    emergence per LLM call" (CLAUDE.md) — a genuine LLM-authored
    summarization would be a real feature but is a call this pass
    doesn't spend; `consolidate()` below folds the oldest `MEMORY_
    CONSOLIDATE_BATCH` raw notes into ONE condensed digest note once
    `memory` reaches `MEMORY_CONSOLIDATE_THRESHOLD` (comfortably under
    `MEMORY_MAX`, so this fires as a real periodic event well before the
    hard cap's blind evict-oldest ever would). This is real forgetting
    (the individual raw notes are gone, not merely capped) plus a literal
    form of "connect into concepts" (several granular notes become one
    higher-level one) — not the full B8 spec (`reinforce`/`reinterpret`,
    which would need per-note salience/access tracking this pass doesn't
    add — flagged as a smaller follow-up, not attempted here)."""

    INBOX_MAX = 8
    OUTBOX_MAX = 8
    """B4 "Inter-pillar consciousness bus": bounded, same standing
    memory-leak-audit discipline as every other list on `Pillar`. A
    message not yet delivered into `working_memory` (see `_pillar_
    observe_turn`) survives across observe turns until it is — this is
    the mechanism "disagreement persists" — but never grows unbounded;
    a genuinely flooded inbox is exactly what B3's attention scheduler
    (priority-scaled backpressure) exists to slow down at the source."""

    DISAGREEMENT_OVERLAP_THRESHOLD = 0.2
    """`disagrees_with`'s Jaccard word-overlap threshold, compared
    against short SUBJECT labels (`"drought"`, `"the harvests"`), not
    full belief sentences — free-text sentences independently phrased
    by two different LLM calls about the same topic routinely overlap
    well under 0.2 even when clearly about the same thing (a live
    smoke test found ~0.1 for "drought and water scarcity" vs. "The
    land is drying, water grows scarce"), while short subject labels
    are both shorter and more likely to share their few actual content
    words. Lower than `llm/beliefs.py`'s `BELIEF_NOOP_REVISION_OVERLAP`
    (0.6, full-sentence, "says essentially the same thing") since
    "about the same subject" is a much weaker bar."""

    WORKING_MEMORY_MAX = 5
    """B2's "bounded attention, working memory" line, taken literally —
    small on purpose (this is "what the pillar is attending to THIS
    cycle," not consolidated knowledge; `memory` is the long-lived
    store, this is scratch space cleared at the end of every cycle)."""

    CYCLE_STAGES = ("observe", "interpret", "remember", "plan", "act", "reflect")
    """B2 "The continuous cognitive cycle": the full named stage
    vocabulary a pillar's turn moves through. Today's Nature
    implementation (`SimulationEngine._maybe_schedule_nature_mind`)
    only branches on two entry points — `observe` (cheap, zero LLM
    cost: reads the Emergence API into `working_memory`) and
    `interpret` (the one real LLM call, which performs remember/plan/
    act/reflect synchronously within its own `apply()` before
    returning `cycle_stage` to `observe`) — the four intermediate
    names are reserved vocabulary for a future pillar whose turn
    genuinely needs to pause between them, not yet exercised as
    separate persisted stops."""

    INITIATED_MESSAGES_MAX = 10
    """C3 "pillars may initiate contact": same bound as `CONVERSATION_
    LOG_MAX` for the same reason — a long-running world's unprompted-
    message history shouldn't grow unbounded."""

    CONVERSATION_LOG_MAX = 10
    """C3 "Player <-> Pillar chat" (roadmap Stage III step 10): "a light
    per-pillar player-model" — bounded so a long-running world's chat
    history doesn't grow unbounded, per the standing memory-leak-audit
    discipline. 10 exchanges is plenty for "does this read as a
    continuing conversation," the only thing `recent_conversation`
    (`llm/pillar_chat.py`) actually needs it for."""

    def __init__(
        self, name: str, description: str = "", self_model: dict | None = None,
        world_model: list[dict] | None = None, memory: list[str] | None = None,
        objectives: list[str] | None = None, inbox: list[dict] | None = None,
        outbox: list[dict] | None = None, next_world_model_id: int = 1, next_message_id: int = 1,
        cycle_stage: str = "observe", working_memory: list[str] | None = None,
        last_turn_tick: int = -1, conversation_log: list[dict] | None = None,
        last_question: str = "", last_answer: str = "", last_answer_tick: int = -1,
        turns_processed: int = 0, memory_access: list[int] | None = None,
        initiated_messages: list[dict] | None = None, last_initiated_tick: int = -1,
    ) -> None:
        self.name = name
        self.description = description
        self.self_model = self_model if self_model is not None else {}
        self.world_model = world_model if world_model is not None else []
        self.memory = memory if memory is not None else []
        self.memory_access = memory_access if memory_access is not None else [0] * len(self.memory)
        """B8's `reinforce`/`reinterpret` half (see `remember()`): an
        access/reinforcement count parallel to `memory`, same index for
        index — kept as a SEPARATE list rather than upgrading `memory`
        entries to dicts, so `memory` itself stays the plain
        `list[str]` every existing consumer (`llm/pillar_chat.py`'s
        prompt builder, `to_dict`'s persisted shape) already expects.
        `0` for a note that has only ever been formed once; every
        `remember()` call that reinforces or reinterprets an existing
        note bumps its count, which `consolidate()` reads to fold the
        LEAST-reinforced notes first instead of blindly the oldest."""
        self.objectives = objectives if objectives is not None else []
        self.inbox = inbox if inbox is not None else []
        self.outbox = outbox if outbox is not None else []
        self.last_turn_tick = last_turn_tick
        """B3 "The Attention Scheduler": the tick this pillar's cycle
        last genuinely advanced (an `observe` read or an `interpret`
        resolution) — `-1` until its first turn. `attention.compute_
        priority`'s staleness input reads `tick_count - last_turn_tick`;
        never written outside `SimulationEngine._maybe_schedule_nature_
        mind`'s cycle-transition points."""
        self.next_world_model_id = next_world_model_id
        self.next_message_id = next_message_id
        self.turns_processed = turns_processed
        """Explicit live-report follow-up ("Nature and especially
        Reflection still feel disconnected... not forming any
        hypothesis even after 13k ticks"): a plain count of real
        season/year boundaries this pillar's cognition job has
        processed since creation (bumped once per resolved observe OR
        interpret turn — see `SimulationEngine._maybe_schedule_nature_
        mind`/`_maybe_schedule_reflection`), independent of `cycle_
        stage`. Exists purely so a diagnostic can answer "how close is
        this pillar to its first real output" (needs 2: one observe,
        one interpret) instead of that cold-start latency being
        silently invisible."""
        self.cycle_stage = cycle_stage if cycle_stage in self.CYCLE_STAGES else "observe"
        self.working_memory = working_memory if working_memory is not None else []
        self.conversation_log = conversation_log if conversation_log is not None else []
        self.last_question = last_question
        self.last_answer = last_answer
        self.last_answer_tick = last_answer_tick
        self.pending = False
        """C3: True from the moment a `/ask/{pillar}` question is
        applied until its answer resolves — same "in-flight state never
        persists" discipline as `World.chronicler_pending`/`sim_
        summary_pending` (see `to_dict`'s comment); always loads back
        `False`, since a generation left in flight at shutdown never
        resolves after restart."""
        self.initiated_messages = initiated_messages if initiated_messages is not None else []
        """C3 "pillars may initiate contact" (docs/ROADMAP-2026-07-
        REMAINING.md): the reverse direction from `conversation_log`
        (which only ever holds a player-asked/pillar-answered pair) —
        an unprompted message this pillar pushed to the player on its
        own initiative, via `push_initiated_message`. Bounded, same
        `INITIATED_MESSAGES_MAX` cap discipline as every other pillar
        list."""
        self.last_initiated_tick = last_initiated_tick
        """The tick of this pillar's own most recent `push_initiated_
        message` call, `-1` until its first — `SimulationEngine._maybe_
        pillar_initiates_contact`'s cooldown gate reads this so a
        pillar can't spam the player every time a fresh high-confidence
        belief happens to form."""

    def note_observation(self, text: str) -> None:
        """B2's `observe` stage: appends one curated observation (a
        real Emergence API entry's summary, not raw state) to
        `working_memory`, capped at `WORKING_MEMORY_MAX` (oldest
        evicted) — bounded attention, not an ever-growing log."""
        self.working_memory.append(text)
        if len(self.working_memory) > self.WORKING_MEMORY_MAX:
            self.working_memory = self.working_memory[-self.WORKING_MEMORY_MAX:]

    def clear_working_memory(self) -> None:
        self.working_memory = []

    def set_cycle_stage(self, stage: str) -> None:
        if stage not in self.CYCLE_STAGES:
            raise ValueError(f"unknown cycle stage {stage!r}, expected one of {self.CYCLE_STAGES}")
        self.cycle_stage = stage

    def find_world_model_entry(self, subject: str) -> dict | None:
        """Exact (case/whitespace-insensitive) subject match, most
        recent first — the lookup a reactive same-subject trigger needs
        before calling `upsert_world_model` so a recurring anomaly
        (e.g. a predator-pack extinction that keeps re-firing as packs
        repeatedly vanish and recolonize) revises its one standing
        entry in place instead of piling up near-duplicate hypotheses
        forever. Deliberately exact-match, not `disagrees_with`'s
        fuzzy substring/overlap check — a caller here already knows
        its own fixed subject string verbatim, so a loose match would
        risk merging two genuinely different anomalies that happen to
        share wording."""
        subject_norm = subject.strip().lower()
        if not subject_norm:
            return None
        for entry in reversed(self.world_model):
            if str(entry.get("subject", "")).strip().lower() == subject_norm:
                return entry
        return None

    def upsert_world_model(
        self, tick: int, subject: str, belief: str, confidence: float,
        status: str = "hypothesis", source: str = "", revises_id: int | None = None,
    ) -> dict:
        """Revise an existing entry by id, or append a new one — mirrors
        the revise-by-index-or-append shape every belief-forming job in
        the codebase already uses, against this pillar's own typed
        `world_model` list instead of a bare dict list."""
        if revises_id is not None:
            existing = next((e for e in self.world_model if e["id"] == revises_id), None)
            if existing is not None:
                existing["belief"] = belief
                existing["confidence"] = max(0.0, min(1.0, confidence))
                existing["subject"] = subject
                existing["status"] = status
                existing["tick"] = tick
                return existing
        entry = make_world_model_entry(self.next_world_model_id, tick, subject, belief, confidence, status, source)
        self.next_world_model_id += 1
        self.world_model.append(entry)
        return entry

    MEMORY_REINFORCE_SCAN = 8
    """`remember()`'s reinforce/reinterpret half only compares a new
    note against this many of the MOST RECENT existing notes, not the
    whole `memory` list — a reinforcement/reinterpretation is "the
    pillar noticing this connects to something on its mind lately," not
    a full-history similarity search (which would also risk merging two
    genuinely unrelated notes that happen to share common words after
    enough entries accumulate)."""

    MEMORY_REINFORCE_OVERLAP = 0.55
    """`remember()`'s Jaccard word-overlap bar for treating a new note
    as a near-restatement of an existing one — same value class as
    `llm/beliefs.py`'s `BELIEF_NOOP_REVISION_OVERLAP` (0.6, "says
    essentially the same thing" over full sentences), fractionally
    lower since memory notes are shorter/more telegraphic than belief
    sentences. At/above this: pure reinforcement — the existing note
    already captures it, so only its `memory_access` count is bumped,
    no duplicate is appended."""

    MEMORY_REINTERPRET_OVERLAP = 0.35
    """Lower bar than `MEMORY_REINFORCE_OVERLAP`: a new note clearly
    about the same subject as a recent one, but phrased differently
    enough to carry real new information (a fuller or updated
    understanding), REPLACES that note's text in place rather than
    reinforcing the old wording or appending a near-duplicate — the
    "reinterpret" half of B8. Below this: genuinely a new, distinct
    memory, appended as usual. `word_overlap` isn't stopword-filtered
    (by design — see its own docstring, shared with `disagrees_with`),
    so two short, GENUINELY UNRELATED full sentences can still cross
    0.2-0.3 purely on shared "a"/"the"/"was"/"to" — empirically checked
    against a batch of deliberately unrelated notes (max observed
    ~0.29) before picking this value, comfortably above that noise
    floor and still below `MEMORY_REINFORCE_OVERLAP`."""

    def remember(self, note: str) -> None:
        """Appends one consolidated-memory note — or, per B8's
        `reinforce`/`reinterpret` (the roadmap's own named remaining
        gap over `consolidate()`'s pure fold-and-forget), strengthens
        or revises an existing recent one instead, when the new note is
        clearly about the same thing:

        - Near-restatement (`>= MEMORY_REINFORCE_OVERLAP`): REINFORCE —
          bump that note's `memory_access` count, keep its wording.
        - Related but distinct (`>= MEMORY_REINTERPRET_OVERLAP`):
          REINTERPRET — replace that note's text with the new one (a
          more current understanding of the same experience), also
          bumping `memory_access`.
        - Otherwise: append as a genuinely new, distinct note.

        Only the most recent `MEMORY_REINFORCE_SCAN` notes are checked,
        newest first, so a fresh but related note always wins over an
        older tangential match. `consolidate()` (B8, called once per
        closed cognitive cycle) is what actually keeps this bounded in
        the common case; `MEMORY_MAX` below is only a defense-in-depth
        hard FIFO cap for the case a pillar's cycle stalls for a long
        stretch and consolidation never runs."""
        window_start = max(0, len(self.memory) - self.MEMORY_REINFORCE_SCAN)
        for i in range(len(self.memory) - 1, window_start - 1, -1):
            overlap = word_overlap(note, self.memory[i])
            if overlap >= self.MEMORY_REINFORCE_OVERLAP:
                self.memory_access[i] += 1
                return
            if overlap >= self.MEMORY_REINTERPRET_OVERLAP:
                self.memory[i] = note
                self.memory_access[i] += 1
                return
        self.memory.append(note)
        self.memory_access.append(0)
        if len(self.memory) > self.MEMORY_MAX:
            self.memory = self.memory[-self.MEMORY_MAX:]
            self.memory_access = self.memory_access[-self.MEMORY_MAX:]

    def record_conversation(self, question: str, answer: str, tick: int) -> None:
        """C3 "Player <-> Pillar chat": appends one Q&A exchange to the
        bounded `conversation_log` ("a light per-pillar player-model")
        and updates `last_question`/`last_answer`/`last_answer_tick`
        (the single most recent exchange, same shape `World.chronicler_
        *` already used for the settlement-scoped predecessor)."""
        self.conversation_log.append({"question": question, "answer": answer, "tick": tick})
        if len(self.conversation_log) > self.CONVERSATION_LOG_MAX:
            self.conversation_log = self.conversation_log[-self.CONVERSATION_LOG_MAX:]
        self.last_question = question
        self.last_answer = answer
        self.last_answer_tick = tick

    def push_initiated_message(self, subject: str, text: str, tick: int, world_model_entry_id: int | None) -> None:
        """C3 "pillars may initiate contact": the pillar-to-player
        direction `record_conversation` doesn't cover — this pillar
        volunteering something unprompted, rather than answering a
        question. Zero new LLM cost by construction: `text` is always
        an already-formed `world_model` belief's own text (see
        `SimulationEngine._maybe_pillar_initiates_contact`), never a
        fresh generation — the mechanism is WHETHER/WHEN to surface an
        existing thought, not authoring a new one. `world_model_entry_
        id` lets the caller dedupe (never re-announce the same belief
        twice) without this method needing to know the dedupe policy
        itself."""
        self.initiated_messages.append({
            "subject": subject, "text": text, "tick": tick, "world_model_entry_id": world_model_entry_id,
        })
        if len(self.initiated_messages) > self.INITIATED_MESSAGES_MAX:
            self.initiated_messages = self.initiated_messages[-self.INITIATED_MESSAGES_MAX:]
        self.last_initiated_tick = tick

    def send_message(self, message: dict) -> None:
        """B4: appends to this pillar's own `outbox` (its sent-message
        record), capped at `OUTBOX_MAX`. Call via `SimulationEngine.
        _send_pillar_message`, which also delivers the same message
        into the recipient's `inbox` via `receive_message` below —
        never call this alone, or the message only ever shows up on
        the sender's side."""
        self.outbox.append(message)
        if len(self.outbox) > self.OUTBOX_MAX:
            self.outbox = self.outbox[-self.OUTBOX_MAX:]

    def receive_message(self, message: dict) -> None:
        """B4: appends to `inbox`, capped at `INBOX_MAX`. A received
        message is NOT immediately consumed — it sits here until this
        pillar's next `observe` turn (`SimulationEngine._pillar_
        observe_turn`) delivers it into `working_memory` alongside
        Emergence API observations, competing for the same bounded
        attention by the same salience ranking. This persistence
        (surviving across ticks until actually attended to) is what
        makes a `disagreement` message genuinely "persist," not just
        fire-and-forget."""
        self.inbox.append(message)
        if len(self.inbox) > self.INBOX_MAX:
            self.inbox = self.inbox[-self.INBOX_MAX:]

    def disagrees_with(self, subject_text: str) -> bool:
        """B4's mechanical definition of "disagreement" — no semantic
        judgment call, just: does this pillar already hold a confident
        (>=0.5) theory whose SUBJECT LABEL substantially overlaps or
        contains/is-contained-by the given incoming subject text? Two
        minds independently forming confident theories about the
        recognizably same thing is disagreement (or at least genuine
        tension) worth surfacing, even without comparing what each
        theory actually SAYS. Compares subjects (short labels like
        `"drought"`), not full belief sentences — see `DISAGREEMENT_
        OVERLAP_THRESHOLD`'s docstring for why."""
        subject_lower = subject_text.strip().lower()
        if not subject_lower:
            return False
        for entry in self.world_model[-6:]:
            if entry.get("confidence", 0.0) < 0.5:
                continue
            existing_subject = str(entry.get("subject", "")).strip().lower()
            if not existing_subject:
                continue
            if existing_subject in subject_lower or subject_lower in existing_subject:
                return True
            if word_overlap(subject_text, existing_subject) >= self.DISAGREEMENT_OVERLAP_THRESHOLD:
                return True
        return False

    def subject_confidence(self, subject_substring: str) -> float:
        """Tier 0's mirror-write -> pillar-AUTHORED-decision conversion
        (docs/ROADMAP-2026-07-REMAINING.md, item 0's own closing note):
        the general, reusable primitive any future settlement job can
        call to let this pillar's own accumulated `world_model` actually
        WEIGH an already-existing decision, not just record its outcome
        afterward. Same mechanical scan-and-match shape `disagrees_with`
        already established (recent entries only, substring/word-overlap
        match on the short SUBJECT label, never comparing full belief
        text) but returns the best-matching entry's own `confidence`
        (0.0 if nothing recent matches) instead of a bool — a bounded
        magnitude a caller can fold into an existing soft/tiebreak
        decision point, deliberately NOT a mechanism for handing a
        pillar a whole decision outright. This keeps every consuming
        site fully deterministic and legible (a plain read of already-
        persisted state, no LLM call in the decision itself) — see
        `town_brain.compute_priority`'s own docstring for why that
        matters at its first consuming site: "just compute, highest
        wins" and "pillar-authored" are compatible exactly because the
        pillar's *lean* is itself computed, never a fresh LLM opinion
        overriding the numbers."""
        subject_lower = subject_substring.strip().lower()
        if not subject_lower:
            return 0.0
        best = 0.0
        for entry in self.world_model[-6:]:
            confidence = entry.get("confidence", 0.0)
            if confidence <= best:
                continue
            existing_subject = str(entry.get("subject", "")).strip().lower()
            if not existing_subject:
                continue
            if (
                existing_subject in subject_lower or subject_lower in existing_subject
                or word_overlap(subject_substring, existing_subject) >= self.DISAGREEMENT_OVERLAP_THRESHOLD
            ):
                best = confidence
        return best

    def consolidate(self) -> bool:
        """B8 "Living memory & consolidation": folds `MEMORY_CONSOLIDATE_
        BATCH` raw notes into one condensed digest note once `memory`
        reaches `MEMORY_CONSOLIDATE_THRESHOLD` — real periodic
        forgetting-of-trivia plus concept-formation, not just a cap. See
        the threshold/batch constants' docstring. Returns True if a
        consolidation actually happened this call (the common no-op case
        below threshold returns False, cheap to call unconditionally).

        Which notes get folded is now `memory_access`-aware (B8's
        `reinforce` half paying off, not just the write side): the
        `MEMORY_CONSOLIDATE_BATCH` notes with the LOWEST access count
        are folded first (ties broken oldest-first), not blindly the
        oldest `MEMORY_CONSOLIDATE_BATCH` regardless of position — a
        note `remember()` has reinforced or reinterpreted survives
        longer than one that was only ever noted once, the same
        "preserving identity" the spec's own language asks for. The
        resulting digest inherits the highest access count among the
        notes it folded, so a digest that absorbed a reinforced note
        isn't itself immediately the next thing folded away."""
        if len(self.memory) < self.MEMORY_CONSOLIDATE_THRESHOLD:
            return False
        order = sorted(range(len(self.memory)), key=lambda i: (self.memory_access[i], i))
        fold = set(order[: self.MEMORY_CONSOLIDATE_BATCH])
        batch = [self.memory[i] for i in range(len(self.memory)) if i in fold]
        batch_access = [self.memory_access[i] for i in range(len(self.memory)) if i in fold]
        remaining = [self.memory[i] for i in range(len(self.memory)) if i not in fold]
        remaining_access = [self.memory_access[i] for i in range(len(self.memory)) if i not in fold]
        digest = f"[{len(batch)} earlier memories, folded together] " + " | ".join(batch)
        self.memory = [digest[:280]] + remaining
        self.memory_access = [max(batch_access, default=0)] + remaining_access
        return True

    def to_dict(self) -> dict:
        return {
            "name": self.name, "description": self.description, "self_model": dict(self.self_model),
            "world_model": [dict(e) for e in self.world_model], "memory": list(self.memory),
            "memory_access": list(self.memory_access),
            "objectives": list(self.objectives), "inbox": [dict(m) for m in self.inbox],
            "outbox": [dict(m) for m in self.outbox],
            "next_world_model_id": self.next_world_model_id, "next_message_id": self.next_message_id,
            "cycle_stage": self.cycle_stage, "working_memory": list(self.working_memory),
            "last_turn_tick": self.last_turn_tick, "turns_processed": self.turns_processed,
            "conversation_log": [dict(c) for c in self.conversation_log],
            "last_question": self.last_question, "last_answer": self.last_answer,
            "last_answer_tick": self.last_answer_tick,
            # `pending` deliberately NOT persisted — same "in-flight
            # state never survives a restart" reasoning as `World.
            # chronicler_pending`/`sim_summary_pending`.
            "initiated_messages": [dict(m) for m in self.initiated_messages],
            "last_initiated_tick": self.last_initiated_tick,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Pillar":
        return cls(
            name=data.get("name", ""), description=data.get("description", ""),
            self_model=dict(data.get("self_model", {})),
            world_model=[dict(e) for e in data.get("world_model", [])],
            memory=list(data.get("memory", [])),
            # Legacy backfill: a snapshot saved before B8's reinforce/
            # reinterpret slice has no `memory_access` at all — default
            # every existing note to 0 (never yet reinforced), same
            # length as `memory` so `remember()`/`consolidate()`'s
            # index-parallel invariant holds from the first tick after
            # load.
            memory_access=list(data["memory_access"]) if "memory_access" in data else [0] * len(data.get("memory", [])),
            objectives=list(data.get("objectives", [])),
            cycle_stage=data.get("cycle_stage", "observe"),
            working_memory=list(data.get("working_memory", [])),
            last_turn_tick=data.get("last_turn_tick", -1),
            turns_processed=data.get("turns_processed", 0),
            inbox=[dict(m) for m in data.get("inbox", [])],
            outbox=[dict(m) for m in data.get("outbox", [])],
            next_world_model_id=data.get("next_world_model_id", 1),
            next_message_id=data.get("next_message_id", 1),
            conversation_log=[dict(c) for c in data.get("conversation_log", [])],
            last_question=data.get("last_question", ""),
            last_answer=data.get("last_answer", ""),
            last_answer_tick=data.get("last_answer_tick", -1),
            initiated_messages=[dict(m) for m in data.get("initiated_messages", [])],
            last_initiated_tick=data.get("last_initiated_tick", -1),
        )


def default_nature_pillar() -> Pillar:
    """Nature's seeded identity/self-model/objectives — genesis-time
    defaults, not LLM-authored (a pillar's sense of what it fundamentally
    is isn't itself a revisable belief the way its `world_model` entries
    are)."""
    return Pillar(
        name="nature",
        description=(
            "The wordless, watching intelligence of the land itself — not a person, "
            "not the village, but the accumulated sense the wilderness has of its own state."
        ),
        self_model={
            "domain": "weather, wildlife, disasters, terrain, the land's own condition",
            "voice": "never speaks as a person; forms impressions, not statements",
        },
        objectives=[
            "notice what threatens or nourishes the land",
            "hold a real, sometimes-wrong sense of its own condition",
        ],
    )


def default_village_pillar() -> Pillar:
    """Village's seeded identity — the settlement's own collective
    self-theory, mirroring `Settlement.beliefs`' existing subject/
    belief/confidence shape (`_maybe_schedule_beliefs`, the same role
    `nature_mind` plays for Nature)."""
    return Pillar(
        name="village",
        description=(
            "The settlement's own slowly-accumulating theory of itself — not any one "
            "person's opinion, but what the community as a whole has come to believe "
            "about its people, its troubles, and its fortunes."
        ),
        self_model={
            "domain": "the settlement's people, institutions, disputes, and civic life",
            "voice": "speaks in terms of the village, never a single named person",
        },
        objectives=[
            "form and revise a real theory about the village's condition",
            "notice what the village is actually living through, not what it wishes were true",
        ],
    )


def default_humans_pillar() -> Pillar:
    """Humans' seeded identity — the collective psychology B7 asks for
    (mood/values/direction), mirroring `Settlement.narrative_themes`
    (computed from `Settlement.mood`, itself the aggregate of living
    agents' own `Agent.emotions` — "individual minds aggregate into
    collective psychology," CLAUDE.md's own framing). `self_model["
    current_protagonists"]` (B7, roadmap Stage III step 14): the
    collective mind's own awareness of which two individuals currently
    carry `Population.voice_pair_ids` — "fold in the voice-pair
    machinery," made real by `SimulationEngine`'s voice-pair-rotation
    site writing here directly and emitting a matching Emergence API
    observation, rather than the two mechanisms staying structurally
    unaware of each other. Per this doc's own standing design decision
    ("when the Humans collective consciousness and an individual NPC
    disagree, who speaks... individual acts locally, collective sets
    the mood/direction they're measured against"): this field is the
    collective's OWN record of who's currently salient, never a
    channel that speaks or acts on an individual's behalf."""
    return Pillar(
        name="humans",
        description=(
            "The felt shape of the village's collective mood — not a single villager's "
            "voice, but what the accumulated feeling of everyone living there is "
            "actually like right now, and the story that feeling seems to be telling."
        ),
        self_model={
            "domain": "the settlement's collective mood and the narrative theme it forms",
            "voice": "names a theme running through recent shared life, never a private thought",
            "current_protagonists": [],
        },
        objectives=[
            "notice the theme the village's collective mood is actually living out",
            "let genuinely new local language emerge when something real deserves a name",
        ],
    )


def default_innovation_pillar() -> Pillar:
    """Innovation's seeded identity — the ontology-origination job
    (`_maybe_schedule_ontology_proposal`) is the closest existing
    analog, mirroring `World.invented_concepts`' name/description/
    category shape into `world_model` (mapped: name -> subject,
    description -> belief)."""
    return Pillar(
        name="innovation",
        description=(
            "The village's capacity to originate something genuinely new — a custom, "
            "a law, a saying, a role, an institution's flavor — grounded in what its "
            "people have actually lived through, not invented from nothing."
        ),
        self_model={
            "domain": "customs, laws, rituals, sayings, professions, institutional flavor",
            "voice": "proposes one concrete new thing at a time, or proposes nothing",
        },
        objectives=[
            "originate something new only when the village's real recent life suggests it",
            "never invent the same thing twice",
        ],
    )


def default_reflection_pillar() -> Pillar:
    """Reflection's seeded identity — the meta-cognitive fifth
    participant (`_maybe_schedule_reflection`) observing the other
    four pillars' Body state and forming falsifiable hypotheses,
    mirroring `World.reflection_notebook`'s subject/content/confidence
    shape into `world_model` (mapped: content -> belief)."""
    return Pillar(
        name="reflection",
        description=(
            "The meta-cognitive intelligence watching all four other pillars' long-term "
            "patterns, not their moment-to-moment state — the part of the town that asks "
            "whether what it believes about itself is actually true."
        ),
        self_model={
            "domain": "cross-pillar patterns in population, culture, ecology, and invention",
            "voice": "proposes falsifiable hypotheses, never asserts certainty",
        },
        objectives=[
            "form a real, testable hypothesis about a genuine cross-pillar pattern",
            "let evidence confirm or refute what it previously believed, honestly",
        ],
    )
