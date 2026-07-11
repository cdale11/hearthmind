"""Phase B: a single local LLM (via Ollama) as the world's reasoning layer.

Kept deliberately separate from the deterministic core (world/, agents/,
simulation/): everything in here is optional, off by default, and must
degrade to a deterministic fallback on any failure — see
docs/DECISIONS.md, B1.
"""
