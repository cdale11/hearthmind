"""B7 -- Hardware model (docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part
B, Hard Rule 7). Standalone infrastructure, same "never big-bang"
discipline as every other Tier 5 Runtime module (task_graph.py,
scheduler.py, reactivity.py, dormancy.py, profiling.py, tuning.py) --
nothing here is imported by `simulation/engine.py` or wired into the
live tick loop yet.

B7.1 `HostProbe.sample()`: a point-in-time hardware/load snapshot.
B7.2 `MachineProfile`: a persistent, host-fingerprinted profile
     refined across sessions (measured LLM throughput, optimal worker
     count/batch size, storage characteristics) -- versioned JSON,
     the same "ship as data" discipline the ML weight blobs already
     use.
B7.3 `select_strategy`: a deterministic mapping from a profile to a
     scheduling strategy (parallelism, cache sizes, dormancy
     aggressiveness, LLM concurrency hints) -- generic policy read
     from profile data, never a hardware-specific branch baked into
     gameplay code, per the item's own text.
B7.4 `GoodCitizenPolicy`: back off before the OS starts swapping,
     yield under external load, respond to thermal state --
     configurable aggressiveness (a dedicated box may reasonably want
     less caution than a shared laptop).
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import tempfile
import time
from dataclasses import dataclass
from enum import Enum

PROFILE_SCHEMA_VERSION = 1
_STORAGE_BENCH_SIZE_BYTES = 4 * 1024 * 1024  # 4 MiB -- cheap, not disruptive


@dataclass
class HostProbe:
    """B7.1 -- a single point-in-time snapshot. Every field is
    best-effort: unavailable on this platform/kernel means `None`,
    never an exception (a probe must never be able to crash the
    process that calls it)."""

    logical_cores: int | None
    usable_cores: int | None  # os.sched_getaffinity, may differ under cgroups/taskset
    mem_total_mb: float | None
    mem_available_mb: float | None
    swap_used_mb: float | None
    swap_total_mb: float | None
    load_avg_1m: float | None
    storage_write_mb_s: float | None
    storage_read_mb_s: float | None
    gpu_present: bool
    thermal_state: str | None  # "nominal"/"throttled"/None if unreadable
    timestamp: float

    @classmethod
    def sample(cls, run_storage_bench: bool = True) -> "HostProbe":
        write_mb_s = read_mb_s = None
        if run_storage_bench:
            write_mb_s, read_mb_s = _storage_microbenchmark()
        mem = _meminfo()
        return cls(
            logical_cores=os.cpu_count(),
            usable_cores=_usable_cores(),
            mem_total_mb=mem.get("mem_total_mb"),
            mem_available_mb=mem.get("mem_available_mb"),
            swap_used_mb=mem.get("swap_used_mb"),
            swap_total_mb=mem.get("swap_total_mb"),
            load_avg_1m=_load_avg_1m(),
            storage_write_mb_s=write_mb_s,
            storage_read_mb_s=read_mb_s,
            gpu_present=_gpu_present(),
            thermal_state=_thermal_state(),
            timestamp=time.time(),
        )

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _usable_cores() -> int | None:
    getter = getattr(os, "sched_getaffinity", None)
    if getter is None:
        return None
    try:
        return len(getter(0))
    except OSError:
        return None


def _meminfo() -> dict:
    if not os.path.isdir("/proc"):
        return {}
    try:
        raw = {}
        with open("/proc/meminfo") as handle:
            for line in handle:
                key, _, value = line.partition(":")
                if key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
                    raw[key] = round(int(value.split()[0]) / 1024, 1)
        swap_used = None
        if "SwapTotal" in raw and "SwapFree" in raw:
            swap_used = round(raw["SwapTotal"] - raw["SwapFree"], 1)
        return {
            "mem_total_mb": raw.get("MemTotal"),
            "mem_available_mb": raw.get("MemAvailable"),
            "swap_used_mb": swap_used,
            "swap_total_mb": raw.get("SwapTotal"),
        }
    except OSError:
        return {}


def _load_avg_1m() -> float | None:
    getter = getattr(os, "getloadavg", None)
    if getter is None:
        return None
    try:
        return getter()[0]
    except OSError:
        return None


def _gpu_present() -> bool:
    # Best-effort, zero new dependency: a real nvidia driver exposes
    # this path on Linux. Anything more (AMD/Metal detection, actual
    # utilization) needs a real query tool, out of scope for a
    # zero-dependency probe -- absence here means "not detected," not
    # "definitely no GPU."
    return os.path.exists("/proc/driver/nvidia")


def _thermal_state() -> str | None:
    base = "/sys/class/thermal"
    if not os.path.isdir(base):
        return None
    try:
        temps = []
        for name in os.listdir(base):
            temp_path = os.path.join(base, name, "temp")
            if os.path.isfile(temp_path):
                with open(temp_path) as handle:
                    # millidegrees C, per the kernel thermal sysfs convention.
                    temps.append(int(handle.read().strip()) / 1000.0)
        if not temps:
            return None
        return "throttled" if max(temps) >= 90.0 else "nominal"
    except (OSError, ValueError):
        return None


def _storage_microbenchmark() -> tuple:
    try:
        data = os.urandom(_STORAGE_BENCH_SIZE_BYTES)
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
            start = time.perf_counter()
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
            write_elapsed = time.perf_counter() - start
        start = time.perf_counter()
        with open(path, "rb") as f:
            f.read()
        read_elapsed = time.perf_counter() - start
        os.unlink(path)
        mb = _STORAGE_BENCH_SIZE_BYTES / (1024 * 1024)
        write_mb_s = mb / write_elapsed if write_elapsed > 0 else None
        read_mb_s = mb / read_elapsed if read_elapsed > 0 else None
        return write_mb_s, read_mb_s
    except OSError:
        return None, None


def host_fingerprint() -> str:
    """A stable identifier for the current machine -- stable across
    runs on the same host, distinct across different hosts. Not
    cryptographic; just a key for `MachineProfile` persistence."""
    raw = f"{platform.node()}|{os.cpu_count()}|{platform.machine()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class MachineProfile:
    """B7.2 -- a persistent profile keyed by `host_fingerprint()`,
    refined session over session. Every measured field is an
    exponential moving average (`PROFILE_EMA_ALPHA`) rather than a
    single overwrite, so one noisy session can't wildly swing the
    profile -- "gradually evolves," per the item's own text, not
    "resets each time."""

    host_fingerprint: str
    sessions_recorded: int = 0
    measured_llm_throughput_tokens_per_s: float | None = None
    optimal_worker_count: int | None = None
    optimal_batch_size: int | None = None
    storage_write_mb_s: float | None = None
    storage_read_mb_s: float | None = None

    EMA_ALPHA = 0.3

    def record_llm_throughput(self, tokens_per_s: float) -> None:
        self.measured_llm_throughput_tokens_per_s = _ema(
            self.measured_llm_throughput_tokens_per_s, tokens_per_s, self.EMA_ALPHA
        )

    def record_storage_benchmark(self, probe: HostProbe) -> None:
        if probe.storage_write_mb_s is not None:
            self.storage_write_mb_s = _ema(self.storage_write_mb_s, probe.storage_write_mb_s, self.EMA_ALPHA)
        if probe.storage_read_mb_s is not None:
            self.storage_read_mb_s = _ema(self.storage_read_mb_s, probe.storage_read_mb_s, self.EMA_ALPHA)

    def record_session(self) -> None:
        self.sessions_recorded += 1

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["schema_version"] = PROFILE_SCHEMA_VERSION
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "MachineProfile":
        return cls(
            host_fingerprint=d["host_fingerprint"],
            sessions_recorded=d.get("sessions_recorded", 0),
            measured_llm_throughput_tokens_per_s=d.get("measured_llm_throughput_tokens_per_s"),
            optimal_worker_count=d.get("optimal_worker_count"),
            optimal_batch_size=d.get("optimal_batch_size"),
            storage_write_mb_s=d.get("storage_write_mb_s"),
            storage_read_mb_s=d.get("storage_read_mb_s"),
        )

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f)

    @classmethod
    def load(cls, path: str) -> "MachineProfile":
        with open(path) as f:
            d = json.load(f)
        if d.get("schema_version") != PROFILE_SCHEMA_VERSION:
            raise ValueError(f"unsupported machine profile schema_version={d.get('schema_version')!r}")
        return cls.from_dict(d)

    @classmethod
    def load_or_create(cls, path: str) -> "MachineProfile":
        if os.path.isfile(path):
            return cls.load(path)
        return cls(host_fingerprint=host_fingerprint())


