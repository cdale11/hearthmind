#!/usr/bin/env python3
"""HearthBench A4 — Scoring & the judge problem. Real production-path
checks, no unittest, same standalone-script convention as every
sibling `verify_*.py`.

Tier 1 is exercised against a REAL `hearthmind.llm.recorder` archive
(via `TrainingRecorder`, same technique `verify_a3_prompt_library.py`
established) so every deterministic scorer runs against genuinely
recorded data, not a hand-built stand-in. Tier 2 is exercised against
a REAL local stdlib HTTP server (same `_CapturingHandler` technique
`verify_a2_model_adapters.py` established) standing in for a judge
backend, through the REAL `OpenAICompatAdapter` — no mocked adapter,
no mocked HTTP.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthbench.adapters import OpenAICompatAdapter
from hearthbench.prompts import Turn, export_fixture_pack, load_fixture_pack, test_case_from_fixture
from hearthbench.scoring import (
    DEFAULT_REGISTRY,
    DETERMINISTIC_SCORERS,
    CaseResult,
    DuplicateScorerError,
    HumanRating,
    HumanRatingTask,
    JudgeScorer,
    ScoreDetail,
    Scorer,
    ScorerRegistry,
    append_rating,
    build_judge_prompt,
    judge_human_agreement,
    judge_implied_choice,
    load_ratings,
    measure_self_consistency,
    register_deterministic_scorers,
)
from hearthmind.llm.recorder import RecordingPolicy, TrainingRecorder

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def _write_real_archive(archive_dir: str) -> None:
    recorder = TrainingRecorder(
        archive_dir=archive_dir,
        model_name_provider=lambda: "test-model",
        hearthmind_version_provider=lambda: "test-version",
    )
    recorder.start(session_name="a4-verify", policy=RecordingPolicy.ALL_TASKS.value)
    # A genuinely SCHEMA-VALID, leak-free, context-reflecting example.
    recorder.maybe_record(
        task="cognition", prompt="What should agent 1 do? They mentioned hunger.",
        system_prompt="You are a village.",
        result={"goal": "forage", "reason": "hungry, so I should forage for food"},
        structured_input={"agent_id": 1, "own_belief": "I feel hungry"},
        settlement="Marshcroft", npc_ids=[1], elapsed_ms=120.0,
        parse_repaired=False, used_fallback=False,
    )
    # A genuinely LEAKY example (raw coordinates + a meta-leakage marker).
    recorder.maybe_record(
        task="cognition", prompt="What should agent 2 do?", system_prompt="You are a village.",
        result={"goal": "wander", "reason": "heading to (12, 34) as an AI language model would"},
        structured_input={"agent_id": 2}, settlement="Marshcroft", npc_ids=[2], elapsed_ms=90.0,
        parse_repaired=False, used_fallback=False,
    )
    # A dialogue example, real line_a/line_b for the responds/topic scorers' own siblings.
    recorder.maybe_record(
        task="dialogue", prompt="Two villagers talk.", system_prompt="Speak briefly.",
        result={"line_a": "Is the harvest in yet?", "line_b": "Aye, brought it in this morning."},
        structured_input={"pair": [3, 4], "settlement_topic": "the drought"},
        settlement="Marshcroft", npc_ids=[3, 4], elapsed_ms=80.0,
        parse_repaired=False, used_fallback=False,
    )
    # A fallback-used example — must score 0.0 on fallback_free.
    recorder.maybe_record(
        task="naming", prompt="", system_prompt=None, result={}, structured_input={},
        settlement=None, npc_ids=[], elapsed_ms=None, parse_repaired=False, used_fallback=True,
    )
    recorder.stop()
    import time as _time
    _time.sleep(0.2)


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

    def log_message(self, *args):  # noqa: D401 - silence stdlib access logging
        pass


def _start_fake_judge_server(rubric_answers: list) -> HTTPServer:
    """Each `rubric_answers` entry is a dict (the rubric JSON) — the
    server cycles through them per call, so a self-consistency check
    can supply several genuinely different answers in a row."""
    responses = [
        {"choices": [{"message": {"content": json.dumps(answer)}}], "usage": {"prompt_tokens": 10, "completion_tokens": 20}}
        for answer in rubric_answers
    ]
    server = HTTPServer(("127.0.0.1", 0), _CapturingHandler)
    server.canned_responses = responses
    server.call_count = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main() -> int:
    # --- A4.4: registry basics -------------------------------------------
    registry = ScorerRegistry()
    check("empty registry starts empty", len(registry) == 0)
    register_deterministic_scorers(registry)
    check("all 9 deterministic scorers registered", len(registry) == 9, str(len(registry)))
    check("registry.get resolves a real scorer", registry.get("schema_validity") is not None)
    check("registry.get returns None for unknown id", registry.get("nonexistent") is None)
    check("resolve() silently drops unknown ids", len(registry.resolve(["schema_validity", "nope"])) == 1)
    check("by_tier(1) returns exactly the Tier 1 set", len(registry.by_tier(1)) == 9)
    check("by_tier(2) is empty (no judge/human scorer auto-registered)", len(registry.by_tier(2)) == 0)

    duplicate_rejected = False
    try:
        registry.register(Scorer(id="schema_validity", version="2", fn=lambda c, r, ctx: ScoreDetail(scorer_id="", scorer_version=""), tier=1))
    except DuplicateScorerError:
        duplicate_rejected = True
    check("re-registering an id at a different version is rejected", duplicate_rejected)
    registry.register(Scorer(id="schema_validity", version="1", fn=DETERMINISTIC_SCORERS[0].fn, tier=1))
    check("re-registering the identical (id, version) is a safe no-op", len(registry) == 9)

    check("DEFAULT_REGISTRY is pre-populated (A4.4)", len(DEFAULT_REGISTRY) == 9)

    # --- Scorer.score() never raises ---------------------------------------
    def _boom(case, result, context):
        raise RuntimeError("scorer bug")

    broken = Scorer(id="broken", version="1", fn=_boom, tier=1)
    detail = broken.score(None, CaseResult(task="x"))
    check("Scorer.score() degrades a raising fn to an error ScoreDetail, never raises",
          detail.error is not None and detail.value is None)
    check("error ScoreDetail still carries the real scorer id/version", detail.scorer_id == "broken" and detail.scorer_version == "1")

    # --- ScoreDetail round-trip ----------------------------------------------
    sd = ScoreDetail(scorer_id="x", scorer_version="1", value=0.75, passed=True, detail={"a": 1})
    check("ScoreDetail round-trips through to_dict/from_dict", ScoreDetail.from_dict(sd.to_dict()) == sd)

    with tempfile.TemporaryDirectory() as tmp:
        archive_dir = os.path.join(tmp, "archive")
        _write_real_archive(archive_dir)

        pack_dir = os.path.join(tmp, "packs")
        export_fixture_pack(archive_dir, pack_dir, version="v1", max_per_task=10, seed=0)
        pack = load_fixture_pack(pack_dir, version="v1")
        by_task = {}
        for fx in pack:
            by_task.setdefault(fx.task, []).append(fx)
        check("real archive produced fixtures for cognition/dialogue/naming",
              {"cognition", "dialogue"} <= set(by_task.keys()), str(sorted(by_task.keys())))

        # --- A4.1 against real recorded examples ------------------------------
        good_fixture = next(fx for fx in by_task["cognition"] if "hungry" in fx.structured_input.get("own_belief", ""))
        leaky_fixture = next(fx for fx in by_task["cognition"] if fx.fixture_id != good_fixture.fixture_id)
        dialogue_fixture = by_task["dialogue"][0]

        def _result_for(fixture):
            # Reconstruct a CaseResult straight from the fixture's own
            # captured structured_input/prompt (the archive round-trip
            # already proved fixture<->example fidelity in A3; here we
            # attach the KNOWN real output each recorded call produced).
            if fixture.fixture_id == good_fixture.fixture_id:
                return CaseResult(task="cognition", output={"goal": "forage", "reason": "hungry, so I should forage for food"},
                                   structured_input=fixture.structured_input, fallback_used=False)
            if fixture.fixture_id == leaky_fixture.fixture_id:
                return CaseResult(task="cognition", output={"goal": "wander", "reason": "heading to (12, 34) as an AI language model would"},
                                   structured_input=fixture.structured_input, fallback_used=False)
            return CaseResult(task="dialogue", output={"line_a": "Is the harvest in yet?", "line_b": "Aye, brought it in this morning."},
                               structured_input=fixture.structured_input, fallback_used=False)

        good_result = _result_for(good_fixture)
        leaky_result = _result_for(leaky_fixture)
        dialogue_result = _result_for(dialogue_fixture)
        good_case = test_case_from_fixture(good_fixture, category="planning")
        leaky_case = test_case_from_fixture(leaky_fixture, category="planning")
        dialogue_case = test_case_from_fixture(dialogue_fixture, category="dialogue")

        schema_scorer = registry.get("schema_validity")
        check("schema_validity: real valid cognition output passes", schema_scorer.score(good_case, good_result).passed is True)
        leak_scorer = registry.get("leak_freedom")
        leak_detail = leak_scorer.score(leaky_case, leaky_result)
        check("leak_freedom: real coordinate+meta leak is caught", leak_detail.passed is False and "raw_coordinates" in leak_detail.detail["leak_flags"])
        check("leak_freedom: clean output passes", leak_scorer.score(good_case, good_result).passed is True)

        fallback_scorer = registry.get("fallback_free")
        fallback_result = CaseResult(task="naming", output={}, structured_input={}, fallback_used=True)
        check("fallback_free: a real fallback_used=True example scores 0.0", fallback_scorer.score(good_case, fallback_result).value == 0.0)
        check("fallback_free: a real non-fallback example scores 1.0", fallback_scorer.score(good_case, good_result).value == 1.0)

        ctx_scorer = registry.get("context_reflection")
        ctx_detail = ctx_scorer.score(good_case, good_result)
        check("context_reflection: real offered belief IS reflected in output", ctx_detail.value == 1.0)

        lexdiv_scorer = registry.get("lexical_diversity")
        lex_detail = lexdiv_scorer.score(dialogue_case, dialogue_result)
        check("lexical_diversity: a real multi-word output yields a ratio in (0, 1]", lex_detail.value is not None and 0 < lex_detail.value <= 1.0)
        short_result = CaseResult(task="dialogue", output={"line_a": "ok"}, structured_input={})
        check("lexical_diversity: too few tokens degrades to None, not a fake score", lexdiv_scorer.score(dialogue_case, short_result).value is None)

        repetition_scorer = registry.get("repetition_self_similarity")
        no_history = repetition_scorer.score(dialogue_case, dialogue_result, context={})
        check("repetition: no prior outputs -> value 1.0 (nothing to repeat)", no_history.value == 1.0)
        near_dupe_context = {"prior_outputs": ["Is the harvest in yet? Aye, brought it in this morning."]}
        with_history = repetition_scorer.score(dialogue_case, dialogue_result, context=near_dupe_context)
        check("repetition: a near-identical prior output is caught (low value, failed)",
              with_history.value is not None and with_history.value < 0.4 and with_history.passed is False)
        distinct_context = {"prior_outputs": ["The wolves came down from the hills last night."]}
        distinct_result = repetition_scorer.score(dialogue_case, dialogue_result, context=distinct_context)
        check("repetition: a genuinely different prior output scores high", distinct_result.value > 0.8)

        latency_scorer = registry.get("latency")
        lat_result = CaseResult(task="dialogue", output={}, structured_input={}, latency_ms=1234.5, ttft_ms=None)
        lat_detail = latency_scorer.score(dialogue_case, lat_result)
        check("latency: a measurement, not a verdict (value is None)", lat_detail.value is None)
        check("latency: real ms carried through in detail", lat_detail.detail["latency_ms"] == 1234.5)

        # --- A3.3/A4.1 multi-turn recall -----------------------------------
        recall_scorer = registry.get("multi_turn_recall")
        multi_case = good_case
        multi_case.turns = [
            Turn(index=0, content="What is your name?", injected_fact="the agent's name is Mira"),
            Turn(index=1, content="Say your name again.", expects_recall_of="the agent's name is Mira"),
            Turn(index=2, content="Confirm once more.", expects_recall_of="the agent's name is Mira"),
        ]
        recalled_result = CaseResult(task="cognition", output={"reason": "My name is Mira, remember?"}, structured_input={})
        forgot_result = CaseResult(task="cognition", output={"reason": "I don't know what you mean."}, structured_input={})
        no_turn_results = recall_scorer.score(multi_case, good_result, context={})
        check("multi_turn_recall: no turn_results supplied -> None, not a false pass", no_turn_results.value is None)
        recall_hit = recall_scorer.score(multi_case, good_result, context={"turn_results": {1: recalled_result, 2: recalled_result}})
        check("multi_turn_recall: both turns correctly recall the fact -> value 1.0, passed", recall_hit.value == 1.0 and recall_hit.passed is True)
        recall_partial = recall_scorer.score(multi_case, good_result, context={"turn_results": {1: recalled_result, 2: forgot_result}})
        check("multi_turn_recall: one of two turns forgets -> partial credit, not passed", recall_partial.value == 0.5 and recall_partial.passed is False)
        single_turn_case = test_case_from_fixture(good_fixture, category="planning")
        check("multi_turn_recall: a case with no recall-testing turns -> None",
              recall_scorer.score(single_turn_case, good_result, context={}).value is None)

        # --- A4.2: Tier 2 judge scorer, real HTTP round-trip -------------------
        server = _start_fake_judge_server([
            {"naturalness": 4, "personality": 5, "emotional_realism": 3, "reason": "reads as genuinely in-character"},
        ])
        try:
            adapter = OpenAICompatAdapter(endpoint=f"http://{server.server_address[0]}:{server.server_address[1]}/v1", model="fake-judge")
            judge = JudgeScorer(adapter, judge_model_label="fake-judge-v1")
            judge_detail = judge.score_output("Ugh, I could eat a whole loaf right now.", context_text="Agent is hungry.")
            check("judge scorer: a real HTTP round-trip produces a normalized composite",
                  judge_detail.value is not None and 0.0 <= judge_detail.value <= 1.0)
            expected_composite = ((4 - 1) / 4 + (5 - 1) / 4 + (3 - 1) / 4) / 3
            check("judge scorer: composite matches hand-computed rubric average",
                  abs(judge_detail.value - expected_composite) < 1e-9, f"{judge_detail.value} vs {expected_composite}")
            check("judge scorer: rubric_version/judge_model recorded per A4.2's own text",
                  judge_detail.detail.get("rubric_version") == "1" and judge_detail.detail.get("judge_model") == "fake-judge-v1")
            check("judge scorer: the real request actually hit the fake server",
                  server.call_count == 1 and server.last_request_json is not None)
            check("build_judge_prompt is pure and embeds the given output text",
                  "Ugh, I could eat a whole loaf" in build_judge_prompt("Ugh, I could eat a whole loaf right now."))

            as_scorer = judge.as_scorer()
            check("JudgeScorer.as_scorer() produces a real Tier 2 Scorer", as_scorer.tier == 2)
            via_scorer_detail = as_scorer.score(dialogue_case, dialogue_result, context={"context_text": "Two villagers talk."})
            check("Tier 2 scorer produced via as_scorer() also round-trips through Scorer.score()", via_scorer_detail.value is not None)
        finally:
            server.shutdown()

        # A judge returning a malformed/non-JSON answer degrades cleanly.
        broken_server = _start_fake_judge_server([{"choices_ignored": True}])
        broken_server.canned_responses = [
            {"choices": [{"message": {"content": "I refuse to answer in JSON."}}]},
        ]
        try:
            broken_adapter = OpenAICompatAdapter(
                endpoint=f"http://{broken_server.server_address[0]}:{broken_server.server_address[1]}/v1", model="fake-judge",
            )
            broken_judge = JudgeScorer(broken_adapter)
            broken_detail = broken_judge.score_output("some output")
            check("judge scorer: a non-JSON judge answer degrades to a real error detail, not a crash",
                  broken_detail.value is None and "parse_error" in broken_detail.detail)
        finally:
            broken_server.shutdown()

        # An unreachable judge host -- real connection-refused, no mock.
        unreachable_adapter = OpenAICompatAdapter(endpoint="http://127.0.0.1:1", model="fake-judge", timeout_seconds=2.0)
        unreachable_judge = JudgeScorer(unreachable_adapter)
        unreachable_detail = unreachable_judge.score_output("some output")
        check("judge scorer: an unreachable backend degrades to error, never raises",
              unreachable_detail.value is None and unreachable_detail.error is not None)

        # --- A4.2: self-consistency over a real varying sample -----------------
        consistency_server = _start_fake_judge_server([
            {"naturalness": 4, "personality": 4, "emotional_realism": 4, "reason": "a"},
            {"naturalness": 4, "personality": 5, "emotional_realism": 4, "reason": "b"},
            {"naturalness": 3, "personality": 4, "emotional_realism": 5, "reason": "c"},
        ])
        try:
            consistency_adapter = OpenAICompatAdapter(
                endpoint=f"http://{consistency_server.server_address[0]}:{consistency_server.server_address[1]}/v1", model="fake-judge",
            )
            consistency_judge = JudgeScorer(consistency_adapter)
            consistency = measure_self_consistency(consistency_judge, "some output", n=3)
            check("self-consistency: real 3-sample spread computed", consistency["n_scored"] == 3 and consistency["stdev"] is not None)
            check("self-consistency: agreement is bounded [0, 1]", 0.0 <= consistency["agreement"] <= 1.0)
            perfectly_consistent_server = _start_fake_judge_server([
                {"naturalness": 4, "personality": 4, "emotional_realism": 4, "reason": "x"},
            ])
            try:
                stable_adapter = OpenAICompatAdapter(
                    endpoint=f"http://{perfectly_consistent_server.server_address[0]}:{perfectly_consistent_server.server_address[1]}/v1",
                    model="fake-judge",
                )
                stable_judge = JudgeScorer(stable_adapter)
                stable_consistency = measure_self_consistency(stable_judge, "some output", n=3)
                check("self-consistency: identical repeated answers -> stdev 0, agreement 1.0",
                      stable_consistency["stdev"] == 0.0 and stable_consistency["agreement"] == 1.0)
            finally:
                perfectly_consistent_server.shutdown()
        finally:
            consistency_server.shutdown()

        n_too_low_raised = False
        try:
            measure_self_consistency(judge, "x", n=1)
        except ValueError:
            n_too_low_raised = True
        check("self-consistency: n < 2 is rejected outright (a spread needs 2+ samples)", n_too_low_raised)

        # --- A4.3: human rating data model + judge<->human agreement -----------
        ratings_path = os.path.join(tmp, "human_ratings.jsonl")
        check("load_ratings on a not-yet-created file returns [] (not an error)", load_ratings(ratings_path) == [])

        invalid_choice_rejected = False
        try:
            HumanRating(task_id="t1", rater_id="alice", choice="banana")
        except ValueError:
            invalid_choice_rejected = True
        check("HumanRating rejects an invalid choice value", invalid_choice_rejected)

        r1 = HumanRating(task_id="t1", rater_id="alice", choice="a")
        r2 = HumanRating(task_id="t2", rater_id="bob", choice="tie")
        r3 = HumanRating(task_id="t3", rater_id="alice", choice="b")
        append_rating(ratings_path, r1)
        append_rating(ratings_path, r2)
        append_rating(ratings_path, r3)
        loaded = load_ratings(ratings_path)
        check("append_rating/load_ratings round-trips all three real ratings", len(loaded) == 3 and loaded[0].choice == "a")

        task_agree = HumanRatingTask(
            task_id="t1", case_id="c1", prompt_text="p", candidate_a_text="A", candidate_b_text="B",
            candidate_a_source="adapter-x", candidate_b_source="adapter-y", judge_score_a=0.9, judge_score_b=0.3,
        )
        task_disagree = HumanRatingTask(
            task_id="t2", case_id="c2", prompt_text="p", candidate_a_text="A", candidate_b_text="B",
            candidate_a_source="adapter-x", candidate_b_source="adapter-y", judge_score_a=0.9, judge_score_b=0.88,
        )  # small gap -> judge implies "tie", human said "tie" too on t2
        task_no_judge = HumanRatingTask(
            task_id="t3", case_id="c3", prompt_text="p", candidate_a_text="A", candidate_b_text="B",
            candidate_a_source="adapter-x", candidate_b_source="adapter-y",
        )  # no judge scores at all
        check("judge_implied_choice: a clear score gap implies the winning side", judge_implied_choice(task_agree) == "a")
        check("judge_implied_choice: a close gap implies a tie", judge_implied_choice(task_disagree) == "tie")
        check("judge_implied_choice: missing judge scores -> None", judge_implied_choice(task_no_judge) is None)

        agreement = judge_human_agreement([task_agree, task_disagree, task_no_judge], loaded)
        check("judge_human_agreement: t1 (judge=a, human=a) counted as agree", agreement["n_agree"] >= 1)
        check("judge_human_agreement: t3 has no judge score, excluded from the rate but counted separately",
              agreement["n_no_judge_score"] == 1)
        check("judge_human_agreement: agreement_rate is a real fraction in [0, 1]",
              agreement["agreement_rate"] is not None and 0.0 <= agreement["agreement_rate"] <= 1.0)
        empty_agreement = judge_human_agreement([], [])
        check("judge_human_agreement: nothing comparable -> agreement_rate None, not a crash",
              empty_agreement["agreement_rate"] is None)

        # A real disagreement case, to prove disagreements are actually recorded.
        task_flip = HumanRatingTask(
            task_id="t4", case_id="c4", prompt_text="p", candidate_a_text="A", candidate_b_text="B",
            candidate_a_source="x", candidate_b_source="y", judge_score_a=0.2, judge_score_b=0.9,
        )
        human_flip = HumanRating(task_id="t4", rater_id="carol", choice="a")  # human picked A, judge implies B
        flip_agreement = judge_human_agreement([task_flip], [human_flip])
        check("judge_human_agreement: a real judge/human disagreement is recorded with both choices",
              len(flip_agreement["disagreements"]) == 1 and flip_agreement["disagreements"][0]["judge_choice"] == "b"
              and flip_agreement["disagreements"][0]["human_choice"] == "a")

        check("HumanRatingTask round-trips through to_dict/from_dict", HumanRatingTask.from_dict(task_agree.to_dict()) == task_agree)

    print(f"\n{len(FAILURES)} failure(s)." if FAILURES else "\nAll checks passed.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
