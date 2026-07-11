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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from hearthmind.interface.api import WorldBroadcaster
from hearthmind.persistence.snapshot import recent_events

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(broadcaster: WorldBroadcaster, conn: sqlite3.Connection) -> FastAPI:
    """`conn` is the same connection the engine already holds open for
    the life of the process — reused here rather than opening a second
    one, safe because everything (engine ticks and these async request
    handlers) runs on the same single-threaded asyncio event loop. Only
    ever read from, never written to, from this module."""
    app = FastAPI(title="Hearthmind", docs_url=None, redoc_url=None)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

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
