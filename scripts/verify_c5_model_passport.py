#!/usr/bin/env python3
"""HearthBench C5 — the model passport [APPROVED]. Real production-path
checks, no unittest, same standalone-script convention as every sibling
`verify_*.py`.

Covers both halves of C5: the `hearthbench`-side emission (`hearthbench.
reporting.passport.build_passport`/`save_passport`/`load_passport`,
built directly on A10's real `compute_score`) and the `hearthmind`-side
runtime consumption (`hearthmind.simulation.hardware_profile.seed_
machine_profile_from_passport`/`load_passport_dict`, wired at `Simulation
Engine.__init__`'s real `_passport_path_for` control point) — proving
both halves independently AND end to end through a real `Simulation
Engine` construction with a real passport file on disk, per A1.2's own
two-directional import firewall (`hearthbench` never imports `hearthmind.
simulation`/`.agents`/`.world`; `hearthmind` never imports `hearthbench`
at all — confirmed directly in this script, not assumed)."""
from __future__ import annotations

import ast
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthbench.reporting.passport import (
    PASSPORT_SCHEMA_VERSION,
    ModelPassport,
    build_passport,
    load_passport,
    produced_by_host,
    save_passport,
)
from hearthbench.reporting.score import compute_score
from hearthbench.tests.category import CategoryScoreSummary
from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import SimulationEngine, _passport_path_for
from hearthmind.simulation.hardware_profile import (
    MachineProfile,
    host_fingerprint,
    load_passport_dict,
    passport_filename_for,
    seed_machine_profile_from_passport,
)

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def _summary(n_total, mean, pass_rate, ci=None):
    return CategoryScoreSummary(
        category_id="x", n_total=n_total, n_scored=n_total, mean=mean, median=mean,
        p95=mean, stdev=0.0, confidence_interval_95=ci, n_passed=int(round(pass_rate * n_total)) if pass_rate is not None else 0,
        n_failed=n_total - (int(round(pass_rate * n_total)) if pass_rate is not None else 0),
        pass_rate=pass_rate, detail={},
    )


