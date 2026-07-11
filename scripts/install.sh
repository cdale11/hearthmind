#!/bin/bash
set -e
if ! command -v conda >/dev/null; then
 echo "Conda not found."; exit 1; fi
eval "$(conda shell.bash hook)"
conda create -y -n hearthmind python=3.12
conda activate hearthmind
pip install -U pip
pip install -r requirements.txt
echo ""
echo "Installation complete."
echo "Ensure Ollama is running."
echo "Recommended model:"
echo "  ollama pull qwen3:1.7b"
