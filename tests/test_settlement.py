import random
import unittest

from hearthmind.agents.agent import MATURITY_TICKS, Agent, AgentState
from hearthmind.agents.population import Population
from hearthmind.economy.farms import FarmGrid
from hearthmind.settlement.buildings import (
    DECAY_PER_TICK_BASE,
    REPAIR_THRESHOLD,
    RUIN_REMOVAL_TICKS,
    Building,
    BuildingStage,
    Settlement,
)
from hearthmind.world.resources import ResourceGrid
from hearthmind.world.weather import WeatherState
from tests._terrain_helpers import open_terrain


def _clear_weather():
    return WeatherState(temperature_c=20.0, precipitation=0.0, wind=0.0, is_snowing=False)


def _harsh_weather():
    return WeatherState(temperature_c=-5.0, precipitation=0.8, wind=0.7, is_snowing=True)


class TestSettlementQueries(unittest.TestCase):
    def test_at_returns_none_when_empty(self):
        settlement = Settlement()
        self.assertIsNone(settlement.at(0, 0))

    def test_at_finds_building_by_position(self):
        settlement = Settlement()
        settlement.start_construction(3, 4)
        found = settlement.at(3, 4)
        self.assertIsNotNone(found)
        self.assertEqual((found.x, found.y), (3, 4))

    def test_start_construction_assigns_unique_ids(self):
        settlement = Settlement()
        a = settlement.start_construction(0, 0)
        b = settlement.start_construction(1, 1)
        self.assertNotEqual(a.id, b.id)


class TestConstructionAndRepair(unittest.TestCase):
    def test_mature_healthy_colocated_pair_can_start_construction(self):
        # Called directly with a synthetic by-position grouping, for the
        # same reason as the reproduction tests in test_agents.py: relying
        # on random movement to keep two agents colocated for enough ticks
        # to observe the low per-tick roll would make this both slow and
        # seed-fragile.
        settlement = Settlement()
        farms = FarmGrid()
        a = Agent(id=0, name="Founder1", x=5, y=5, age_ticks=MATURITY_TICKS + 1,
                  max_age_ticks=1_000_000, hunger=0.1, energy=0.9)
        b = Agent(id=1, name="Founder2", x=5, y=5, age_ticks=MATURITY_TICKS + 1,
                  max_age_ticks=1_000_000, hunger=0.1, energy=0.9)
        population = Population(agents=[a, b], _next_id=2)

        started = False
        for tick in range(1, 3000):
            rng = random.Random(tick)
            events = population._maybe_start_construction({(5, 5): [a, b]}, settlement, farms, rng)
            if any(cat == "construction_started" for cat, _ in events):
                started = True
                break

        self.assertTrue(started, "expected construction to start within 3000 rolls")
        self.assertEqual(len(settlement.buildings), 1)
        self.assertEqual(settlement.buildings[0].stage, BuildingStage.UNDER_CONSTRUCTION)

    def test_lone_agent_cannot_start_construction(self):
        terrain = open_terrain()
        resources = ResourceGrid(nodes={})
        settlement = Settlement()
        farms = FarmGrid()
        agent = Agent(id=0, name="Solo", x=5, y=5, age_ticks=MATURITY_TICKS + 1,
                      max_age_ticks=1_000_000, hunger=0.1, energy=0.9)
        population = Population(agents=[agent], _next_id=1)

        # Eligibility (colocation, maturity, health) is checked before the
        # RNG roll, so a structurally-ineligible group never starts
        # construction regardless of how many ticks pass — a short loop
        # proves this as well as a long one, much faster.
        for tick in range(1, 50):
            population.tick(seed=1, tick=tick, terrain=terrain, resources=resources, settlement=settlement, farms=farms)

        self.assertEqual(len(settlement.buildings), 0)

    def test_immature_pair_cannot_start_construction(self):
        terrain = open_terrain()
        resources = ResourceGrid(nodes={})
        settlement = Settlement()
        farms = FarmGrid()
        a = Agent(id=0, name="Young1", x=5, y=5, age_ticks=0, max_age_ticks=1_000_000, hunger=0.1, energy=0.9)
        b = Agent(id=1, name="Young2", x=5, y=5, age_ticks=0, max_age_ticks=1_000_000, hunger=0.1, energy=0.9)
        population = Population(agents=[a, b], _next_id=2)

        for tick in range(1, 50):
            population.tick(seed=1, tick=tick, terrain=terrain, resources=resources, settlement=settlement, farms=farms)

        self.assertEqual(len(settlement.buildings), 0)

    def test_construction_advances_with_present_worker_and_completes(self):
        settlement = Settlement()
        settlement.start_construction(5, 5)
        agent = Agent(id=0, name="Builder", x=5, y=5, state=AgentState.AWAKE)
        by_position = {(5, 5): [agent]}

        events = []
        for _ in range(50):
            events.extend(Population._advance_construction(by_position, settlement))
            if settlement.buildings[0].stage is BuildingStage.STANDING:
                break

        self.assertEqual(settlement.buildings[0].stage, BuildingStage.STANDING)
        self.assertEqual(settlement.buildings[0].condition, 1.0)
        self.assertTrue(any(cat == "building_completed" for cat, _ in events))

    def test_construction_does_not_advance_without_workers(self):
        settlement = Settlement()
        building = settlement.start_construction(5, 5)
        Population._advance_construction({}, settlement)
        self.assertEqual(building.progress, 0.0)

    def test_repair_restores_condition_when_worker_present(self):
        settlement = Settlement()
        building = settlement.start_construction(5, 5)
        building.stage = BuildingStage.STANDING
        building.condition = 0.1
        agent = Agent(id=0, name="Repairer", x=5, y=5, state=AgentState.AWAKE)
        by_position = {(5, 5): [agent]}

        Population._maybe_repair(by_position, settlement)

        self.assertGreater(building.condition, 0.1)

    def test_repair_does_not_touch_healthy_buildings(self):
        settlement = Settlement()
        building = settlement.start_construction(5, 5)
        building.stage = BuildingStage.STANDING
        building.condition = 1.0
        agent = Agent(id=0, name="Idle", x=5, y=5, state=AgentState.AWAKE)
        by_position = {(5, 5): [agent]}

        Population._maybe_repair(by_position, settlement)

        self.assertEqual(building.condition, 1.0)

    def test_repair_threshold_constant_is_sane(self):
        self.assertGreater(REPAIR_THRESHOLD, 0.0)
        self.assertLess(REPAIR_THRESHOLD, 1.0)


