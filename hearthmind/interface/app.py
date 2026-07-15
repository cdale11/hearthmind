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
from hearthmind.persistence.snapshot import (
    event_category_counts,
    history_events,
    list_snapshot_ticks,
    load_snapshot_at_tick,
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
        or negative), clamped to capacity/zero by the engine."""
        broadcaster.enqueue_intervention({
            "type": "settlement_resources",
            "materials": payload.get("materials", 0.0),
            "currency": payload.get("currency", 0.0),
        })
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
        text "whisper" folded into the LLM brain's next seasonal
        civic-priority decision as one input among the real settlement
        stats/history — not a command it's forced to obey. See
        docs/DECISIONS.md, "LLM-as-brain batch.\""""
        text = str(payload.get("text", "")).strip()
        if not text:
            return JSONResponse({"error": "text is required"}, status_code=400)
        broadcaster.enqueue_intervention({"type": "town_influence", "text": text})
        return JSONResponse({"queued": True})

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
