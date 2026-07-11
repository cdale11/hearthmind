import unittest

from hearthmind.llm import chronicle


class TestFallbackSummary(unittest.TestCase):
    def test_counts_births_and_deaths(self):
        events = [
            {"category": "birth", "description": "A was born."},
            {"category": "birth", "description": "B was born."},
            {"category": "death", "description": "C died."},
            {"category": "day_end", "description": "A new day begins."},
        ]
        pop_summary = {"total": 10, "awake": 8, "resting": 2}
        result = chronicle.fallback_summary(events, pop_summary, season="autumn", year=1)
        self.assertIn("2 born", result["summary"])
        self.assertIn("1 died", result["summary"])
        self.assertIn("Autumn", result["summary"])
        self.assertIn("year 1", result["summary"])

    def test_handles_no_events(self):
        result = chronicle.fallback_summary([], {"total": 5, "awake": 5, "resting": 0}, "spring", 0)
        self.assertIn("0 born", result["summary"])


class TestParseSummary(unittest.TestCase):
    def test_valid_summary_used(self):
        fallback = {"summary": "fallback text"}
        summary = chronicle.parse_summary({"summary": "A quiet season passed."}, fallback)
        self.assertEqual(summary, "A quiet season passed.")

    def test_missing_summary_uses_fallback(self):
        fallback = {"summary": "fallback text"}
        summary = chronicle.parse_summary({}, fallback)
        self.assertEqual(summary, "fallback text")

    def test_empty_summary_uses_fallback(self):
        fallback = {"summary": "fallback text"}
        summary = chronicle.parse_summary({"summary": "   "}, fallback)
        self.assertEqual(summary, "fallback text")

    def test_long_summary_truncated(self):
        fallback = {"summary": "fallback"}
        summary = chronicle.parse_summary({"summary": "x" * 2000}, fallback)
        self.assertLessEqual(len(summary), 1000)


class TestBuildPrompt(unittest.TestCase):
    def test_prompt_includes_events_and_season(self):
        events = [{"category": "birth", "description": "Aldric was born to Freya and Corwin."}]
        pop_summary = {"total": 13, "awake": 13, "resting": 0}
        prompt = chronicle.build_prompt(events, pop_summary, "summer", 2)
        self.assertIn("summer", prompt)
        self.assertIn("year 2", prompt)
        self.assertIn("Aldric was born", prompt)


if __name__ == "__main__":
    unittest.main()
