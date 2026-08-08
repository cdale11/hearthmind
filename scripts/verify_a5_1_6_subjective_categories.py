#!/usr/bin/env python3
"""HearthBench A5.1-A5.6 — the six subjective benchmark categories
(Dialogue/Personality/Memory/Beliefs/Planning/Village cognition), plus
A4.2's `JudgeScorer` generalization that makes them possible. Real
production-path checks, no unittest, same standalone-script convention
as every sibling `verify_*.py`.

Real HTTP round-trips (never a mocked adapter) through the exact same
`_CapturingHandler`/`OpenAICompatAdapter` technique `scripts/verify_a4_
scoring.py` already established for A4.2's own dialogue rubric.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthbench.adapters import OpenAICompatAdapter
from hearthbench.prompts.schema import render_turn_sequence
from hearthbench.scoring import DEFAULT_REGISTRY
from hearthbench.scoring.judge import (
    JUDGE_RUBRIC_PROMPT,
    JUDGE_RUBRIC_VERSION,
    JudgeScorer,
    _JUDGE_AXES,
    build_judge_prompt,
)
from hearthbench.scoring.types import CaseResult
from hearthbench.tests import (
    BELIEFS_CATEGORY,
    CATEGORY_REGISTRY,
    DIALOGUE_CATEGORY,
    MEMORY_CATEGORY,
    NO_AMBIENT_FILLER_SCORER,
    PERSONALITY_CATEGORY,
    PLANNING_CATEGORY,
    VILLAGE_COGNITION_CATEGORY,
    build_beliefs_cases,
    build_beliefs_judge_scorer,
    build_dialogue_cases,
    build_dialogue_judge_scorer,
    build_memory_cases,
    build_memory_judge_scorer,
    build_personality_cases,
    build_personality_judge_scorer,
    build_planning_cases,
    build_planning_judge_scorer,
    build_village_cognition_cases,
    build_village_cognition_judge_scorer,
)

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


class _CapturingHandler(BaseHTTPRequestHandler):
    def _handle(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        try:
            self.server.last_request_json = json.loads(body) if body else None
        except json.JSONDecodeError:
            self.server.last_request_json = None
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        response = self.server.canned_responses[self.server.call_count % len(self.server.canned_responses)]
        self.server.call_count += 1
        self.wfile.write(json.dumps(response).encode("utf-8"))

    def do_POST(self):
        self._handle()

    def log_message(self, *args):
        pass


def _start_fake_judge_server(rubric_answers: list) -> HTTPServer:
    responses = [
        {"choices": [{"message": {"content": json.dumps(answer)}}], "usage": {"prompt_tokens": 10, "completion_tokens": 20}}
        for answer in rubric_answers
    ]
    server = HTTPServer(("127.0.0.1", 0), _CapturingHandler)
    server.canned_responses = responses
    server.call_count = 0
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _adapter_for(server: HTTPServer, model: str = "fake-judge") -> OpenAICompatAdapter:
    return OpenAICompatAdapter(endpoint=f"http://{server.server_address[0]}:{server.server_address[1]}/v1", model=model)


CATEGORY_TABLE = {
    "dialogue": (DIALOGUE_CATEGORY, 15.0, build_dialogue_cases, build_dialogue_judge_scorer, "judge_dialogue_quality"),
    "personality": (PERSONALITY_CATEGORY, 10.0, build_personality_cases, build_personality_judge_scorer, "judge_personality_quality"),
    "memory": (MEMORY_CATEGORY, 12.0, build_memory_cases, build_memory_judge_scorer, "judge_memory_quality"),
    "beliefs": (BELIEFS_CATEGORY, 12.0, build_beliefs_cases, build_beliefs_judge_scorer, "judge_beliefs_quality"),
    "planning": (PLANNING_CATEGORY, 8.0, build_planning_cases, build_planning_judge_scorer, "judge_planning_quality"),
    "village_cognition": (VILLAGE_COGNITION_CATEGORY, 10.0, build_village_cognition_cases, build_village_cognition_judge_scorer, "judge_village_cognition_quality"),
}


def main() -> int:
    # --- A1.2 firewall over every new/touched hearthbench file --------------
    new_files = [
        "hearthbench/tests/dialogue.py", "hearthbench/tests/personality.py", "hearthbench/tests/memory.py",
        "hearthbench/tests/beliefs.py", "hearthbench/tests/planning.py", "hearthbench/tests/village_cognition.py",
        "hearthbench/tests/__init__.py", "hearthbench/scoring/judge.py", "hearthbench/reporting/score.py",
    ]
    banned = []
    for rel in new_files:
        path = os.path.join(os.path.dirname(__file__), "..", rel)
        tree = ast.parse(open(path).read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(
                ("hearthmind.simulation", "hearthmind.agents", "hearthmind.world")
            ):
                banned.append(f"{rel}: {node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(("hearthmind.simulation", "hearthmind.agents", "hearthmind.world")):
                        banned.append(f"{rel}: {alias.name}")
    check("A1.2 firewall: every new/touched file imports nothing banned", not banned, str(banned))

    # --- JudgeScorer generalization: backward compatibility -----------------
    fake_adapter = OpenAICompatAdapter(endpoint="http://127.0.0.1:1", model="unused")
    default_judge = JudgeScorer(fake_adapter)
    check("JudgeScorer() with no rubric args defaults to the original JUDGE_RUBRIC_PROMPT",
          default_judge.rubric_prompt == JUDGE_RUBRIC_PROMPT)
    check("JudgeScorer() with no rubric args defaults to the original _JUDGE_AXES",
          default_judge.axes == _JUDGE_AXES)
    check("JudgeScorer() with no rubric args defaults to the original JUDGE_RUBRIC_VERSION",
          default_judge.rubric_version == JUDGE_RUBRIC_VERSION)
    check("build_judge_prompt() with no rubric_prompt arg reproduces the original dialogue prompt byte-for-byte",
          build_judge_prompt("out", "ctx") == JUDGE_RUBRIC_PROMPT.format(context="ctx", output_text="out"))
    default_scorer = default_judge.as_scorer()
    check("JudgeScorer.as_scorer() with no args still defaults to judge_dialogue_quality/dialogue (unchanged)",
          default_scorer.id == "judge_dialogue_quality" and default_scorer.category == "dialogue"
          and default_scorer.version == f"rubric-{JUDGE_RUBRIC_VERSION}")

    custom_prompt = "Score {output_text} against {context}. Respond JSON."
    custom_judge = JudgeScorer(fake_adapter, rubric_prompt=custom_prompt, axes=("x", "y"), rubric_version="custom-1")
    check("JudgeScorer(): a supplied rubric_prompt is stored, not silently ignored", custom_judge.rubric_prompt == custom_prompt)
    check("JudgeScorer(): supplied axes are stored, not silently ignored", custom_judge.axes == ("x", "y"))
    check("JudgeScorer(): a supplied rubric_version is stored, not silently ignored", custom_judge.rubric_version == "custom-1")
    check("build_judge_prompt(): a supplied rubric_prompt template is used instead of the default",
          build_judge_prompt("O", "C", rubric_prompt=custom_prompt) == "Score O against C. Respond JSON.")

    # --- Six real Category objects, weights matching A10.1's own table -----
    for cid, (category, expected_weight, build_cases, build_judge, judge_id) in CATEGORY_TABLE.items():
        check(f"{cid}: Category.id matches its own registry key", category.id == cid)
        check(f"{cid}: Category.weight matches A10.1's own stated default", category.weight == expected_weight,
              f"{category.weight} vs {expected_weight}")
        check(f"{cid}: registered in the real CATEGORY_REGISTRY as the same object",
              CATEGORY_REGISTRY.get(cid) is category)
        check(f"{cid}: scorer_ids names the real judge scorer id", judge_id in category.scorer_ids)

        cases = build_cases()
        check(f"{cid}: build_*_cases() returns at least 2 real hand-authored cases", len(cases) >= 2, str(len(cases)))
        check(f"{cid}: every case's category field matches", all(c.category == cid for c in cases))
        check(f"{cid}: every case declares a non-empty scorer set matching the category's own scorer_ids",
              all(c.scorers == list(category.scorer_ids) for c in cases))
        check(f"{cid}: every case carries a real system_prompt or real turns",
              all(c.system_prompt or c.turns for c in cases))
        check(f"{cid}: every case renders to a real, non-crashing turn sequence",
              all(isinstance(render_turn_sequence(c), list) for c in cases))

    # --- Rubrics are genuinely distinct, not accidental copies --------------
    scorer_specs = {}
    for cid, (_category, _w, _cases, build_judge, judge_id) in CATEGORY_TABLE.items():
        scorer_specs[cid] = build_judge(fake_adapter)
        check(f"{cid}: build_*_judge_scorer() produces the expected scorer id/category",
              scorer_specs[cid].id == judge_id and scorer_specs[cid].category == cid)
        check(f"{cid}: build_*_judge_scorer() produces a real Tier 2 scorer", scorer_specs[cid].tier == 2)

    check("dialogue's judge scorer reuses the ORIGINAL rubric prompt exactly (A5.1 reuses A4.2's default unchanged)",
          scorer_specs["dialogue"].version == f"rubric-{JUDGE_RUBRIC_VERSION}")

    # Re-checking distinctness needs each category's own RAW rubric text,
    # not just the wrapped Scorer -- import each module's own constant
    # directly rather than re-deriving it from the Scorer object.
    non_dialogue_prompts = set()
    from hearthbench.tests.personality import PERSONALITY_RUBRIC_PROMPT, _PERSONALITY_AXES
    from hearthbench.tests.memory import MEMORY_RUBRIC_PROMPT, _MEMORY_AXES
    from hearthbench.tests.beliefs import BELIEFS_RUBRIC_PROMPT, _BELIEFS_AXES
    from hearthbench.tests.planning import PLANNING_RUBRIC_PROMPT, _PLANNING_AXES
    from hearthbench.tests.village_cognition import VILLAGE_COGNITION_RUBRIC_PROMPT, _VILLAGE_COGNITION_AXES

    rubric_prompts = {
        "personality": PERSONALITY_RUBRIC_PROMPT, "memory": MEMORY_RUBRIC_PROMPT,
        "beliefs": BELIEFS_RUBRIC_PROMPT, "planning": PLANNING_RUBRIC_PROMPT,
        "village_cognition": VILLAGE_COGNITION_RUBRIC_PROMPT,
    }
    rubric_axes = {
        "personality": _PERSONALITY_AXES, "memory": _MEMORY_AXES,
        "beliefs": _BELIEFS_AXES, "planning": _PLANNING_AXES,
        "village_cognition": _VILLAGE_COGNITION_AXES,
    }
    for cid, prompt in rubric_prompts.items():
        check(f"{cid}: rubric prompt is genuinely distinct from Dialogue's default rubric", prompt != JUDGE_RUBRIC_PROMPT)
        check(f"{cid}: judge axes are genuinely distinct from Dialogue's default axes", rubric_axes[cid] != _JUDGE_AXES)
        non_dialogue_prompts.add(prompt)
    check("all five non-dialogue rubric prompts are pairwise distinct from each other (no accidental copy/paste)",
          len(non_dialogue_prompts) == 5, str(len(non_dialogue_prompts)))

    # --- no_ambient_filler (new A5.1 Tier-1 scorer) --------------------------
    check("no_ambient_filler is registered in DEFAULT_REGISTRY", DEFAULT_REGISTRY.get("no_ambient_filler") is not None)
    clean_case = build_dialogue_cases()[0]
    clean_result = CaseResult(task="dialogue", output={"line": "The mast cracked clean through last Tuesday, and I've no coin to fix it."})
    clean_detail = NO_AMBIENT_FILLER_SCORER.score(clean_case, clean_result)
    check("no_ambient_filler: a substantive line with no filler phrase scores 1.0/passes",
          clean_detail.value == 1.0 and clean_detail.passed is True)
    filler_result = CaseResult(task="dialogue", output={"line": "Well said. True enough. Such is life, I suppose."})
    filler_detail = NO_AMBIENT_FILLER_SCORER.score(clean_case, filler_result)
    check("no_ambient_filler: a line leaning on stock agreement phrases is caught and fails",
          filler_detail.value is not None and filler_detail.value < 1.0 and filler_detail.passed is False,
          str(filler_detail.detail))
    heavy_filler_result = CaseResult(task="dialogue", output={
        "line": "Well said. True enough. Such is life. Fair point. No argument there. As you say."})
    heavy_detail = NO_AMBIENT_FILLER_SCORER.score(clean_case, heavy_filler_result)
    check("no_ambient_filler: heavy reliance on filler is capped at 0.0, not an unbounded free-fall",
          heavy_detail.value == 0.0, str(heavy_detail.detail))
    empty_result = CaseResult(task="dialogue", output={})
    empty_detail = NO_AMBIENT_FILLER_SCORER.score(clean_case, empty_result)
    check("no_ambient_filler: a genuinely empty output degrades to None, not a fake perfect score",
          empty_detail.value is None)

    # --- Memory/Beliefs: real multi-turn machinery is genuinely exercised ---
    memory_cases = {c.id: c for c in build_memory_cases()}
    recall_case = memory_cases["memory:recall_after_gap"]
    rendered = render_turn_sequence(recall_case)
    check("memory:recall_after_gap renders 3 real turns", len(rendered) == 3)
    check("memory:recall_after_gap's final turn expects recall of the turn-0 injected fact",
          rendered[2]["expects_recall_of"] == recall_case.turns[0].injected_fact)
    check("memory:recall_after_gap's context accumulates the injected fact by the final turn",
          any(recall_case.turns[0].injected_fact == v for v in rendered[2]["context"].values()))

    contradiction_case = memory_cases["memory:contradiction_resistance"]
    contradiction_rendered = render_turn_sequence(contradiction_case)
    check("memory:contradiction_resistance has a real offers_contradiction turn",
          any(t["offers_contradiction"] for t in contradiction_rendered))
    check("memory:contradiction_resistance's final turn still expects recall of the ORIGINAL (not the contradicting) fact",
          contradiction_rendered[2]["expects_recall_of"] == contradiction_case.turns[0].injected_fact)

    beliefs_cases = {c.id: c for c in build_beliefs_cases()}
    revision_case = beliefs_cases["beliefs:revision_on_new_evidence"]
    revision_rendered = render_turn_sequence(revision_case)
    check("beliefs:revision_on_new_evidence has a real offers_contradiction (new-evidence) turn",
          any(t["offers_contradiction"] for t in revision_rendered))
    check("beliefs:revision_on_new_evidence's final turn expects recall of the NEW evidence (the inverse of Memory's case)",
          revision_rendered[2]["expects_recall_of"] == revision_case.turns[1].injected_fact
          and revision_case.turns[1].injected_fact != revision_case.turns[0].injected_fact)

    # --- Real end-to-end judge round-trips, two representative categories ---
    memory_server = _start_fake_judge_server([
        {"recall_accuracy": 5, "appropriate_forgetting": 4, "contradiction_resistance": 5, "reason": "held to the established fact"},
    ])
    try:
        memory_adapter = _adapter_for(memory_server, model="fake-memory-judge")
        memory_scorer = build_memory_judge_scorer(memory_adapter)
        memory_case = memory_cases["memory:recall_after_gap"]
        result = CaseResult(task="memory", output={"line": "Aye, still no word from the harbor master about your boat."})
        detail = memory_scorer.score(memory_case, result, context={"context_text": "Tobin's boat mast broke last week"})
        check("memory judge: a real HTTP round-trip produces a normalized composite",
              detail.value is not None and 0.0 <= detail.value <= 1.0)
        check("memory judge: axis_scores uses Memory's OWN axes, not Dialogue's",
              set(detail.detail["axis_scores"].keys()) == set(_MEMORY_AXES))
        check("memory judge: rubric_version/judge_model recorded, category-specific version distinct from dialogue's",
              detail.detail.get("judge_model") is not None and detail.detail.get("rubric_version") == "1")
        check("memory judge: the real request actually hit the fake server", memory_server.call_count == 1)
        check("memory judge: the sent prompt used Memory's own rubric text, not Dialogue's",
              "recall_accuracy" in (memory_server.last_request_json.get("messages", [{}])[-1].get("content", "")
                                     if memory_server.last_request_json else ""))
    finally:
        memory_server.shutdown()

    personality_server = _start_fake_judge_server([
        {"voice_consistency": 2, "distinctiveness": 3, "trait_plausibility": 1, "reason": "reads as generic, not blunt"},
    ])
    try:
        personality_adapter = _adapter_for(personality_server, model="fake-personality-judge")
        personality_scorer = build_personality_judge_scorer(personality_adapter)
        personality_case = build_personality_cases()[0]
        result = CaseResult(task="personality", output={"line": "I suppose the tax could be fine, if others think so."})
        detail = personality_scorer.score(personality_case, result, context={"context_text": personality_case.system_prompt})
        check("personality judge: a real HTTP round-trip produces a normalized composite",
              detail.value is not None and 0.0 <= detail.value <= 1.0)
        check("personality judge: axis_scores uses Personality's OWN axes",
              set(detail.detail["axis_scores"].keys()) == set(_PERSONALITY_AXES))
        expected_composite = ((2 - 1) / 4 + (3 - 1) / 4 + (1 - 1) / 4) / 3
        check("personality judge: composite matches hand-computed rubric average",
              abs(detail.value - expected_composite) < 1e-9, f"{detail.value} vs {expected_composite}")
    finally:
        personality_server.shutdown()

    # --- measure_self_consistency composes with a custom rubric too ---------
    from hearthbench.scoring.judge import measure_self_consistency
    consistency_server = _start_fake_judge_server([
        {"goal_coherence": 5, "horizon_realism": 5, "adaptation_when_blocked": 5, "reason": "coherent"},
        {"goal_coherence": 4, "horizon_realism": 4, "adaptation_when_blocked": 4, "reason": "mostly coherent"},
        {"goal_coherence": 5, "horizon_realism": 5, "adaptation_when_blocked": 5, "reason": "coherent"},
    ])
    try:
        planning_adapter = _adapter_for(consistency_server, model="fake-planning-judge")
        from hearthbench.tests.planning import PLANNING_RUBRIC_PROMPT as _PP, PLANNING_RUBRIC_VERSION as _PV
        planning_scorer_obj = JudgeScorer(planning_adapter, rubric_prompt=_PP, axes=_PLANNING_AXES, rubric_version=_PV)
        spread = measure_self_consistency(planning_scorer_obj, "Gather timber, then repair the granary roof.", n=3)
        check("measure_self_consistency: composes cleanly with a custom rubric, 3 real scored runs",
              spread["n_scored"] == 3)
        check("measure_self_consistency: a real stdev computed over genuinely varied answers",
              spread["stdev"] is not None and spread["stdev"] >= 0.0)
    finally:
        consistency_server.shutdown()

    print(f"\n{len(FAILURES)} failure(s)." if FAILURES else "\nAll checks passed.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
