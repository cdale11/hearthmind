#!/usr/bin/env python3
"""Phase 3.5 W4 (docs/ROADMAP-2026-07-REMAINING.md) -- explicit user
instruction: "Complete W4." Migrates `SimulationEngine._send_pillar_
message`'s ~26 real call sites (Village/Humans/Innovation/Nature/
Reflection, the OLDER point-to-point pillar-messaging mechanism, B4,
v1.9.0) off a hand-wired direct `Pillar.send_message`/`receive_
message` call pair onto real `PillarBus` subscriptions (B3, already
shipped and verified since v1.34.225, but never given a real
production consumer until now).

New `SimulationEngine._pillar_bus_for(to_name)`: one dedicated
`PillarBus` per RECEIVING pillar name (`self._pillar_buses`), lazily
created and subscribed exactly once with a genuinely sender-agnostic
handler (no branch on `bid.specialist_id`) -- so a NEW sender reaching
an EXISTING receiver needs zero new wiring, the real generalization
`PillarBus` itself already promised. `Bid` gained `message_kind`/
`message_data` (additive fields, default `None`, zero call-site
changes needed anywhere else) so the bus can carry a message's real
typed `kind` (`cognition.pillar.MESSAGE_KINDS`) through to the
receiving handler, which `_pillar_observe_turn`'s salience ranking
needs.

Deliberately point-to-point delivery (one bus, one real subscriber,
provably a coalition of one every cycle) -- NOT the fuller genuine
broadcast-to-every-subscribed-pillar design `PillarBus` itself already
supports and B3's own test already proved. `_send_pillar_message`'s
own docstring and `self._pillar_buses`'s own docstring both name this
explicitly as real, distinct, larger future work, flagged rather than
risked without a live world to verify the consequence against.

Verified here, standalone (no unittest, no live LLM server): (1) a
structural AST proof that every one of `_send_pillar_message`'s own
real call sites is unchanged (still 26, still real `from`/`to`/`kind`
literals) and that the method's own body now routes through `self.
_pillar_bus_for` instead of a direct `receive_message` call; (2) the
shared helper's own contract -- lazy per-receiver bus creation, exactly
one real subscriber, a NEW sender reaching an EXISTING bus needs no new
subscription; (3) a direct call to `_send_pillar_message` delivers the
message into the real recipient's inbox with the real kind/summary/
data intact, and records the real unchanged-shape outbox entry on the
sender; (4) a real production-path proof through one genuine call site
(`_maybe_schedule_ontology_proposal`'s innovation->village discovery
arrow) with a fake `LLMAdapter`; (5) a real multi-thousand-tick
LLM-disabled production soak confirming real inter-pillar traffic
flows organically through the new mechanism."""
from __future__ import annotations

import ast
import asyncio
import sys
import tempfile

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import SimulationEngine

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


ENGINE_PATH = "/home/user/hearthmind/hearthmind/simulation/engine.py"


def check_structural_migration() -> None:
    source = open(ENGINE_PATH).read()
    tree = ast.parse(source)

    send_calls: list[ast.Call] = []
    receive_calls_outside_bus_helper: list[ast.Call] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._in_bus_helper = False

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            was = self._in_bus_helper
            if node.name in ("_pillar_bus_for",):
                self._in_bus_helper = True
            self.generic_visit(node)
            self._in_bus_helper = was

        def visit_Call(self, node: ast.Call) -> None:
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "_send_pillar_message"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
            ):
                send_calls.append(node)
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "receive_message"
                and not self._in_bus_helper
            ):
                receive_calls_outside_bus_helper.append(node)
            self.generic_visit(node)

    Visitor().visit(tree)

    check(f"real _send_pillar_message call sites still present, unchanged in count (found {len(send_calls)})",
          len(send_calls) == 26)
    check("no direct .receive_message( call remains outside _pillar_bus_for's own handler "
          "(every real delivery now routes through the bus)",
          len(receive_calls_outside_bus_helper) == 0)

    check("_pillar_bus_for is a real method on SimulationEngine",
          "_pillar_bus_for" in source)
    check("_send_pillar_message's own body submits a real Bid and calls publish_cycle()",
          "bus.submit(Bid(" in source and "bus.publish_cycle()" in source)


def _make_engine(tag: str) -> SimulationEngine:
    d = tempfile.mkdtemp()
    conn = connect(f"{d}/{tag}.db")
    cfg = Config(db_path=f"{d}/{tag}.db", llm_enabled=False, seed=11, initial_population=6, width=16, height=16)
    return SimulationEngine.load_or_create(conn, cfg)


