"""HearthBench A12 — the bench daemon (A12.1-A12.5 this pass).

`server.py`'s `create_app(runs_root)` is the real FastAPI app the UI
page (A12.1) talks to — see that module's own docstring for the full
scope, what's shipped, and what's honestly deferred (A12.6-A12.9).
"""
from __future__ import annotations

from hearthbench.daemon.server import RunRegistry, StartRunRequest, TrackedRun, create_app

__all__ = ["create_app", "RunRegistry", "StartRunRequest", "TrackedRun"]
