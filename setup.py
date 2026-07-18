"""Builds the optional `hearthmind._native` C++ extension.

Project metadata lives in pyproject.toml; this file exists only because
setuptools still wants a setup.py to declare compiled ext_modules. The
extension is a pure speed/memory optimization for hot per-tick loops
(see cpp/, docs/DECISIONS.md "Native extension port") — every function
it exports has a pure-Python fallback, so a failed or skipped build must
never break `pip install -e .`. `BuildExtOptional` below turns any
compiler/pybind11-missing failure into a warning instead of a hard
install failure.
"""
from __future__ import annotations

import os
import sys

from setuptools import setup
from setuptools.command.build_ext import build_ext as _build_ext

# -O4 isn't a real GCC/Clang flag (both cap at -O3; -Ofast goes further
# but changes floating-point semantics in ways that could affect the
# byte-identical-vs-Python verification this project relies on, so it's
# deliberately not used) — -O3 is the actual max standard optimization
# level. -march=native/-mtune=native tune codegen for the exact CPU
# doing the build, which is safe here specifically because this
# extension is always built locally on the machine that runs it (see
# scripts/run.sh / README's "pip install -e .") rather than distributed
# as a prebuilt wheel — a binary built with -march=native on one
# machine and copied to a different CPU could crash on an unsupported
# instruction, which is why this isn't done for portable wheel builds.
# MSVC uses different flag syntax entirely, so these are skipped there.
_EXTRA_COMPILE_ARGS = [] if sys.platform == "win32" else ["-O3", "-march=native", "-mtune=native"]

try:
    from pybind11.setup_helpers import Pybind11Extension
    ext_modules = [
        Pybind11Extension(
            "hearthmind._native",
            sorted([
                "cpp/src/resource_grid.cpp",
                "cpp/src/terrain_index.cpp",
                "cpp/src/agent_position_index.cpp",
                "cpp/src/wildlife_index.cpp",
                "cpp/src/needs.cpp",
                "cpp/src/predator_kill_chance.cpp",
                "cpp/src/farm_grid.cpp",
                "cpp/src/settlement_decay.cpp",
                "cpp/src/weather.cpp",
                "cpp/src/bounded_random_walk.cpp",
                "cpp/src/wilt_farms.cpp",
                "cpp/src/flat_damage.cpp",
                "cpp/src/roll_batch.cpp",
                "cpp/src/climate_drift.cpp",
                "cpp/src/reclaim.cpp",
                "cpp/src/sim_clock.cpp",
                "cpp/src/terrain_grid.cpp",
                "cpp/src/agent_table.cpp",
                "cpp/src/emotion_decay.cpp",
                "cpp/src/relationship_step.cpp",
                "cpp/src/road_wear.cpp",
                "cpp/src/wildlife_step.cpp",
            ]),
            cxx_std=17,
            extra_compile_args=_EXTRA_COMPILE_ARGS,
        )
    ]
except ImportError:
    ext_modules = []


class BuildExtOptional(_build_ext):
    """Same as build_ext, but a compile/link failure (missing compiler,
    missing pybind11 headers, unsupported platform, ...) is downgraded to
    a warning. hearthmind runs in pure Python without this extension —
    it's a hot-path optimization, never a hard requirement.

    Also defaults `build_ext`'s stock `--parallel`/`-j` option to the
    machine's usable core count instead of its own default of 1 — g++
    otherwise compiles this extension's ~19 .cpp files one at a time on
    a plain `pip install -e .`. `-j` on the command line (or the
    `parallel_compile` package_data hook) already lets a caller override
    this; this only changes the *default* a bare install picks up.

    Uses `os.sched_getaffinity(0)` (Linux only) rather than `os.cpu_
    count()` when available: `cpu_count()` reports the *machine's*
    total logical CPUs, ignoring any cgroup quota or `taskset`/container
    CPU-affinity restriction the build process is actually confined to
    (v0.87.3 fix — a live report that the build "still isn't parallel"
    despite this method existing since v0.85.6 traced to exactly this
    class of environment: `cpu_count()` overreports, so a build
    genuinely constrained to fewer schedulable cores than `cpu_count()`
    claims could appear serial or barely-parallel in a process monitor).
    Falls back to `os.cpu_count()` on platforms without `sched_
    getaffinity` (e.g. macOS)."""

    def finalize_options(self):
        super().finalize_options()
        if self.parallel is None:
            get_affinity = getattr(os, "sched_getaffinity", None)
            self.parallel = len(get_affinity(0)) if get_affinity is not None else os.cpu_count()

    def run(self):
        try:
            super().run()
        except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
            print(
                f"WARNING: hearthmind._native native extension failed to build "
                f"({exc}). Continuing with the pure-Python fallback path — "
                f"this only costs some CPU/memory on hot loops, nothing breaks.",
                file=sys.stderr,
            )

    def build_extension(self, ext):
        try:
            super().build_extension(ext)
        except Exception as exc:  # noqa: BLE001
            print(
                f"WARNING: could not build extension {ext.name} ({exc}); "
                f"skipping, pure-Python fallback will be used.",
                file=sys.stderr,
            )


setup(ext_modules=ext_modules, cmdclass={"build_ext": BuildExtOptional})