def main() -> int:
    # --- A1.2 firewall, checked directly ------------------------------------
    passport_src = open(os.path.join(os.path.dirname(__file__), "..", "hearthbench", "reporting", "passport.py")).read()
    tree = ast.parse(passport_src)
    banned_imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(
            ("hearthmind.simulation", "hearthmind.agents", "hearthmind.world")
        ):
            banned_imports.append(node.module)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(("hearthmind.simulation", "hearthmind.agents", "hearthmind.world")):
                    banned_imports.append(alias.name)
    check("A1.2 firewall: hearthbench/reporting/passport.py imports nothing banned", not banned_imports, str(banned_imports))

    hw_profile_src = open(os.path.join(os.path.dirname(__file__), "..", "hearthmind", "simulation", "hardware_profile.py")).read()
    hw_tree = ast.parse(hw_profile_src)
    hw_banned = []
    for node in ast.walk(hw_tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("hearthbench"):
            hw_banned.append(node.module)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("hearthbench"):
                    hw_banned.append(alias.name)
    check("A1.2 firewall: hardware_profile.py imports no real hearthbench module (a doc-comment naming the module path is fine)", not hw_banned, str(hw_banned))

    # --- hearthbench side: build_passport ------------------------------------
    good_summaries = {
        "grounding": {"leak_freedom": _summary(10, 0.95, 0.95, (0.85, 1.0)), "no_unsupported_specifics": _summary(10, 0.85, 0.85, (0.7, 1.0))},
        "structured_outputs": {"structured_output_delta": _summary(4, 0.9, 0.9)},
    }
    score = compute_score(good_summaries, latency_stats={"n_total": 10, "latency_ms": {"p50": 1500.0, "p95": 3000.0}, "ttft_ms": {"p50": 200.0}, "completion_tokens_per_sec": {"p50": 42.5}})
    describe = {"model": "fake-model-q4", "quantization": "Q4_K_M", "context": 4096, "backend": "llamacpp", "extra": {"file_hash": "abc123"}}
    passport = build_passport(score, describe, latency_stats={"n_total": 10, "latency_ms": {"p50": 1500.0, "p95": 3000.0}, "ttft_ms": {"p50": 200.0}, "completion_tokens_per_sec": {"p50": 42.5}})

    check("build_passport: model_id/quantization/file_hash carried through", passport.model_id == "fake-model-q4" and passport.quantization == "Q4_K_M" and passport.file_hash == "abc123")
    check("build_passport: hearthbench_score matches the real computed total", passport.hearthbench_score == score.total)
    check("build_passport: grounding (>=90) is a real strength", "grounding" in passport.category_strengths)
    check("build_passport: measured_throughput carries the real flat values", passport.measured_throughput["completion_tokens_per_s"] == 42.5 and passport.measured_throughput["latency_p50_ms"] == 1500.0)
    check("build_passport: world_score honestly None (A5.11 doesn't exist yet)", passport.world_score is None)
    check("build_passport: peak_rss_mb_by_concurrency honestly empty (no A7.2 yet)", passport.peak_rss_mb_by_concurrency == {})
    check("build_passport: no disqualification -> no hard_warnings", passport.hard_warnings == [])

    # --- a real disqualified (failing) run ------------------------------------
    bad_summaries = {"grounding": {"no_unsupported_specifics": _summary(10, 0.2, 0.2, (0.05, 0.35))}}
    bad_score = compute_score(bad_summaries)
    bad_passport = build_passport(bad_score, {"model": "fabricator-model"})
    check("build_passport: a real disqualification produces a real, worded hard_warning", any("fails grounding" in w for w in bad_passport.hard_warnings))
    check("build_passport: a genuinely weak category (<=50) is a real weakness", "grounding" in bad_passport.category_weaknesses)
    check("build_passport: an empty adapter_describe degrades to model_id=None, never raises", build_passport(bad_score, {}).model_id is None)

    # --- round trip -------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "sub", "passport.json")
        save_passport(passport, path)
        check("save_passport: creates its own parent directory", os.path.isfile(path))
        loaded = load_passport(path)
        check("load_passport: round-trips every real field", loaded == passport)

        with open(path) as f:
            raw = json.load(f)
        raw["schema_version"] = 999
        bad_path = os.path.join(tmp, "bad.json")
        with open(bad_path, "w") as f:
            json.dump(raw, f)
        try:
            load_passport(bad_path)
            check("load_passport: an unsupported schema_version raises", False)
        except ValueError:
            check("load_passport: an unsupported schema_version raises ValueError", True)

    check("ModelPassport.schema_version matches the real module constant", ModelPassport().schema_version == PASSPORT_SCHEMA_VERSION)

    # --- produced_by_host: a real cross-implementation parity proof ---------
    check("produced_by_host: matches hearthmind's own independent host_fingerprint() on this real host", produced_by_host() == host_fingerprint())
    check("produced_by_host: deterministic across two real calls", produced_by_host() == produced_by_host())

    # --- hearthmind side: passport_filename_for/load_passport_dict ----------
    check("passport_filename_for: a real slug, deterministic", passport_filename_for("Nemotron 3 Nano/4B (Q4_K_M)!!") == "nemotron_3_nano_4b_q4_k_m.json")
    check("passport_filename_for: an empty/None model_id degrades to unknown.json", passport_filename_for("") == "unknown.json" and passport_filename_for(None) == "unknown.json")

    with tempfile.TemporaryDirectory() as tmp:
        check("load_passport_dict: a missing file degrades to None, never raises", load_passport_dict(os.path.join(tmp, "nope.json")) is None)
        check("load_passport_dict: path=None degrades to None", load_passport_dict(None) is None)

        corrupt_path = os.path.join(tmp, "corrupt.json")
        with open(corrupt_path, "w") as f:
            f.write("{not valid json")
        check("load_passport_dict: corrupted JSON degrades to None", load_passport_dict(corrupt_path) is None)

        wrong_schema_path = os.path.join(tmp, "wrong_schema.json")
        with open(wrong_schema_path, "w") as f:
            json.dump({"schema_version": 999, "model_id": "x"}, f)
        check("load_passport_dict: an unsupported schema_version degrades to None (never raises, unlike load_passport)", load_passport_dict(wrong_schema_path) is None)

        real_path = os.path.join(tmp, "real.json")
        save_passport(passport, real_path)
        loaded_dict = load_passport_dict(real_path)
        check("load_passport_dict: a real valid passport loads as a plain dict", isinstance(loaded_dict, dict) and loaded_dict.get("model_id") == "fake-model-q4")

    # --- seed_machine_profile_from_passport ----------------------------------
    fresh_profile = MachineProfile(host_fingerprint="h1")
    seeded = seed_machine_profile_from_passport(fresh_profile, passport.to_dict())
    check("seed_machine_profile_from_passport: a genuinely fresh profile IS seeded", seeded and fresh_profile.measured_llm_throughput_tokens_per_s == 42.5)
    check("seed_machine_profile_from_passport: passport_warnings/model_id refreshed", fresh_profile.passport_model_id == "fake-model-q4" and fresh_profile.passport_warnings == [])

    live_profile = MachineProfile(host_fingerprint="h1", measured_llm_throughput_tokens_per_s=99.0)
    seeded_live = seed_machine_profile_from_passport(live_profile, passport.to_dict())
    check("seed_machine_profile_from_passport: a profile with real live data is NEVER overwritten", not seeded_live and live_profile.measured_llm_throughput_tokens_per_s == 99.0)
    check("seed_machine_profile_from_passport: warnings still refresh even when throughput isn't seedable", live_profile.passport_model_id == "fake-model-q4")

    many_sessions_profile = MachineProfile(host_fingerprint="h1", sessions_recorded=50)
    seeded_many = seed_machine_profile_from_passport(many_sessions_profile, passport.to_dict())
    check("seed_machine_profile_from_passport: a many-times-loaded but never-measured profile is STILL seedable (no session-count gate)", seeded_many and many_sessions_profile.measured_llm_throughput_tokens_per_s == 42.5)

    hard_warning_profile = MachineProfile(host_fingerprint="h2")
    seed_machine_profile_from_passport(hard_warning_profile, bad_passport.to_dict())
    check("seed_machine_profile_from_passport: a real hard warning is carried through", any("fails grounding" in w for w in hard_warning_profile.passport_warnings))

    no_throughput_profile = MachineProfile(host_fingerprint="h3")
    seeded_empty = seed_machine_profile_from_passport(no_throughput_profile, {"model_id": "m", "hard_warnings": []})
    check("seed_machine_profile_from_passport: a passport with no measured throughput seeds nothing, doesn't crash", not seeded_empty and no_throughput_profile.measured_llm_throughput_tokens_per_s is None)

    # --- MachineProfile round-trip incl. new fields + legacy backfill -------
    round_tripped = MachineProfile.from_dict(fresh_profile.to_dict())
    check("MachineProfile: passport_model_id/passport_warnings survive a real round-trip", round_tripped.passport_model_id == fresh_profile.passport_model_id and round_tripped.passport_warnings == fresh_profile.passport_warnings)
    legacy_dict = {"host_fingerprint": "h4", "sessions_recorded": 3}  # no passport_* keys at all, a pre-C5 profile
    legacy_loaded = MachineProfile.from_dict(legacy_dict)
    check("MachineProfile: a legacy (pre-C5) persisted dict backfills passport_model_id=None/passport_warnings=[]", legacy_loaded.passport_model_id is None and legacy_loaded.passport_warnings == [])

    # --- real end-to-end proof through SimulationEngine.__init__ ------------
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "world.db")
        model_id = "verify-c5-model"
        machine_profile_path = os.path.join(tmp, "machine_profile.json")
        passport_path = _passport_path_for(machine_profile_path, model_id)
        check("_passport_path_for: a real, deterministic passports/ sibling path", os.path.dirname(passport_path).endswith("passports") and os.path.basename(passport_path) == passport_filename_for(model_id))
        check("_passport_path_for: :memory:-equivalent (None machine_profile_path) stays honestly None", _passport_path_for(None, model_id) is None)

        e2e_latency_stats = {"n_total": 6, "completion_tokens_per_sec": {"p50": 17.25}}
        e2e_score = compute_score({"grounding": {"leak_freedom": _summary(6, 0.9, 0.9)}}, latency_stats=e2e_latency_stats)
        e2e_passport = build_passport(e2e_score, {"model": model_id}, latency_stats=e2e_latency_stats)
        save_passport(e2e_passport, passport_path)

        conn = connect(db_path)
        cfg = Config(db_path=db_path, llm_enabled=False, seed=1, initial_population=3, width=16, height=16, llm_model=model_id)
        engine = SimulationEngine.load_or_create(conn, cfg)
        check("SimulationEngine.__init__: a real passport on disk seeds the fresh machine profile's throughput", engine._machine_profile.measured_llm_throughput_tokens_per_s == 17.25)
        check("SimulationEngine.__init__: passport_model_id/warnings surfaced on the real profile", engine._machine_profile.passport_model_id == model_id)

        report = engine.full_diagnostics()
        mp_diag = report["machine_profile"]
        check("full_diagnostics(): machine_profile.passport_model_id present", mp_diag["passport_model_id"] == model_id)
        check("full_diagnostics(): machine_profile.passport_warnings present (empty, no disqualification)", mp_diag["passport_warnings"] == [])
        conn.close()

        # A second engine against a DIFFERENT model id (no matching passport) never seeds, never crashes.
        db_path2 = os.path.join(tmp, "world2.db")
        conn2 = connect(db_path2)
        cfg2 = Config(db_path=db_path2, llm_enabled=False, seed=1, initial_population=3, width=16, height=16, llm_model="a-totally-different-model")
        engine2 = SimulationEngine.load_or_create(conn2, cfg2)
        check("SimulationEngine.__init__: no matching passport for a different model_id -> no crash, no seeding", engine2._machine_profile.measured_llm_throughput_tokens_per_s is None and engine2._machine_profile.passport_model_id is None)
        conn2.close()

        # A :memory: db never touches disk for the passport either.
        conn3 = connect(":memory:")
        cfg3 = Config(db_path=":memory:", llm_enabled=False, seed=1, initial_population=3, width=16, height=16, llm_model=model_id)
        engine3 = SimulationEngine.load_or_create(conn3, cfg3)
        check("SimulationEngine.__init__: :memory: db never crashes on passport lookup", engine3._passport_path is None)
        conn3.close()

    print(f"\n{len(FAILURES)} failure(s)." if FAILURES else "\nAll checks passed.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
