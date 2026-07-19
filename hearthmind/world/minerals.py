"""Distinct mineral veins — iron and gold — layered on hills terrain.

Explicit user directive (v0.87.25, docs/IDEAS-2026-07-EMERGENCE.md §8):
"we also need to include more materials like gold, iron, diamonds,
silicon etc to get minecraft like mechanics to NPCs - NPCs too should
believe they are living in a real world." Scoped to IRON and GOLD on
HILLS this pass — MOUNTAIN-gated DIAMOND and BEACH-gated SILICON are
explicitly deferred (flagged, not silently dropped): both need real
GATHER-goal pathing work `_nearest_material_tile` doesn't do today
(MATERIAL_BIOMES is FOREST/HILLS only), which is a larger, separate
increment than extending an already-hills-reachable mechanic.

Deliberately a standalone module, not a `ResourceKind` extension on
`ResourceGrid` — `ResourceGrid._tick_native`/`resource_grid.cpp` switch
on a closed set of kind strings for regen behavior; adding new kinds
there without touching the C++ side risks silently wrong regen rates
(or a crash) under a native build. A HILLS tile's mineral deposit (if
any) is tracked independently of whatever `ResourceGrid` node also sits
there — a real hillside can hold both a worked stone quarry and a
distinct ore vein, so no exclusivity check against `ResourceGrid` was
needed to keep this believable. R7 ("new physical-substrate code is
C++-first") deviation, same documented shape as v0.87.23's spatial
weather: flagged, not silently ignored — a native port is a reasonable
follow-up once/if this proves worth the engineering cost, not attempted
this pass given the low density (rare tile-level lookups, not a hot
per-agent loop)."""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from enum import Enum

from hearthmind.world.terrain import Biome, Tile


class MineralKind(str, Enum):
    IRON = "iron"
    GOLD = "gold"


IRON_BIOMES = frozenset({Biome.HILLS})
GOLD_BIOMES = frozenset({Biome.HILLS})

IRON_NODE_DENSITY = 0.035
"""Fraction of HILLS tiles carrying an iron vein — denser than gold,
rarer than the plain ORE node ResourceGrid already scatters there
(0.06), reflecting "common but not universal" ore-grade iron."""

GOLD_NODE_DENSITY = 0.01
"""Fraction of HILLS tiles carrying a gold vein — roughly a third as
dense as iron, the "genuinely worth finding" rarity tier."""

MAX_IRON_AMOUNT = 1.5
MAX_GOLD_AMOUNT = 0.8
"""A gold vein holds less than an iron one — scarcity by design, not
just by density."""

IRON_REGEN_PER_TICK = 0.00012
"""Roughly comparable order of magnitude to ORE_REGEN_PER_TICK
(world/resources.py) — a mined-out iron vein takes on the order of two
months of sim-time to fully recover."""

GOLD_REGEN_PER_TICK = IRON_REGEN_PER_TICK / 3
"""Gold recovers slower still — a genuinely scarce find, not just a
reskinned iron vein."""

SEASON_REGEN_MULTIPLIER = {"winter": 0.3, "autumn": 0.75, "spring": 1.1, "summer": 1.0}
"""Same shape/rationale as ResourceGrid's own table — frozen ground
slows mining exactly as it slows foraging."""


def _mineral_rng(seed: int) -> random.Random:
    digest = hashlib.sha256(f"{seed}:minerals_init".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


@dataclass
class MineralDeposit:
    x: int
    y: int
    kind: MineralKind
    amount: float

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "kind": self.kind.value, "amount": round(self.amount, 4)}

    @classmethod
    def from_dict(cls, data: dict) -> "MineralDeposit":
        return cls(
            x=data["x"], y=data["y"], kind=MineralKind(data["kind"]), amount=data["amount"],
        )


@dataclass
class MineralGrid:
    deposits: dict[tuple[int, int], MineralDeposit] = field(default_factory=dict)

    @classmethod
    def generate(cls, seed: int, terrain: list[list[Tile]]) -> "MineralGrid":
        rng = _mineral_rng(seed)
        deposits: dict[tuple[int, int], MineralDeposit] = {}
        for row in terrain:
            for tile in row:
                if tile.biome in IRON_BIOMES and rng.random() < IRON_NODE_DENSITY:
                    deposits[(tile.x, tile.y)] = MineralDeposit(
                        x=tile.x, y=tile.y, kind=MineralKind.IRON, amount=MAX_IRON_AMOUNT,
                    )
                elif tile.biome in GOLD_BIOMES and rng.random() < GOLD_NODE_DENSITY:
                    deposits[(tile.x, tile.y)] = MineralDeposit(
                        x=tile.x, y=tile.y, kind=MineralKind.GOLD, amount=MAX_GOLD_AMOUNT,
                    )
        return cls(deposits=deposits)

    def get(self, x: int, y: int) -> MineralDeposit | None:
        return self.deposits.get((x, y))

    def harvest(self, x: int, y: int, amount: float) -> float:
        """Consume up to `amount` from the deposit at (x, y); returns the
        actual amount consumed (0.0 if nothing there)."""
        deposit = self.deposits.get((x, y))
        if deposit is None or deposit.amount <= 0:
            return 0.0
        consumed = min(deposit.amount, amount)
        deposit.amount -= consumed
        return consumed

    def tick(self, season: str = "summer") -> None:
        multiplier = SEASON_REGEN_MULTIPLIER.get(season, 1.0)
        for deposit in self.deposits.values():
            cap, regen = (
                (MAX_IRON_AMOUNT, IRON_REGEN_PER_TICK) if deposit.kind is MineralKind.IRON
                else (MAX_GOLD_AMOUNT, GOLD_REGEN_PER_TICK)
            )
            if deposit.amount < cap:
                deposit.amount = min(cap, deposit.amount + regen * multiplier)

    def summary(self) -> dict:
        iron = [d for d in self.deposits.values() if d.kind is MineralKind.IRON]
        gold = [d for d in self.deposits.values() if d.kind is MineralKind.GOLD]
        return {
            "iron_deposits": len(iron),
            "iron_avg_amount": round(sum(d.amount for d in iron) / len(iron), 3) if iron else 0.0,
            "gold_deposits": len(gold),
            "gold_avg_amount": round(sum(d.amount for d in gold) / len(gold), 3) if gold else 0.0,
        }

    def to_dict(self) -> dict:
        return {"deposits": [d.to_dict() for d in self.deposits.values()]}

    @classmethod
    def from_dict(cls, data: dict) -> "MineralGrid":
        deposits: dict[tuple[int, int], MineralDeposit] = {}
        for deposit_data in data.get("deposits", []):
            deposit = MineralDeposit.from_dict(deposit_data)
            deposits[(deposit.x, deposit.y)] = deposit
        return cls(deposits=deposits)
