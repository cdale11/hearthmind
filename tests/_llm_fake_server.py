"""Test-only fake Ollama server, so hearthmind/llm/client.py's real HTTP,
timeout, and JSON-parsing code paths can be exercised without a live
Ollama installation. Not a test module itself (no test_ prefix, so
`unittest discover` skips it).
"""
from __future__ import annotations

import contextlib
import http.server
import json
import threading
import time


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)  # drain the request body

            if self.server.delay:
                time.sleep(self.server.delay)

            if self.server.status != 200:
                self.send_response(self.server.status)
                self.end_headers()
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            body = json.dumps({"response": self.server.response_text}).encode("utf-8")
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client gave up (e.g. hit its own timeout) — nothing to do

    def log_message(self, format, *args):  # noqa: A002 - matches BaseHTTPRequestHandler's signature
        pass  # keep test output quiet


@contextlib.contextmanager
def fake_ollama_server(response_text: str, status: int = 200, delay: float = 0.0):
    """Yields a base URL (http://127.0.0.1:<port>) of a fake Ollama server
    that responds to POST /api/generate with `{"response": response_text}`,
    matching Ollama's actual response shape (a JSON envelope whose
    "response" field holds the model's raw text output)."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    server.response_text = response_text
    server.status = status
    server.delay = delay
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
