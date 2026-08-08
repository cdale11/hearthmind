"""A real `python -m hearthbench.daemon` launcher — starts the bench
daemon (`server.create_app`) under `uvicorn`. Requires the `bench`
extra (`pip install -e .[bench]`); this module itself is the one place
in `hearthbench` that imports `uvicorn` directly, kept out of
`server.py` so `create_app` stays importable (and testable — see
`scripts/verify_a12_bench_daemon.py`) without needing a real ASGI
server installed."""
from __future__ import annotations

import argparse

from hearthbench.daemon.server import create_app


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m hearthbench.daemon")
    parser.add_argument("--runs-root", default="hearthbench_runs", help="Directory holding every real run's own subdirectory (A8).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8420)
    return parser


def main(argv: "list | None" = None) -> int:
    import uvicorn

    args = build_arg_parser().parse_args(argv)
    app = create_app(args.runs_root)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
