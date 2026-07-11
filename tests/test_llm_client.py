import json
import unittest

from hearthmind.llm.client import OllamaClient, OllamaUnavailable
from tests._llm_fake_server import fake_ollama_server


class TestOllamaClient(unittest.TestCase):
    def test_successful_json_round_trip(self):
        with fake_ollama_server(json.dumps({"goal": "forage", "reason": "hungry"})) as host:
            client = OllamaClient(host=host, model="test-model", timeout_seconds=2.0)
            result = client.generate_json("prompt", system="system")
            self.assertEqual(result, {"goal": "forage", "reason": "hungry"})

    def test_malformed_inner_json_raises_unavailable(self):
        with fake_ollama_server("not json at all") as host:
            client = OllamaClient(host=host, model="test-model", timeout_seconds=2.0)
            with self.assertRaises(OllamaUnavailable):
                client.generate_json("prompt")

    def test_non_200_status_raises_unavailable(self):
        with fake_ollama_server("{}", status=500) as host:
            client = OllamaClient(host=host, model="test-model", timeout_seconds=2.0)
            with self.assertRaises(OllamaUnavailable):
                client.generate_json("prompt")

    def test_unreachable_host_raises_unavailable(self):
        # Port 1 is a reserved low port almost certainly not listening.
        client = OllamaClient(host="http://127.0.0.1:1", model="test-model", timeout_seconds=1.0)
        with self.assertRaises(OllamaUnavailable):
            client.generate_json("prompt")

    def test_slow_server_times_out(self):
        with fake_ollama_server(json.dumps({"goal": "wander"}), delay=0.5) as host:
            client = OllamaClient(host=host, model="test-model", timeout_seconds=0.1)
            with self.assertRaises(OllamaUnavailable):
                client.generate_json("prompt")


if __name__ == "__main__":
    unittest.main()
