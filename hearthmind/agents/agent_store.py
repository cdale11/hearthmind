"""Native structure-of-arrays backing for Agent's 12 dense scalar fields.

R8 slice 3, wire-in phase (v0.75.0). The `AgentTable` storage primitive
(cpp/src/agent_table.cpp) was shipped and fuzz-verified in isolation in
v0.74.3; this module is the compatibility layer that finally makes it the
live source of truth for those scalars, the same "storage moves to C++
behind a drop-in Python handle" step `world/terrain.py`'s `TerrainGrid`
took for the terrain grid.

Design (why this is safe against the ~700-touch risk surface the v0.74.2
scoping flagged):

- The store's public API is keyed by **agent id**, never by table slot.
  The native table uses swap-with-last removal, which reassigns a
  surviving agent's slot when another is removed; by resolving id->slot
  *inside* the store on every access (and updating that map from the
  table's own RemoveResult), no Python-side handle can ever hold a stale
  slot. The entire staleness bug class is eliminated at the API boundary
  rather than guarded against at ~700 call sites. Agent ids are
  monotonic and never reused (Population._next_id), so an id is a stable
  key for an agent's whole lifetime.

- `Agent` (agents/agent.py) keeps `self.agents` an ordinary ordered
  `list[Agent]`; iteration order is the list's, fully decoupled from the
  table's slot order, so slot churn from deaths never reorders anything a
  caller sees.

- **Fallback stays byte-identical to the old dataclass behaviour.** When
  the native extension isn't built, `Population` creates no store and
  every `Agent` stays "detached" — its scalars live in plain instance
  attributes exactly as the dataclass held them. The store is a pure
  optimisation of *where* the numbers sit, never a behavioural change;
  this is verified every tick, native-on vs native-off byte-identical, by
  scripts/verify_native_soak.py's `agent_store` toggle.

Enum encoding: `AgentState`/`AgentGoal` cross the C++ boundary as small
int codes (the table stores ints). The authoritative bijection lives in
agents/agent.py (STATE_TO_CODE/GOAL_TO_CODE, next to the enums it
encodes) so this module stays enum-free and dependency-light — it deals
only in the raw ints the table holds. `AgentTable`'s own header
documents the same codes — keep the three in sync.
"""
from __future__ import annotations

try:  # optional native extension; pure-Python fallback when absent
    from hearthmind._native import AgentTable as _NativeAgentTable
except ImportError:  # pragma: no cover - exercised on machines without the build
    _NativeAgentTable = None


def native_available() -> bool:
    """Read the current module global live (so the soak harness can
    monkeypatch `_NativeAgentTable = None` to force the fallback path)."""
    return _NativeAgentTable is not None


class AgentStore:
    """id-keyed structure-of-arrays store over the native `AgentTable`.

    Only constructed when the native extension is present — the pure
    Python fallback keeps scalars on the Agent objects themselves and
    never builds a store (see this module's docstring). Every method is
    keyed by agent id; the id->slot map is the only place slots are ever
    seen, and it is the single thing updated when swap-with-last removal
    moves a surviving agent."""

    __slots__ = ("_table", "_id_to_slot")

    def __init__(self) -> None:
        if _NativeAgentTable is None:  # pragma: no cover - guarded by callers
            raise RuntimeError("AgentStore requires the native extension")
        self._table = _NativeAgentTable()
        self._id_to_slot: dict[int, int] = {}

    def __contains__(self, agent_id: int) -> bool:
        return agent_id in self._id_to_slot

    def add(
        self, agent_id: int, x: int, y: int, hunger: float, energy: float,
        state_code: int, age_ticks: int, max_age_ticks: int, starving_ticks: int,
        sick_ticks: int, immune_ticks: int, goal_code: int, settlement_id: int,
    ) -> None:
        slot = self._table.append(
            agent_id, x, y, hunger, energy, state_code, age_ticks, max_age_ticks,
            starving_ticks, sick_ticks, immune_ticks, goal_code, settlement_id,
        )
        self._id_to_slot[agent_id] = slot

    def remove(self, agent_id: int) -> None:
        slot = self._id_to_slot.pop(agent_id)
        result = self._table.remove(slot)
        if result.moved:
            # The last slot's agent was moved into `slot` to keep storage
            # dense; repoint its id at its new home. This is the only
            # bookkeeping the whole swap-with-last scheme needs.
            self._id_to_slot[result.moved_agent_id] = slot

    # --- scalar getters/setters (raw ints/floats; enum coding lives in Agent) ---
    def get_x(self, i: int) -> int: return self._table.get_x(self._id_to_slot[i])
    def get_y(self, i: int) -> int: return self._table.get_y(self._id_to_slot[i])
    def get_hunger(self, i: int) -> float: return self._table.get_hunger(self._id_to_slot[i])
    def get_energy(self, i: int) -> float: return self._table.get_energy(self._id_to_slot[i])
    def get_state(self, i: int) -> int: return self._table.get_state(self._id_to_slot[i])
    def get_age_ticks(self, i: int) -> int: return self._table.get_age_ticks(self._id_to_slot[i])
    def get_max_age_ticks(self, i: int) -> int: return self._table.get_max_age_ticks(self._id_to_slot[i])
    def get_starving_ticks(self, i: int) -> int: return self._table.get_starving_ticks(self._id_to_slot[i])
    def get_sick_ticks(self, i: int) -> int: return self._table.get_sick_ticks(self._id_to_slot[i])
    def get_immune_ticks(self, i: int) -> int: return self._table.get_immune_ticks(self._id_to_slot[i])
    def get_goal(self, i: int) -> int: return self._table.get_goal(self._id_to_slot[i])
    def get_settlement_id(self, i: int) -> int: return self._table.get_settlement_id(self._id_to_slot[i])

    def set_x(self, i: int, v: int) -> None: self._table.set_x(self._id_to_slot[i], v)
    def set_y(self, i: int, v: int) -> None: self._table.set_y(self._id_to_slot[i], v)
    def set_hunger(self, i: int, v: float) -> None: self._table.set_hunger(self._id_to_slot[i], v)
    def set_energy(self, i: int, v: float) -> None: self._table.set_energy(self._id_to_slot[i], v)
    def set_state(self, i: int, v: int) -> None: self._table.set_state(self._id_to_slot[i], v)
    def set_age_ticks(self, i: int, v: int) -> None: self._table.set_age_ticks(self._id_to_slot[i], v)
    def set_max_age_ticks(self, i: int, v: int) -> None: self._table.set_max_age_ticks(self._id_to_slot[i], v)
    def set_starving_ticks(self, i: int, v: int) -> None: self._table.set_starving_ticks(self._id_to_slot[i], v)
    def set_sick_ticks(self, i: int, v: int) -> None: self._table.set_sick_ticks(self._id_to_slot[i], v)
    def set_immune_ticks(self, i: int, v: int) -> None: self._table.set_immune_ticks(self._id_to_slot[i], v)
    def set_goal(self, i: int, v: int) -> None: self._table.set_goal(self._id_to_slot[i], v)
    def set_settlement_id(self, i: int, v: int) -> None: self._table.set_settlement_id(self._id_to_slot[i], v)
