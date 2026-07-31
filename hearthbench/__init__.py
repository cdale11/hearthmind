"""HearthBench: a standalone, model-agnostic evaluation framework.

Answers "if I plug this model into Hearthmind, how good will the
experience be?" — a **selection** question, distinct from the live
simulation itself. See docs/HEARTHBENCH-RUNTIME-2026-07-23.md (Part A)
for the full spec.

Isolation boundary (A1.2, enforced mechanically by
scripts/verify_hearthbench_isolation.py, not just by convention):
this package and everything under it must never import from
`hearthmind.simulation`, `hearthmind.agents`, or `hearthmind.world` —
a benchmark run must never be able to contend with, pause, or corrupt
a live simulation. It may import read-only fixtures/schemas from a
future shared `hearthmind.cognition_contract` package (A0's own
"Rule"), and `hearthmind` itself must never import anything from
`hearthbench`.
"""

__version__ = "0.1.0"
