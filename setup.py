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

try:
    from pybind11.setup_helpers import Pybind11Extension
    ext_modules = [
        Pybind11Extension(
            "hearthmind._native",
            sorted(["cpp/src/resource_grid.cpp", "cpp/src/terrain_index.cpp"]),
            cxx_std=17,
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
