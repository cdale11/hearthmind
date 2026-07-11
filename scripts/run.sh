#!/bin/bash
set -e
eval "$(conda shell.bash hook)"
conda activate hearthmind
uvicorn app.main:app --host 0.0.0.0 --port 8000
