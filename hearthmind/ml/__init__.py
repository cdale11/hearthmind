"""Tier 6 learned-model substrate (docs/ML-ARCHITECTURE-2026-08-01.md,
Layer 0). Standalone infrastructure, same "never big-bang" discipline
as every Tier 5 Runtime module — nothing here is imported by
`simulation/engine.py` or any live gameplay code yet. Inference is
always the pure-Python forward pass (stdlib only); numpy is permitted
for offline training only (v1.34.171), gated behind the `ml` optional
extra in `pyproject.toml`.
"""
