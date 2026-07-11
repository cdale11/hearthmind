"""Live-state broadcast layer for the browser interface (Phase F).

`WorldBroadcaster` is the one object that bridges the engine's tick loop
and the FastAPI app (`interface/app.py`): `SimulationEngine` pushes a
fresh payload into it once per tick (fire-and-forget, never awaited
inline — see `_maybe_broadcast` in simulation/engine.py), and it holds
the *last* payload for `GET /state` plus a set of live WebSocket
connections to push to. It never reaches back into the engine or the
`World` itself — one-way data flow, read-only, same as every other
observation surface (`inspect_world`). See docs/DECISIONS.md, F1/F2.
"""
from __future__ import annotations

import json
import logging
from typing import Callable

logger = logging.getLogger("hearthmind.api")


class WorldBroadcaster:
    def __init__(self) -> None:
        self._clients: set = set()
        self._last_payload: dict | None = None
        self._terrain_payload: dict | None = None
        self._diagnostics_provider: Callable[[], dict] | None = None

    # --- called by SimulationEngine (writer side) -----------------------------

    def set_terrain(self, terrain, width: int, height: int) -> None:
        """Called once, when the engine starts — terrain never changes
        after world creation, so it's not part of the per-tick payload."""
        self._terrain_payload = {
            "width": width,
            "height": height,
            "biomes": [[tile.biome.value for tile in row] for row in terrain],
        }

    def set_diagnostics_provider(self, provider: Callable[[], dict]) -> None:
        """Called once, when the engine starts — `provider` is
        `SimulationEngine.full_diagnostics`, a synchronous, read-only
        callable. Keeps this class framework-free and engine-agnostic
        (it never imports SimulationEngine) while still letting
        `GET /diagnostics` (interface/app.py) reach the heavier,
        on-demand report. See docs/DECISIONS.md, diagnostics pass."""
        self._diagnostics_provider = provider

    def get_full_diagnostics(self) -> dict | None:
        return self._diagnostics_provider() if self._diagnostics_provider else None

    async def broadcast(self, payload: dict) -> None:
        self._last_payload = payload
        if not self._clients:
            return
        message = json.dumps(payload)
        dead = []
        for client in list(self._clients):
            try:
                await client.send_text(message)
            except Exception:
                dead.append(client)
        for client in dead:
            self._clients.discard(client)

    # --- called by the FastAPI app (reader side) ------------------------------

    def get_state(self) -> dict | None:
        return self._last_payload

    def get_terrain(self) -> dict | None:
        return self._terrain_payload

    def client_count(self) -> int:
        """Read-only diagnostic for the engine's broadcast payload (see
        `_maybe_broadcast`'s `diagnostics` key) — lets the browser's dev
        console show how many clients are actually connected without the
        engine reaching into this class's private state."""
        return len(self._clients)

    def add_client(self, websocket) -> None:
        self._clients.add(websocket)
        logger.info("Client connected (%d total).", len(self._clients))

    def remove_client(self, websocket) -> None:
        self._clients.discard(websocket)
        logger.info("Client disconnected (%d total).", len(self._clients))
