import unittest

from hearthmind.agents.agent import Agent, AgentGoal, AgentState
from hearthmind.llm.cognition import build_prompt, fallback_goal, parse_goal


class TestFallbackGoal(unittest.TestCase):
    def test_hungry_forages(self):
        result = fallback_goal(hunger=0.8, energy=0.9)
        self.assertEqual(result["goal"], "forage")

    def test_tired_rests(self):
        result = fallback_goal(hunger=0.1, energy=0.2)
        self.assertEqual(result["goal"], "rest")

    def test_content_wanders(self):
        result = fallback_goal(hunger=0.2, energy=0.8)
        self.assertEqual(result["goal"], "wander")

    def test_hunger_takes_priority_over_tiredness(self):
        result = fallback_goal(hunger=0.9, energy=0.1)
        self.assertEqual(result["goal"], "forage")


class TestParseGoal(unittest.TestCase):
    def test_valid_goal_parsed(self):
        goal, reason = parse_goal({"goal": "socialize", "reason": "lonely"})
        self.assertEqual(goal, AgentGoal.SOCIALIZE)
        self.assertEqual(reason, "lonely")

    def test_invalid_goal_defaults_to_wander(self):
        goal, _ = parse_goal({"goal": "become a dragon"})
        self.assertEqual(goal, AgentGoal.WANDER)

    def test_missing_goal_defaults_to_wander(self):
        goal, _ = parse_goal({})
        self.assertEqual(goal, AgentGoal.WANDER)

    def test_reason_truncated(self):
        _, reason = parse_goal({"goal": "rest", "reason": "x" * 500})
        self.assertLessEqual(len(reason), 200)

    def test_non_string_reason_does_not_crash(self):
        goal, reason = parse_goal({"goal": "forage", "reason": 12345})
        self.assertEqual(goal, AgentGoal.FORAGE)
        self.assertEqual(reason, "12345")


class TestBuildPrompt(unittest.TestCase):
    def test_prompt_includes_agent_state(self):
        agent = Agent(id=0, name="Aldric", x=0, y=0, hunger=0.7, energy=0.3, state=AgentState.AWAKE)
        prompt = build_prompt(agent, season="winter", weather="snowing, -2.0C, wind 0.50")
        self.assertIn("Aldric", prompt)
        self.assertIn("0.70", prompt)
        self.assertIn("winter", prompt)


if __name__ == "__main__":
    unittest.main()
