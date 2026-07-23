"""Live-state broadcast layer for the browser interface (Phase F).

`WorldBroadcaster` is the one object that bridges the engine's tick loop
and the FastAPI app (`interface/app.py`): `SimulationEngine` pushes a
fresh payload into it once per tick (fire-and-forget, never awaited
inline — see `_maybe_broadcast` in simulation/engine.py), and it holds
the *last* payload for `GET /state` plus a set of live WebSocket
connections to push to. It never reaches back into the engine or the
`World` itself directly. The data flow is mostly one-way/read-only,
same as every other observation surface (`inspect_world`) — with one
deliberate exception: `enqueue_intervention`/`drain_interventions` is a
small queued channel the FastAPI app's `/intervene/*` endpoints use to
request a change (nudge an agent's goal, adjust settlement stores,
nudge the weather); `SimulationEngine` is still the only thing that
actually mutates `World`, applying each queued item synchronously at
the top of its next tick — see `_apply_pending_interventions`. See
docs/DECISIONS.md, F1/F2 and the interventions pass.
"""
from __future__ import annotations

import json
import logging
from typing import Callable

logger = logging.getLogger("hearthmind.api")


DEFAULT_SPEED_MULTIPLIER = 1.0
MIN_SPEED_MULTIPLIER = 0.25
MAX_SPEED_MULTIPLIER = 8.0
"""Bounds for the live sim-speed control (see `/intervene/sim-speed` in
interface/app.py). 0.25x is slow enough to watch individual agent
movement; 8x is fast enough to skip through quiet stretches without the
tick loop's LLM concurrency cap (config.llm_max_concurrent) getting
overwhelmed by ticks arriving faster than jobs resolve."""

INTERVENTION_QUEUE_MAX = 256
"""Cap on the pending-intervention queue (`enqueue_intervention`) — it
drains every tick, so this is only reached if POSTs burst faster than
ticks or the loop is stalled/paused. Well above any realistic burst of
genuine user nudges; the oldest is dropped past it (v0.71.0)."""