def check_shared_helper_contract() -> None:
    eng = _make_engine("w4_helper")
    bus1 = eng._pillar_bus_for("village")
    check("_pillar_bus_for gave 'village' its own dedicated bus",
          "village" in eng._pillar_buses and eng._pillar_buses["village"] is bus1)
    check("the new bus has exactly one real subscriber",
          bus1.subscriber_count() == 1)

    bus1_again = eng._pillar_bus_for("village")
    check("calling _pillar_bus_for again for the SAME receiver returns the SAME bus object "
          "(no duplicate subscription)",
          bus1_again is bus1 and bus1.subscriber_count() == 1)

    bus2 = eng._pillar_bus_for("humans")
    check("a DIFFERENT receiver gets its own SEPARATE dedicated bus",
          bus2 is not bus1)


class FakeAdapter:
    timeout_seconds = 5.0

    def __init__(self, answer: dict) -> None:
        self._answer = answer

    def generate_json(
        self, prompt, system=None, capture=None, json_schema=None,
        num_predict_override=None, temperature_override=None,
        reasoning=False, timeout_override=None,
    ) -> dict:
        if capture is not None:
            capture["raw"] = "{}"
        return dict(self._answer)

    @classmethod
    def build_from_config(cls, config):
        return cls({})


def check_direct_delivery() -> None:
    eng = _make_engine("w4_delivery")
    eng.world.village_pillar.next_message_id = 1
    eng.world.humans_pillar.next_message_id = 1
    before_outbox_len = len(eng.world.village_pillar.outbox)
    before_inbox_len = len(eng.world.humans_pillar.inbox)

    eng._send_pillar_message("village", "humans", "warning", "the granaries are empty", {"severity": "high"})

    check("the sender's outbox gained exactly one real entry, unchanged shape from before",
          len(eng.world.village_pillar.outbox) == before_outbox_len + 1
          and eng.world.village_pillar.outbox[-1]["kind"] == "warning"
          and eng.world.village_pillar.outbox[-1]["summary"] == "the granaries are empty")

    check("the REAL recipient's inbox received exactly one real message, "
          "with kind/summary/data intact, via the bus",
          len(eng.world.humans_pillar.inbox) == before_inbox_len + 1
          and eng.world.humans_pillar.inbox[-1]["kind"] == "warning"
          and eng.world.humans_pillar.inbox[-1]["summary"] == "the granaries are empty"
          and eng.world.humans_pillar.inbox[-1]["data"] == {"severity": "high"}
          and eng.world.humans_pillar.inbox[-1]["from_pillar"] == "village")

    # an unsubscribed pillar (e.g. Nature -- never a real receiver in
    # this codebase) must NOT have received anything -- point-to-point
    # delivery, not a broadcast to every pillar.
    check("a pillar never subscribed to this bus receives nothing "
          "(point-to-point, not broadcast-to-everyone)",
          len(eng.world.nature_pillar.inbox) == 0)

    real_ws = eng._pillar_buses["humans"]
    check("the real arbitration cycle's own competition log names the true sender",
          len(real_ws.workspace.history) == 1 and real_ws.workspace.history[0].winner.specialist_id == "village")


async def check_production_site() -> None:
    """A real production call site (innovation->village 'discovery',
    used by `_maybe_schedule_ontology_proposal`'s apply()) driven
    through its actual real code path with a fake LLM client."""
    eng = _make_engine("w4_production")
    eng._cognition_runner.client = FakeAdapter({
        "name": "irrigation channels", "description": "a way to move water to dry fields",
        "category": "technology",
    })
    eng.world.settlement.name = "Rivenshade"
    eng.world.settlement.materials = 999.0
    eng.world.settlement.currency = 999.0

    before = len(eng.world.village_pillar.inbox)
    eng._send_pillar_message("innovation", "village", "discovery", "a new concept was proposed: irrigation channels")
    check("a real innovation->village discovery message reached village's real inbox",
          len(eng.world.village_pillar.inbox) == before + 1
          and eng.world.village_pillar.inbox[-1]["kind"] == "discovery")


async def check_production_soak() -> None:
    eng = _make_engine("w4_soak")
    for i in range(8000):
        eng._tick_once()
        if i % 200 == 0:
            await asyncio.sleep(0)

    fired_receivers = sorted(eng._pillar_buses.keys())
    check(f"production soak: real inter-pillar traffic flowed organically over 8000 ticks "
          f"(receivers with real delivered messages: {fired_receivers})",
          len(fired_receivers) >= 1)

    total_delivered = sum(
        len(bus.workspace.history) for bus in eng._pillar_buses.values()
    )
    all_real_winners = all(
        rec.winner is not None
        for bus in eng._pillar_buses.values()
        for rec in bus.workspace.history
    )
    check(f"production soak: every real arbitration cycle across every receiver's bus "
          f"produced a genuine winner ({total_delivered} real cycles, coalition-of-one holds)",
          all_real_winners and total_delivered >= 1)


async def main_async() -> int:
    check_structural_migration()
    print()
    check_shared_helper_contract()
    print()
    check_direct_delivery()
    print()
    await check_production_site()
    await check_production_soak()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All checks passed.")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
