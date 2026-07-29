"""FastAPI app factory for the browser interface (Phase F).

Kept separate from `api.py` (the data layer) so the FastAPI/Starlette
dependency is isolated to this one module — `interface/api.py`'s
`WorldBroadcaster` has no framework imports at all, in case the
transport ever needs to change again. See docs/DECISIONS.md, F1/F2.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from hearthmind import __version__
from hearthmind.config import Config
from hearthmind.interface.api import DEFAULT_SPEED_MULTIPLIER, WorldBroadcaster
from hearthmind.world.emergence import PILLARS
from hearthmind.persistence.snapshot import (
    agent_memory_log_count,
    event_category_counts,
    history_events,
    list_snapshot_ticks,
    load_snapshot_at_tick,
    recent_agent_memory_log,
    recent_events,
    recent_metrics,
    snapshot_count,
    total_event_count,
)

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(broadcaster: WorldBroadcaster, conn: sqlite3.Connection, config: Config) -> FastAPI:
    """`conn` is the same connection the engine already holds open for
    the life of the process — reused here rather than opening a second
    one, safe because everything (engine ticks and these async request
    handlers) runs on the same single-threaded asyncio event loop. Only
    ever read from, never written to, from this module."""
    app = FastAPI(title="Hearthmind", docs_url=None, redoc_url=None)

    # Frame-by-frame replay (v0.65.0) re-fetches consecutive snapshot
    # ticks in quick succession; rebuilding a World from its DB row for
    # a tick the player just scrubbed past is pure waste, so the last
    # few built payloads are kept. Small + FIFO-evicted: replay only
    # ever needs the ticks around the playhead, and each entry is a
    # rendered-map dict, not a live World.
    snapshot_payload_cache: dict[int, dict] = {}
    SNAPSHOT_CACHE_MAX = 24

    # `/static/*` assets (app.js, style.css) are fetched by their bare
    # path, and browsers cache static assets aggressively across page
    # loads by default — a stale cached app.js can silently keep serving
    # an old build (missing new features/fixes) even after the server
    # ships a new one, with no visible symptom besides "it doesn't work."
    # Stamping index.html's asset URLs with `?v=<package version>` busts
    # the cache on every release without disabling caching entirely (the
    # same version still caches fine within a session). See
    # docs/DECISIONS.md, UI pass.
    _index_html = (_STATIC_DIR / "index.html").read_text()
    _index_html = _index_html.replace('href="/static/style.css"', f'href="/static/style.css?v={__version__}"')
    _index_html = _index_html.replace('src="/static/app.js"', f'src="/static/app.js?v={__version__}"')

    @app.get("/")
    async def index() -> HTMLResponse:
        return HTMLResponse(_index_html)

    @app.get("/state")
    async def state() -> JSONResponse:
        payload = broadcaster.get_state()
        if payload is None:
            return JSONResponse({"error": "no tick has completed yet"}, status_code=503)
        return JSONResponse(payload)

    @app.get("/terrain")
    async def terrain() -> JSONResponse:
        payload = broadcaster.get_terrain()
        if payload is None:
            return JSONResponse({"error": "terrain not yet available"}, status_code=503)
        return JSONResponse(payload)

    @app.get("/events")
    async def events(limit: int = 50) -> JSONResponse:
        return JSONResponse(recent_events(conn, limit=limit))

    @app.get("/history")
    async def history(limit: int = 200) -> JSONResponse:
        """A summarized town history — founding, naming, era advances,
        chronicle/tradition/invention/festival entries, beliefs formed/
        revised, and omens — filtered out of the everything-included
        live event feed. Backs the UI's History tab."""
        return JSONResponse(history_events(conn, limit=limit))

    @app.get("/agents/{agent_id}/memory_log")
    async def agent_memory_log(agent_id: int, limit: int = 100) -> JSONResponse:
        """An NPC's full durable memory history — main-UI visible per
        explicit user direction (v0.86.3, Constitution §6), unlike the
        dev-console-only `consciousness_log`. `agent.memories`/
        `semantic_memories` in the live `/state` payload only ever show
        the small in-RAM tail; this reaches everything that has ever
        been logged to disk (significant episodic memories once evicted
        past their cap, plus every distilled self-theory), newest first.
        Fetched on demand (not part of the hot broadcast payload) when
        the NPC inspector's "full life history" section is opened."""
        entries = recent_agent_memory_log(conn, agent_id=agent_id, limit=limit)
        return JSONResponse({
            "agent_id": agent_id,
            "total_count": agent_memory_log_count(conn, agent_id=agent_id),
            "entries": entries,
        })

    @app.get("/metrics")
    async def metrics(limit: int = 365) -> JSONResponse:
        """The per-sim-day time-series (population, food, social,
        temperament — see SimulationEngine._log_daily_metrics), oldest-
        first and chart-ready. The research/observatory counterpart to
        `/events`' narrative feed: `/events` says what happened, this
        says how the curves moved. Default window is one sim-year."""
        return JSONResponse(recent_metrics(conn, limit=limit))

    @app.get("/diagnostics")
    async def diagnostics() -> JSONResponse:
        """Extensive, on-demand diagnostic report — built for debugging
        an unattended overnight soak run (see the `⚙ dev` browser
        console's "Full diagnostic report" button): live engine stats
        (tick timing, LLM latency/error breakdown, memory, DB size) plus
        an all-time event-category histogram. See docs/DECISIONS.md,
        diagnostics pass."""
        live = broadcaster.get_full_diagnostics()
        if live is None:
            return JSONResponse({"error": "no tick has completed yet"}, status_code=503)
        return JSONResponse({
            "engine": live,
            "event_category_counts": event_category_counts(conn),
            "total_events_logged": total_event_count(conn),
            "snapshot_rows": snapshot_count(conn),
        })

    @app.get("/knowledge-tree")
    async def knowledge_tree() -> JSONResponse:
        """Vision doc item 3.2, docs/VISION-2026-07-22-LIVINGTERRARIUM.md
        ("What the world learned" ledger) — every LLM-originated
        persistent entity across all four pillars plus Reflection
        (invented concepts, laws/customs/taboos, Reflection hypotheses,
        Nature's beliefs), newest-first, with lineage where it exists.
        See `World.knowledge_tree`."""
        rows = broadcaster.get_knowledge_tree()
        if rows is None:
            return JSONResponse({"error": "no tick has completed yet"}, status_code=503)
        return JSONResponse(rows)

    @app.get("/causal-threads")
    async def causal_threads() -> JSONResponse:
        """Vision doc item 3.3, docs/VISION-2026-07-22-LIVINGTERRARIUM.md
        ("Legible causal threads") — newest-first grounding-fact chains
        behind recent dispute/feud outcomes. See `World.causal_threads_
        list`."""
        rows = broadcaster.get_causal_threads()
        if rows is None:
            return JSONResponse({"error": "no tick has completed yet"}, status_code=503)
        return JSONResponse(rows)

    @app.get("/emergence")
    async def emergence_log() -> JSONResponse:
        """A22 "The Emergence API", docs/MASTERCHECKLIST-2026-07-22.md —
        newest-first curated, kind/pillar-tagged observations from the
        deterministic Body layer. See `World.emergence_log_recent`."""
        rows = broadcaster.get_emergence_log()
        if rows is None:
            return JSONResponse({"error": "no tick has completed yet"}, status_code=503)
        return JSONResponse(rows)

    @app.get("/snapshots")
    async def snapshots() -> JSONResponse:
        """Observatory UI depth pass: which past ticks a snapshot still
        exists for (newest-first) — the scrub-through-time timeline's
        index. Backs the UI's Timeline panel; see `GET /snapshots/
        {tick}` for a specific past state."""
        return JSONResponse(list_snapshot_ticks(conn))

    @app.get("/snapshots/{tick}")
    async def snapshot_at(tick: int) -> JSONResponse:
        """A curated, read-only look at the world as it was at a past
        snapshot tick — settlement/population summaries and the sim
        calendar, the same shape `/state` already gives for the *live*
        world, not the full agent/terrain payload. Reconstructing a
        `World` from a stored snapshot never touches or advances the
        live engine (it's a separate object built from the DB row, not
        `broadcaster`'s world) — this is genuinely read-only, a first,
        deliberately small step on docs/ROADMAP.md's flagged "a true
        scrub-through-time replay view" gap, not a rewind/undo
        feature."""
        cached = snapshot_payload_cache.get(tick)
        if cached is not None:
            return JSONResponse(cached)
        world = load_snapshot_at_tick(conn, tick, config)
        if world is None:
            return JSONResponse({"error": f"no snapshot on file for tick {tick}"}, status_code=404)
        payload = {
            "tick": world.clock.tick_count,
            "day": world.clock.day_of_year,
            "month": world.clock.month_name,
            "year": world.clock.year,
            "season": world.clock.season,
            "settlement": world.settlement.summary(),
            "settlements": [
                {"id": s.id, "name": s.name, "center": s.center()}
                for s in world.settlements
            ],
            "population": world.population.summary(),
            # Timeline v2 (v0.64.0): enough to actually *render* the past
            # map — the terrain as it was (snapshots carry the full
            # terrain, so past floods/deforestation/climate drift show
            # correctly), plus lightweight positions. Only built
            # on-demand for the specific scrubbed/replayed tick, never
            # part of the per-tick payload. Multi-settlement (v0.65.0):
            # physical layers merge across every settlement of that era.
            "map": {
                "width": world.config.width,
                "height": world.config.height,
                "biomes": [[tile.biome.value for tile in row] for row in world.terrain],
                "buildings": [
                    {"x": b.x, "y": b.y, "kind": b.kind.value, "stage": b.stage.value}
                    for s in world.settlements for b in s.buildings
                ],
                "agents": [[a.x, a.y] for a in world.population.agents],
                "farms": [
                    {"x": p.x, "y": p.y, "stage": p.stage.value}
                    for p in world.farms.plots.values()
                ],
                "memorials": [m for s in world.settlements for m in s.memorials],
                "labels": [
                    {"name": s.name, "center": s.center()}
                    for s in world.settlements if s.name and s.center() is not None
                ],
            },
        }
        snapshot_payload_cache[tick] = payload
        while len(snapshot_payload_cache) > SNAPSHOT_CACHE_MAX:
            snapshot_payload_cache.pop(next(iter(snapshot_payload_cache)))
        return JSONResponse(payload)

    @app.post("/intervene/agent-goal")
    async def intervene_agent_goal(payload: dict) -> JSONResponse:
        """Nudge one agent's goal — queued for the engine's next tick,
        applied the same way LLM cognition applies a goal decision. See
        docs/DECISIONS.md, interventions pass."""
        agent_id, goal = payload.get("agent_id"), payload.get("goal")
        if agent_id is None or goal is None:
            return JSONResponse({"error": "agent_id and goal are required"}, status_code=400)
        broadcaster.enqueue_intervention({
            "type": "agent_goal", "agent_id": agent_id, "goal": goal, "reason": payload.get("reason", ""),
        })
        return JSONResponse({"queued": True})

    @app.post("/intervene/settlement")
    async def intervene_settlement(payload: dict) -> JSONResponse:
        """Nudge the settlement's shared stockpiles by a delta (positive
        or negative), clamped to capacity/zero by the engine. Optional
        `settlement_id` targets a specific settlement (the UI's active
        one) in a multi-settlement world; omitted/unknown falls back to
        the founding settlement, the old single-settlement behavior."""
        item = {
            "type": "settlement_resources",
            "materials": payload.get("materials", 0.0),
            "currency": payload.get("currency", 0.0),
        }
        if "settlement_id" in payload:
            item["settlement_id"] = payload["settlement_id"]
        broadcaster.enqueue_intervention(item)
        return JSONResponse({"queued": True})

    @app.post("/intervene/weather")
    async def intervene_weather(payload: dict) -> JSONResponse:
        """Nudge current weather directly — any subset of
        temperature_c/precipitation/wind/is_snowing. Weather keeps
        evolving naturally from the nudged values afterward (see
        world/weather.py's smoothing), it isn't pinned."""
        broadcaster.enqueue_intervention({"type": "weather", **payload})
        return JSONResponse({"queued": True})

    @app.post("/intervene/town-brain")
    async def intervene_town_brain(payload: dict) -> JSONResponse:
        """The deliberately subtle player-influence channel: a short
        text "whisper" folded into the LLM brain's next civic-priority
        decision as one input among the real settlement stats/history —
        not a command it's forced to obey. See docs/DECISIONS.md,
        "LLM-as-brain batch." Optional `settlement_id` targets a
        specific settlement (the UI's active one); omitted/unknown
        falls back to the founding settlement — fixes a bug where a
        whisper submitted while viewing a non-founding settlement always
        landed on the founding one instead, so it could sit unread for
        many months in a multi-settlement world (see docs/DECISIONS.md,
        "whisper routing fix")."""
        text = str(payload.get("text", "")).strip()
        if not text:
            return JSONResponse({"error": "text is required"}, status_code=400)
        item = {"type": "town_influence", "text": text}
        if "settlement_id" in payload:
            item["settlement_id"] = payload["settlement_id"]
        broadcaster.enqueue_intervention(item)
        return JSONResponse({"queued": True})

    @app.get("/recorder/status")
    async def recorder_status() -> JSONResponse:
        """Permanent LLM training recorder status (llm/recorder.py, §8) —
        reads the same `training_recorder` key already carried on every
        tick's broadcast payload (`SimulationEngine._diagnostics_
        snapshot`), so this is a cheap poll, not a fresh computation."""
        payload = broadcaster.get_state()
        recorder = (payload or {}).get("diagnostics", {}).get("training_recorder")
        if recorder is None:
            return JSONResponse({"error": "no tick has completed yet"}, status_code=503)
        return JSONResponse(recorder)

    @app.post("/recorder/start")
    async def recorder_start(payload: dict) -> JSONResponse:
        """OFF by default (spec: "Recording MUST be OFF by default") —
        only starts recording when this is explicitly called, from the
        UI's Recorder panel or a direct API call. Queued through the
        same intervention seam every other `/intervene/*` endpoint uses
        (`_apply_intervention`'s `recorder_start` branch) so the engine's
        tick loop remains the only thing that mutates simulation-adjacent
        state — recording state included."""
        item = {
            "type": "recorder_start",
            "session_name": payload.get("session_name"),
            "policy": payload.get("policy", "all_tasks"),
            "selected_tasks": payload.get("selected_tasks"),
            "sample_rate": payload.get("sample_rate", 0.1),
            "tags": payload.get("tags"),
        }
        broadcaster.enqueue_intervention(item)
        return JSONResponse({"queued": True})

    @app.post("/recorder/stop")
    async def recorder_stop() -> JSONResponse:
        broadcaster.enqueue_intervention({"type": "recorder_stop"})
        return JSONResponse({"queued": True})

    @app.post("/recorder/export-review-pack")
    async def recorder_export_review_pack(payload: dict) -> JSONResponse:
        """Builds a self-contained review-pack ZIP on demand (spec:
        "Implement lightweight exports for AI review") from the on-disk
        JSONL archive — reads directly off disk, not through the engine,
        since this is a read-only export over already-written data.
        Filters: task, date range (from/to, ISO date strings), limit."""
        from hearthmind.llm.review_pack import export_review_pack

        archive_dir = config.recorder_archive_dir
        try:
            zip_path = export_review_pack(
                archive_dir,
                task=payload.get("task"),
                date_from=payload.get("date_from"),
                date_to=payload.get("date_to"),
                limit=int(payload.get("limit", 500)),
                markdown=bool(payload.get("markdown", False)),
            )
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"path": str(zip_path), "filename": Path(zip_path).name})

    @app.get("/recorder/download")
    async def recorder_download(path: str):
        """Serves a previously-exported review pack ZIP by path (must
        live under `config.recorder_archive_dir` — path-traversal guard
        below) so the browser UI's export button can trigger a real
        file download rather than just returning a server-side path."""
        from fastapi.responses import FileResponse

        archive_root = Path(config.recorder_archive_dir).resolve()
        candidate = Path(path).resolve()
        if archive_root not in candidate.parents and candidate != archive_root:
            return JSONResponse({"error": "invalid path"}, status_code=400)
        if not candidate.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(candidate, filename=candidate.name)

    @app.get("/summary")
    async def summary() -> JSONResponse:
        """The most recent on-demand LLM-authored simulation summary
        (see `POST /summary/request`) — reads `World.sim_summary_*` off
        the same broadcast payload `/state` already serializes (`world.
        summary()`'s `sim_summary` key), so this never touches the
        engine directly. `pending=True` while a requested generation is
        in flight; the UI polls this until it clears."""
        payload = broadcaster.get_state()
        if payload is None:
            return JSONResponse({"error": "no tick has completed yet"}, status_code=503)
        return JSONResponse(payload.get("summary", {}).get("sim_summary", {"text": "", "tick": -1, "pending": False}))

    @app.post("/summary/request")
    async def request_summary() -> JSONResponse:
        """Queue an on-demand LLM summary of the current simulation
        state — applied the engine's next tick (same enqueue-now/apply-
        next-tick seam as every other intervention), then generated
        async like any other settlement-level LLM job. See
        SimulationEngine._schedule_summary."""
        broadcaster.enqueue_intervention({"type": "request_summary"})
        return JSONResponse({"queued": True})

    @app.get("/chronicler")
    async def chronicler_state() -> JSONResponse:
        """The most recent Ask-the-Chronicler question/answer (§3
        "Closing meaning loops," docs/IDEAS-2026-07-EMERGENCE.md) —
        reads `World.chronicler_*` off the same broadcast payload
        `/summary` already reads `sim_summary_*` from. `pending=True`
        while a requested answer is in flight; the UI polls this until
        it clears."""
        payload = broadcaster.get_state()
        if payload is None:
            return JSONResponse({"error": "no tick has completed yet"}, status_code=503)
        return JSONResponse(
            payload.get("summary", {}).get(
                "chronicler", {"question": "", "answer": "", "tick": -1, "pending": False},
            )
        )

    @app.post("/ask-chronicler")
    async def ask_chronicler(payload: dict) -> JSONResponse:
        """Queue an on-demand, subjective in-fiction answer from the
        settlement's chronicler — same enqueue-now/apply-next-tick seam
        as `POST /summary/request`. See SimulationEngine._schedule_
        chronicler_answer for why the answer is built only from the
        village's own narrative material, never ground-truth stats."""
        question = str(payload.get("question", "")).strip()
        if not question:
            return JSONResponse({"error": "question is required"}, status_code=400)
        item = {"type": "ask_chronicler", "question": question}
        if "settlement_id" in payload:
            item["settlement_id"] = payload["settlement_id"]
        broadcaster.enqueue_intervention(item)
        return JSONResponse({"queued": True})

    @app.get("/pillar/{pillar}")
    async def pillar_state(pillar: str) -> JSONResponse:
        """C3 "Player <-> Pillar chat" (roadmap Stage III step 10): the
        most recent question/answer for one cognitive pillar — same
        `{question, answer, tick, pending}` shape as `GET /chronicler`,
        read off `payload["summary"]["pillars"][pillar]` (see `World.
        summary()`)."""
        if pillar not in PILLARS:
            return JSONResponse({"error": f"unknown pillar {pillar!r}, expected one of {list(PILLARS)}"}, status_code=404)
        payload = broadcaster.get_state()
        if payload is None:
            return JSONResponse({"error": "no tick has completed yet"}, status_code=503)
        pillars = payload.get("summary", {}).get("pillars", {})
        return JSONResponse(
            pillars.get(pillar, {"question": "", "answer": "", "tick": -1, "pending": False, "initiated_messages": []}),
        )

    @app.post("/ask/{pillar}")
    async def ask_pillar(pillar: str, payload: dict) -> JSONResponse:
        """Queue an on-demand, subjective in-fiction answer from ONE
        cognitive pillar — the C3 generalization of `POST /ask-
        chronicler` to any of the five pillars (Nature today; Village/
        Humans/Innovation/Reflection answer from their own real state
        too, since B1's generalization gave every pillar the same
        self_model/world_model/memory shape). Same enqueue-now/apply-
        next-tick seam. See `SimulationEngine._schedule_pillar_answer`
        for why the answer is built only from the pillar's own
        persistent state, never raw World/Settlement stats."""
        if pillar not in PILLARS:
            return JSONResponse({"error": f"unknown pillar {pillar!r}, expected one of {list(PILLARS)}"}, status_code=404)
        question = str(payload.get("question", "")).strip()
        if not question:
            return JSONResponse({"error": "question is required"}, status_code=400)
        broadcaster.enqueue_intervention({"type": "ask_pillar", "pillar": pillar, "question": question})
        return JSONResponse({"queued": True})

    @app.post("/advisory/{advisory_id}/review")
    async def review_advisory(advisory_id: int, payload: dict) -> JSONResponse:
        """B6 "Reflection as meta-scientist" (roadmap Stage III step
        13): the ONLY way an `advisory_proposals` entry's `status`
        changes — a human marking it `accepted`/`rejected`. Never
        auto-applied to any real mechanic; this is advice logged for a
        person to act on outside the simulation. Dev-console-only
        surfacing today (`World.advisory_proposals` reachable via
        `/diagnostics`), same depth as `self_tuning_actions`."""
        status = str(payload.get("status", "")).strip()
        if status not in ("accepted", "rejected"):
            return JSONResponse({"error": "status must be 'accepted' or 'rejected'"}, status_code=400)
        broadcaster.enqueue_intervention({"type": "review_advisory", "advisory_id": advisory_id, "status": status})
        return JSONResponse({"queued": True})

    @app.get("/digest")
    async def away_digest() -> JSONResponse:
        """§5 "While you were away" digest (docs/IDEAS-2026-07-
        EMERGENCE.md) — reads `World.away_digest_*` off the same
        broadcast payload `/summary`/`/chronicler` already read their
        own on-demand state from. `pending=True` while a requested
        digest is in flight; the UI polls this until it clears."""
        payload = broadcaster.get_state()
        if payload is None:
            return JSONResponse({"error": "no tick has completed yet"}, status_code=503)
        return JSONResponse(
            payload.get("summary", {}).get(
                "away_digest",
                {"text": "", "tick": -1, "since_tick": -1, "pending": False, "highlights": []},
            )
        )

    @app.get("/highlights")
    async def highlights() -> JSONResponse:
        """§5 "Anomaly/highlight log" (docs/IDEAS-2026-07-EMERGENCE.md)
        — the simulation's own bounded self-flagged log of notable
        moments (`World.highlights`), newest-last off the same
        broadcast payload every other summary field reads from."""
        payload = broadcaster.get_state()
        if payload is None:
            return JSONResponse({"error": "no tick has completed yet"}, status_code=503)
        rows = payload.get("summary", {}).get("highlights", [])
        return JSONResponse(list(reversed(rows)))

    @app.post("/digest/request")
    async def request_digest() -> JSONResponse:
        """Queue an on-demand "while you were away" recap covering
        events since the previous digest (or world start, the first
        time) — same enqueue-now/apply-next-tick seam as `POST /summary/
        request`. See SimulationEngine._schedule_away_digest."""
        broadcaster.enqueue_intervention({"type": "request_digest"})
        return JSONResponse({"queued": True})

    @app.post("/world/found-successor")
    async def found_successor_world() -> JSONResponse:
        """§5 "Ruins mode / successor worlds" (docs/IDEAS-2026-07-
        EMERGENCE.md) — queues a `found_successor_world` intervention,
        applied the engine's next tick (same enqueue-now/apply-next-tick
        seam as every other intervention). Only takes effect if the
        population is currently truly extinct (SimulationEngine._found_
        successor_world checks and logs a `successor_founding_refused`
        event otherwise, since a `POST` response here can't reflect a
        result that hasn't been computed yet)."""
        broadcaster.enqueue_intervention({"type": "found_successor_world"})
        return JSONResponse({"queued": True})

    @app.post("/observer/attention")
    async def observer_attention(payload: dict) -> JSONResponse:
        """§4 "observer attention as a signal into the Town
        Consciousness" (docs/IDEAS-2026-07-EMERGENCE.md) — fired by the
        frontend's NPC inspector whenever it opens on an agent. Zero LLM
        cost: queued through the same enqueue-now/apply-next-tick seam
        as every other intervention, applied as a plain bounded counter
        update (`SimulationEngine._record_observer_attention`), never a
        scheduled job. All data stays local to this world's own save
        file — nothing about the observer leaves this process."""
        agent_id = payload.get("agent_id")
        if agent_id is None:
            return JSONResponse({"error": "agent_id is required"}, status_code=400)
        broadcaster.enqueue_intervention({"type": "observer_attention", "agent_id": agent_id})
        return JSONResponse({"queued": True})

    @app.post("/intervene/sim-speed")
    async def intervene_sim_speed(payload: dict) -> JSONResponse:
        """Live pause/speed control — deliberately applied immediately
        (not queued through `enqueue_intervention`) since it never
        touches `World` state, only the engine's own tick pacing; see
        `WorldBroadcaster`'s pause/speed fields for why queuing would
        deadlock a paused sim. `action` is one of "pause", "resume",
        "speed_up", "speed_down", "reset", or "set" (with an explicit
        "multiplier"). speed_up/speed_down double/halve the current
        multiplier, clamped to [MIN_SPEED_MULTIPLIER,
        MAX_SPEED_MULTIPLIER]."""
        action = str(payload.get("action", "")).strip().lower()
        if action == "pause":
            broadcaster.set_paused(True)
        elif action == "resume":
            broadcaster.set_paused(False)
        elif action == "speed_up":
            broadcaster.set_speed_multiplier(broadcaster.get_speed_multiplier() * 2.0)
        elif action == "speed_down":
            broadcaster.set_speed_multiplier(broadcaster.get_speed_multiplier() / 2.0)
        elif action == "set":
            try:
                broadcaster.set_speed_multiplier(float(payload.get("multiplier", DEFAULT_SPEED_MULTIPLIER)))
            except (TypeError, ValueError):
                return JSONResponse({"error": "multiplier must be a number"}, status_code=400)
        elif action == "reset":
            broadcaster.reset_speed()
        else:
            return JSONResponse(
                {"error": "action must be one of: pause, resume, speed_up, speed_down, set, reset"},
                status_code=400,
            )
        return JSONResponse(broadcaster.sim_pacing())

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        broadcaster.add_client(websocket)
        # Send the current state immediately on connect, rather than
        # making the client wait up to one full tick for its first
        # picture of the world.
        current = broadcaster.get_state()
        if current is not None:
            await websocket.send_json(current)
        try:
            while True:
                await websocket.receive_text()  # read-only channel: ignored, see api.py
        except WebSocketDisconnect:
            pass
        finally:
            broadcaster.remove_client(websocket)

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
    return app