class WorldBroadcaster:
    def __init__(self) -> None:
        self._clients: set = set()
        self._last_payload: dict | None = None
        self._terrain_payload: dict | None = None
        self._diagnostics_provider: Callable[[], dict] | None = None
        self._knowledge_tree_provider: Callable[[], list] | None = None
        self._causal_threads_provider: Callable[[], list] | None = None
        self._emergence_log_provider: Callable[[], list] | None = None
        self._interventions: list[dict] = []
        self._paused = False
        self._speed_multiplier = DEFAULT_SPEED_MULTIPLIER
        """Read every loop iteration by `SimulationEngine.run_forever` —
        deliberately NOT routed through the `_interventions` queue like
        every other `/intervene/*` request, because that queue is only
        drained at the top of `_tick_once`: if the sim is paused,
        `_tick_once` never runs, so a queued "unpause" would never be
        applied and the sim would be stuck paused forever. Plain
        read/write attributes instead, same shape as `_last_payload` —
        safe because both the FastAPI handler and the engine's tick loop
        run on the same asyncio event loop, never concurrently."""

    # --- called by SimulationEngine (writer side) -----------------------------

    def set_terrain(
        self, terrain, width: int, height: int,
        mining_scars: dict | None = None, disaster_scars: dict | None = None,
        ritual_activity: dict | None = None,
    ) -> None:
        """Called when the engine starts, and again on any tick where
        terrain evolution changed a tile's biome (see
        `SimulationEngine._maybe_broadcast`) — terrain changes rarely
        enough that it's not worth including in the per-tick payload,
        but it isn't truly static anymore. See docs/DECISIONS.md,
        terrain-evolution pass.

        `mining_scars` (v0.87.27, §8 "NPC activity reshapes geography")
        rides this same resync — it doesn't change `biomes` but shares
        the exact rarity profile (a tile crossing MINING_SCAR_VISIBLE_
        THRESHOLD is now in `TERRAIN_CHANGING_CATEGORIES`), so reusing
        this one payload avoids a second broadcast channel. Sparse —
        only genuinely visible scars, not the full grid.

        `disaster_scars` (Phase 3.D, docs/VISION-2026-07-21-
        SELFEVOLVING.md): same shape/rationale as `mining_scars`, for
        `disaster_scarred` events instead.

        `ritual_activity` (A19, roadmap Stage IV step 26): same shape,
        piggybacking on this same resync channel — a real limitation
        flagged, not silently accepted: unlike the two scar dicts
        above, nothing yet forces a resync specifically when a NEW
        tile gains ritual activity (no `TERRAIN_CHANGING_CATEGORIES`
        entry for it), so the map overlay can lag behind the real
        state until some OTHER terrain-changing event happens to fire.
        Acceptable for a first slice — festivals are already rare
        events, and every existing terrain-changing category still
        refreshes this whole payload including this field."""
        self._terrain_payload = {
            "width": width,
            "height": height,
            "biomes": [[tile.biome.value for tile in row] for row in terrain],
            "mining_scars": (
                {f"{x}:{y}": round(v, 3) for (x, y), v in mining_scars.items()}
                if mining_scars else {}
            ),
            "disaster_scars": (
                {f"{x}:{y}": round(v, 3) for (x, y), v in disaster_scars.items()}
                if disaster_scars else {}
            ),
            "ritual_activity": (
                {f"{x}:{y}": round(v, 3) for (x, y), v in ritual_activity.items()}
                if ritual_activity else {}
            ),
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

    def set_knowledge_tree_provider(self, provider: Callable[[], list]) -> None:
        """Same shape as `set_diagnostics_provider` — `provider` is
        `World.knowledge_tree`, a synchronous read-only callable.
        Vision doc item 3.2 ("What the world learned" ledger,
        docs/VISION-2026-07-22-LIVINGTERRARIUM.md): computed on demand
        by `GET /knowledge-tree` rather than baked into the per-tick
        broadcast payload, since it aggregates/sorts across several
        stores and doesn't need sub-second freshness."""
        self._knowledge_tree_provider = provider

    def get_knowledge_tree(self) -> list | None:
        return self._knowledge_tree_provider() if self._knowledge_tree_provider else None

    def set_causal_threads_provider(self, provider: Callable[[], list]) -> None:
        """Same on-demand shape as `set_knowledge_tree_provider` —
        `provider` is `World.causal_threads_list`. Vision doc item 3.3
        ("Legible causal threads")."""
        self._causal_threads_provider = provider

    def get_causal_threads(self) -> list | None:
        return self._causal_threads_provider() if self._causal_threads_provider else None

    def set_emergence_log_provider(self, provider: Callable[[], list]) -> None:
        """Same on-demand shape as `set_knowledge_tree_provider` —
        `provider` reads `World.emergence_log` directly (no aggregation
        needed, but on-demand rather than baked into the per-tick
        broadcast anyway: up to `EMERGENCE_LOG_MAX_STORED` entries would
        bloat every WS message for a stream nothing polls sub-second).
        A22 "The Emergence API" (docs/MASTERCHECKLIST-2026-07-22.md)."""
        self._emergence_log_provider = provider

    def get_emergence_log(self) -> list | None:
        return self._emergence_log_provider() if self._emergence_log_provider else None

    # --- called by the FastAPI app (writer side — interventions only) ---------

    def enqueue_intervention(self, intervention: dict) -> None:
        """Called by a `/intervene/*` POST handler. Queued, not applied —
        `SimulationEngine._apply_pending_interventions` drains and
        applies this at the top of its next tick, so `World` is still
        only ever mutated from the tick loop. See docs/DECISIONS.md,
        interventions pass.

        Bounded at INTERVENTION_QUEUE_MAX: the queue drains every tick, so
        it's normally tiny, but a burst of POSTs between two ticks (or a
        stalled/paused tick loop) could otherwise grow it without bound.
        Past the cap the oldest queued intervention is dropped — an
        intervention is a best-effort nudge, and shedding the stalest one
        is the right failure mode (v0.71.0 memory-audit pass)."""
        self._interventions.append(intervention)
        if len(self._interventions) > INTERVENTION_QUEUE_MAX:
            del self._interventions[: len(self._interventions) - INTERVENTION_QUEUE_MAX]

    # --- called by SimulationEngine (writer side) -----------------------------

    def drain_interventions(self) -> list[dict]:
        """Returns and clears everything queued since the last drain —
        called once per tick."""
        drained, self._interventions = self._interventions, []
        return drained

    # --- sim pacing: read/written by both the FastAPI handler and the engine --

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def is_paused(self) -> bool:
        return self._paused

    def set_speed_multiplier(self, multiplier: float) -> float:
        self._speed_multiplier = max(MIN_SPEED_MULTIPLIER, min(MAX_SPEED_MULTIPLIER, multiplier))
        return self._speed_multiplier

    def get_speed_multiplier(self) -> float:
        return self._speed_multiplier

    def reset_speed(self) -> None:
        self._paused = False
        self._speed_multiplier = DEFAULT_SPEED_MULTIPLIER

    def sim_pacing(self) -> dict:
        return {"paused": self._paused, "speed_multiplier": self._speed_multiplier}

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