class TestWeatheringAndReclamation(unittest.TestCase):
    def test_standing_building_decays_over_time(self):
        settlement = Settlement(buildings=[
            Building(id=0, x=0, y=0, stage=BuildingStage.STANDING, condition=1.0)
        ])
        settlement.tick(weather=_clear_weather())
        self.assertLess(settlement.buildings[0].condition, 1.0)

    def test_harsh_weather_decays_faster_than_clear(self):
        clear = Settlement(buildings=[Building(id=0, x=0, y=0, stage=BuildingStage.STANDING, condition=1.0)])
        harsh = Settlement(buildings=[Building(id=0, x=0, y=0, stage=BuildingStage.STANDING, condition=1.0)])

        clear.tick(weather=_clear_weather())
        harsh.tick(weather=_harsh_weather())

        self.assertLess(harsh.buildings[0].condition, clear.buildings[0].condition)

    def test_building_becomes_ruined_at_zero_condition(self):
        settlement = Settlement(buildings=[
            Building(id=0, x=0, y=0, stage=BuildingStage.STANDING, condition=DECAY_PER_TICK_BASE / 2)
        ])
        events = settlement.tick(weather=_clear_weather())
        self.assertEqual(settlement.buildings[0].stage, BuildingStage.RUINED)
        self.assertTrue(any(cat == "building_ruined" for cat, _ in events))

    def test_ruin_removed_after_enough_ticks(self):
        settlement = Settlement(buildings=[
            Building(id=0, x=0, y=0, stage=BuildingStage.RUINED, ruined_ticks=RUIN_REMOVAL_TICKS - 1)
        ])
        events = settlement.tick(weather=_clear_weather())
        self.assertEqual(len(settlement.buildings), 0)
        self.assertTrue(any(cat == "building_reclaimed" for cat, _ in events))

    def test_ruin_not_removed_before_threshold(self):
        settlement = Settlement(buildings=[
            Building(id=0, x=0, y=0, stage=BuildingStage.RUINED, ruined_ticks=0)
        ])
        settlement.tick(weather=_clear_weather())
        self.assertEqual(len(settlement.buildings), 1)

    def test_under_construction_building_unaffected_by_weathering(self):
        settlement = Settlement(buildings=[
            Building(id=0, x=0, y=0, stage=BuildingStage.UNDER_CONSTRUCTION, progress=0.3)
        ])
        settlement.tick(weather=_harsh_weather())
        self.assertEqual(settlement.buildings[0].progress, 0.3)
        self.assertEqual(settlement.buildings[0].stage, BuildingStage.UNDER_CONSTRUCTION)


class TestSummary(unittest.TestCase):
    def test_summary_counts_by_stage(self):
        settlement = Settlement(buildings=[
            Building(id=0, x=0, y=0, stage=BuildingStage.UNDER_CONSTRUCTION),
            Building(id=1, x=1, y=1, stage=BuildingStage.STANDING, condition=0.8),
            Building(id=2, x=2, y=2, stage=BuildingStage.STANDING, condition=0.4),
            Building(id=3, x=3, y=3, stage=BuildingStage.RUINED),
        ])
        summary = settlement.summary()
        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["under_construction"], 1)
        self.assertEqual(summary["standing"], 2)
        self.assertEqual(summary["ruined"], 1)
        self.assertAlmostEqual(summary["avg_condition"], 0.6, places=3)

    def test_summary_empty_settlement(self):
        summary = Settlement().summary()
        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["avg_condition"], 0.0)


class TestSerialization(unittest.TestCase):
    def test_building_round_trip(self):
        building = Building(id=1, x=2, y=3, stage=BuildingStage.STANDING, progress=1.0, condition=0.42, ruined_ticks=5)
        restored = Building.from_dict(building.to_dict())
        self.assertEqual(building.to_dict(), restored.to_dict())

    def test_settlement_round_trip(self):
        settlement = Settlement(buildings=[
            Building(id=0, x=0, y=0, stage=BuildingStage.UNDER_CONSTRUCTION, progress=0.5),
            Building(id=1, x=1, y=1, stage=BuildingStage.RUINED, ruined_ticks=100),
        ], _next_id=2)
        restored = Settlement.from_dict(settlement.to_dict())
        self.assertEqual(settlement.to_dict(), restored.to_dict())


if __name__ == "__main__":
    unittest.main()
