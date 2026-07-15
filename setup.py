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
    it's a hot-path optimization, never a hard requirement."""

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