def _ema(current: float | None, new: float, alpha: float) -> float:
    if current is None:
        return new
    return alpha * new + (1.0 - alpha) * current


@dataclass
class Strategy:
    """B7.3's output: a generic scheduling policy read from a profile,
    never a hardware-specific branch in gameplay code."""

    llm_max_concurrent_hint: int
    worker_count_hint: int
    cache_size_hint: str  # "small" / "normal" / "large"
    dormancy_aggressiveness: str  # "low" / "normal" / "high"


def select_strategy(probe: HostProbe, profile: MachineProfile | None = None) -> Strategy:
    """B7.3 -- deterministic rules over hardware readings. `profile`
    (if given) refines the hint using this specific machine's own
    measured history rather than only the instantaneous probe."""
    cores = probe.usable_cores or probe.logical_cores or 1
    mem_total = probe.mem_total_mb or 0.0
    mem_available = probe.mem_available_mb if probe.mem_available_mb is not None else mem_total

    if cores >= 8 and mem_total >= 8192:
        llm_concurrent = 3
        workers = min(cores, 8)
        cache = "large"
    elif cores >= 4 and mem_total >= 4096:
        llm_concurrent = 2
        workers = min(cores, 4)
        cache = "normal"
    else:
        llm_concurrent = 1
        workers = max(1, min(cores, 2))
        cache = "small"

    mem_pressure = mem_available < (mem_total * 0.2) if mem_total else False
    swap_pressure = bool(probe.swap_used_mb and probe.swap_used_mb > 0)
    throttled = probe.thermal_state == "throttled"

    if mem_pressure or swap_pressure or throttled:
        llm_concurrent = max(1, llm_concurrent - 1)
        cache = "small"
        dormancy = "high"
    elif probe.load_avg_1m is not None and cores and probe.load_avg_1m > cores * 1.5:
        dormancy = "high"
    else:
        dormancy = "normal" if not (cores >= 8 and mem_total >= 8192) else "low"

    if profile is not None and profile.optimal_worker_count:
        workers = profile.optimal_worker_count

    return Strategy(
        llm_max_concurrent_hint=llm_concurrent,
        worker_count_hint=workers,
        cache_size_hint=cache,
        dormancy_aggressiveness=dormancy,
    )


