"""Read-only WebSocket API exposing live world state to a browser client.

First Phase F slice: a broadcast-only channel, no intervention endpoints
yet — the roadmap explicitly puts "sparse intervention tools" last, once
there's something worth looking at. The engine owns time (see
simulation/engine.py); this module only ever *reads* `World` state via
the summary/event-log the CLI (`inspect_world`) already uses, and pushes
it out — it never mutates the world and is never awaited from inside the
tick path, so a slow or disconnected client cannot stall or crash the
simulation, the same liveness guarantee already given to the LLM layer
(see docs/DECISIONS.md, B1).

Bends the project's "no external dependencies" rule (see README) for the
`websockets` package — Python's stdlib has no WebSocket support, and a
hand-rolled implementation would be a lot of fragile protocol code for
little benefit. This is a deliberate, scoped exception, not a precedent
for pulling in dependencies freely — see docs/DECISIONS.md, F1.
"""
from __future__ import annotations

import asyncio
import json
import logging

import websockets

logger = logging.getLogger("hearthmind.api")


class WorldBroadcaster:
    """Owns the set of connected WebSocket clients and pushes a JSON
    payload to all of them once per tick. `SimulationEngine` calls
    `broadcast()` as a fire-and-forget background task (same pattern as
    LLM cognition/chronicle jobs) — never awaited inline in `_tick_once`."""

    def __init__(self) -> None:
        self._clients: set = set()

    async def handler(self, websocket) -> None:
        self._clients.add(websocket)
        logger.info("Client connected (%d total).", len(self._clients))
        try:
            async for _ in websocket:
                pass  # read-only channel: incoming messages are ignored, not an intervention API yet
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            logger.info("Client disconnected (%d total).", len(self._clients))

    async def broadcast(self, payload: dict) -> None:
        if not self._clients:
            return
        message = json.dumps(payload)
        dead = []
        for client in list(self._clients):
            try:
                await client.send(message)
            except websockets.exceptions.ConnectionClosed:
                dead.append(client)
        for client in dead:
            self._clients.discard(client)


async def serve_forever(broadcaster: WorldBroadcaster, host: str, port: int, stop_event: asyncio.Event) -> None:
    """Runs the WebSocket server until `stop_event` is set — mirrors
    `SimulationEngine.run_forever`'s own stop-event shutdown so both loops
    exit together on Ctrl+C/SIGTERM."""
    async with websockets.serve(broadcaster.handler, host, port):
        logger.info("WebSocket API listening on ws://%s:%s", host, port)
        await stop_event.wait()
        logger.info("WebSocket API shutting down.")
