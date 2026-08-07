"""Prompt library & test definitions (A3) — SHIPPED, v1.34.277.

A3.1 frozen prompt fixtures (`fixtures.py`'s `export_fixture_pack`/
`load_fixture_pack`, real reuse of `hearthmind.llm.review_pack.
iter_examples`); A3.2 the declarative `TestCase`/`Turn` schema
(`schema.py`) + `test_case_from_fixture`; A3.3 multi-turn/stateful
cases (`Turn`'s `injected_fact`/`expects_recall_of`/
`offers_contradiction` + `render_turn_sequence`); A3.4 synthetic
perturbation (`perturbation.py`, real reuse of `hearthmind.llm.
prompt_synthesis`). See each submodule's own docstring for full
detail.
"""
from .fixtures import (
    FixtureExample,
    export_fixture_pack,
    fixture_from_archive_example,
    load_fixture_pack,
    select_fixtures_per_task,
)
from .perturbation import synthesize_fixtures, synthesize_town_brain_fixtures
from .schema import TestCase, Turn, render_turn_sequence, test_case_from_fixture

__all__ = [
    "FixtureExample",
    "TestCase",
    "Turn",
    "export_fixture_pack",
    "fixture_from_archive_example",
    "load_fixture_pack",
    "render_turn_sequence",
    "select_fixtures_per_task",
    "synthesize_fixtures",
    "synthesize_town_brain_fixtures",
    "test_case_from_fixture",
]
