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
from hearthmind.interface.api import WorldBroadcaster
from hearthmind.persistence.snapshot import event_category_counts, recent_events, snapshot_count, total_event_count

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(broadcaster: WorldBroadcaster, conn: sqlite3.Connection) -> FastAPI:
    """`conn` is the same connection the engine already holds open for
    the life of the process — reused here rather than opening a second
    one, safe because everything (engine ticks and these async request
    handlers) runs on the same single-threaded asyncio event loop. Only
    ever read from, never written to, from this module."""
    app = FastAPI(title="Hearthmind", docs_url=None, redoc_url=None)

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
