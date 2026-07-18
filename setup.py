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

def _build_jobs() -> int:
    """Usable core count for this build process — `os.sched_getaffinity(0)`
    (Linux only) rather than `os.cpu_count()`: `cpu_count()` reports the
    *machine's* total logical CPUs, ignoring any cgroup quota or
    `taskset`/container CPU-affinity restriction the build is actually
    confined to (v0.87.3 finding). Falls back to `os.cpu_count()` on
    platforms without `sched_getaffinity` (e.g. macOS)."""
    get_affinity = getattr(os, "sched_getaffinity", None)
    return len(get_affinity(0)) if get_affinity is not None else (os.cpu_count() or 1)


try:
    from pybind11.setup_helpers import ParallelCompile, Pybind11Extension

    # v0.87.8 root-cause fix: `build_ext`'s own `--parallel`/`self.parallel`
    # (what `BuildExtOptional.finalize_options` below sets) only
    # parallelizes ACROSS multiple `Extension` objects — internally,
    # `_build_extensions_parallel` submits one `ThreadPoolExecutor` task
    # PER EXTENSION, then each task calls the stock `CCompiler.compile()`,
    # which loops over that extension's own source list strictly
    # serially (verified directly against setuptools._distutils'
    # `CCompiler.compile()`/`build_ext._build_extensions_parallel()`
    # source — no source-file-level dispatch exists in either). This
    # project declares exactly ONE `Pybind11Extension` (with ~21 .cpp
    # files), so `self.parallel` — however many workers it's set to —
    # only ever gets ONE task to hand out; every prior "fix" here
    # (v0.85.6's initial `--parallel` default, v0.87.3's cgroup-aware
    # core-count correction) tuned a lever that could never have had any
    # effect on THIS single-extension build, which is why the build
    # reportedly still isn't parallel. `ParallelCompile` (pybind11's own
    # documented fix for exactly this shape of project) monkey-patches
    # `CCompiler.compile()` itself to thread-pool over the individual
    # source files of whichever extension is currently compiling — the
    # only place per-file parallelism can actually be introduced.
    # `HEARTHMIND_BUILD_JOBS` overrides the auto-detected (cgroup-aware)
    # worker count if set; `max=_build_jobs()` caps the "0 = auto"
    # default (which otherwise uses `multiprocessing.cpu_count()`,
    # subject to the exact same overreporting `_build_jobs()` exists to
    # avoid) at this same affinity-aware ceiling either way.
    ParallelCompile("HEARTHMIND_BUILD_JOBS", default=0, max=_build_jobs()).install()

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
    machine's usable core count (`_build_jobs()`) instead of its own
    default of 1. **This alone does not parallelize this project's
    build** — see the `ParallelCompile(...).install()` call above for
    why (it only parallelizes across multiple `Extension` objects, and
    this project has exactly one) and for the actual fix. Kept anyway
    for correctness/forward-compatibility: if this extension is ever
    split into multiple `Extension` objects, or a future pybind11
    version changes `ParallelCompile`'s behavior, `self.parallel` being
    set correctly here means build_ext's own extension-level
    parallelism still does the right thing without further changes."""

    def finalize_options(self):
        super().finalize_options()
        if self.parallel is None:
            self.parallel = _build_jobs()

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
