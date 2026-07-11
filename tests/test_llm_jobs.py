import asyncio
import json
import unittest

from hearthmind.llm.client import OllamaClient
from hearthmind.llm.jobs import CognitionRunner
from tests._llm_fake_server import fake_ollama_server


class TestCognitionRunner(unittest.TestCase):
    def test_disabled_runner_always_uses_fallback(self):
        runner = CognitionRunner(client=None, max_concurrent=2)
        self.assertFalse(runner.enabled)

        async def go():
            return await runner.run("prompt", "system", fallback=lambda: {"goal": "wander"})

        result, used_fallback = asyncio.run(go())
        self.assertEqual(result, {"goal": "wander"})
        self.assertTrue(used_fallback)

    def test_successful_call_returns_llm_result(self):
        with fake_ollama_server(json.dumps({"goal": "socialize"})) as host:
            client = OllamaClient(host=host, model="test-model", timeout_seconds=2.0)
            runner = CognitionRunner(client=client, max_concurrent=2)
            self.assertTrue(runner.enabled)

            async def go():
                return await runner.run("prompt", "system", fallback=lambda: {"goal": "wander"})

            result, used_fallback = asyncio.run(go())
            self.assertEqual(result, {"goal": "socialize"})
            self.assertFalse(used_fallback)

    def test_unreachable_client_falls_back(self):
        client = OllamaClient(host="http://127.0.0.1:1", model="test-model", timeout_seconds=0.5)
        runner = CognitionRunner(client=client, max_concurrent=2)

        async def go():
            return await runner.run("prompt", "system", fallback=lambda: {"goal": "rest"})

        result, used_fallback = asyncio.run(go())
        self.assertEqual(result, {"goal": "rest"})
        self.assertTrue(used_fallback)

    def test_concurrency_is_bounded(self):
        # Three slow requests through a runner allowing only 1 concurrent
        # call should take roughly 3x as long as allowing all 3 at once —
        # confirms the semaphore is actually gating concurrency, not just
        # present in the code.
        with fake_ollama_server(json.dumps({"goal": "wander"}), delay=0.2) as host:
            client = OllamaClient(host=host, model="test-model", timeout_seconds=5.0)
            runner = CognitionRunner(client=client, max_concurrent=1)

            async def go():
                import time
                start = time.monotonic()
                await asyncio.gather(*[
                    runner.run("prompt", "system", fallback=lambda: {"goal": "wander"})
                    for _ in range(3)
                ])
                return time.monotonic() - start

            elapsed = asyncio.run(go())
            self.assertGreater(elapsed, 0.5)  # ~3 * 0.2s serialized, generous margin


if __name__ == "__main__":
    unittest.main()
