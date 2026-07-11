#!/bin/bash
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR/.."
uvicorn hearthmind.main:app --app-dir src --host 0.0.0.0 --port 8000