class Aggressiveness(str, Enum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


_BACKOFF_MEM_AVAILABLE_FRACTION = {
    Aggressiveness.CONSERVATIVE: 0.30,
    Aggressiveness.BALANCED: 0.15,
    Aggressiveness.AGGRESSIVE: 0.05,
}
_BACKOFF_LOAD_MULTIPLIER = {
    Aggressiveness.CONSERVATIVE: 1.2,
    Aggressiveness.BALANCED: 1.6,
    Aggressiveness.AGGRESSIVE: 2.5,
}


@dataclass
class GoodCitizenPolicy:
    """B7.4 -- "respect system memory pressure (back off before the OS
    swaps), yield under external CPU load... coexist cleanly," with a
    configurable aggressiveness so a dedicated box can reasonably run
    hotter than a shared laptop."""

    aggressiveness: Aggressiveness = Aggressiveness.BALANCED

    def should_back_off(self, probe: HostProbe) -> bool:
        if probe.mem_total_mb and probe.mem_available_mb is not None:
            fraction = probe.mem_available_mb / probe.mem_total_mb
            if fraction < _BACKOFF_MEM_AVAILABLE_FRACTION[self.aggressiveness]:
                return True
        if probe.swap_used_mb and probe.swap_used_mb > 0 and self.aggressiveness == Aggressiveness.CONSERVATIVE:
            return True
        cores = probe.usable_cores or probe.logical_cores
        if probe.load_avg_1m is not None and cores:
            if probe.load_avg_1m > cores * _BACKOFF_LOAD_MULTIPLIER[self.aggressiveness]:
                return True
        if probe.thermal_state == "throttled":
            return True
        return False
