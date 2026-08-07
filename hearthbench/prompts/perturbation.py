"""HearthBench A3.4 — synthetic perturbation.

"Reuse `prompt_synthesis.py` to generate fixture variants so a model
can't be tuned to the exact fixture set, and rare job types get enough
cases for a stable score." `hearthmind.llm.prompt_synthesis` already
exists (FT.4, docs/AUDIT-2026-07-20.md) and is explicitly scoped to
`town_brain` today — real reuse here, not a second synthesizer.

Import isolation (A1.2): `hearthmind.llm.prompt_synthesis` is under
`hearthmind.llm`, not `.simulation`/`.agents`/`.world`.
"""
from __future__ import annotations

from typing import Callable

from .fixtures import FixtureExample, _content_hash

SynthesizerFn = Callable[[int, "int | None"], list[dict]]
"""A `(count, seed) -> [{"task", "structured_input", "prompt",
"system_prompt"}, ...]` function — `hearthmind.llm.prompt_synthesis.
synthesize_town_brain_batch` is the one real instance today. Typed
this way (not hardcoded to that one function) so a future per-task
synthesizer — the module's own docstring names this as a real,
scoped-later extension — plugs in with zero changes here."""


def synthesize_fixtures(synthesizer: SynthesizerFn, count: int, seed: int | None = None) -> list[FixtureExample]:
    """Runs any `SynthesizerFn` and wraps its output as real
    `FixtureExample`s — `synthetic=True`, `source_example_id=None` (no
    real archive line backs these), `fixture_id` prefixed `synthetic-`
    so a mixed pack can always tell organic and synthesized fixtures
    apart at a glance (A9's report-honesty discipline: a category
    scored mostly on synthetic variety, not real recorded behavior, is
    something a report should be able to say plainly)."""
    raw = synthesizer(count, seed)
    fixtures: list[FixtureExample] = []
    for i, item in enumerate(raw):
        task = item["task"]
        structured_input = item.get("structured_input") or {}
        prompt = item.get("prompt") or ""
        system_prompt = item.get("system_prompt")
        fixtures.append(FixtureExample(
            fixture_id=f"synthetic-{task}-{i:04d}",
            task=task, structured_input=structured_input, prompt=prompt, system_prompt=system_prompt,
            content_hash=_content_hash(task, structured_input, prompt, system_prompt),
            source_example_id=None, synthetic=True,
        ))
    return fixtures


def synthesize_town_brain_fixtures(count: int, seed: int | None = None) -> list[FixtureExample]:
    """The one real, wired instance — `hearthmind.llm.prompt_
    synthesis.synthesize_town_brain_batch` through `synthesize_
    fixtures` above. A rare/thin task in a real archive (the exact gap
    FT.4 was built to close) can now be padded with genuinely diverse,
    plausible synthetic fixtures at export time rather than staying
    stuck at whatever thin count the archive happens to hold."""
    from hearthmind.llm.prompt_synthesis import synthesize_town_brain_batch

    return synthesize_fixtures(synthesize_town_brain_batch, count, seed)
