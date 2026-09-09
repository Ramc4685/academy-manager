"""Every seat-reserving use case instance must be handed the SeatBroker.

Departures design contract §3.1/§3.2: demand for a seat is detected in
exactly one place (a failed ``try_reserve_seat``), and reclaim only happens
for callers routed through ``SeatBroker.acquire``. Four use cases call
``try_reserve_seat`` directly and each exposes a ``set_seat_broker`` setter
that production wiring must call: ``EditRosterAdd``, ``ResumeEnrollment``,
``TransferEnrollment``, ``PromoteFromWaitlist``.

``composition/admin.py`` is at its wiring line-budget cap, so the broker is
attached post-hoc from ``main.py`` (see the comment there) rather than passed
as a constructor argument. That indirection is exactly what let a second,
un-brokered ``PromoteFromWaitlist`` slip in through ``composition/parent.py``
(reached via ``install_handlers``/``event_handlers.on_enrollment_cancelled``,
not through a route) — it was never given the broker, so an ordinary
``EnrollmentCancelled`` promotion could never reclaim a hold.

This test does not try to prove *which* variable maps to *which*
``set_seat_broker`` call (composition modules are free to name locals
whatever they like) — it proves the invariant that actually matters: the
number of places a brokered use case is *constructed* across
``composition/`` equals the number of ``set_seat_broker(...)`` calls made
against production wiring. A new un-brokered construction changes the left
side without changing the right, and fails here instead of silently
dropping a family's seat.
"""

from __future__ import annotations

import ast
from pathlib import Path

V2_ROOT = Path(__file__).resolve().parents[2]
COMPOSITION_ROOT = V2_ROOT / "composition"
MAIN_MODULE = V2_ROOT / "main.py"

#: The seat-reserving use cases that must be routed through SeatBroker.
#: Exhaustive per departures design contract §2.5 item 8 / §3.1.
BROKERED_USE_CASES = frozenset(
    {
        "EditRosterAdd",
        "ResumeEnrollment",
        "TransferEnrollment",
        "PromoteFromWaitlist",
    }
)


def _count_constructions(source: str, *, class_names: frozenset[str]) -> int:
    """Count top-level calls that construct one of ``class_names``.

    Matches ``Name(...)`` calls only (every composition module imports these
    use cases directly by name, never via a module-qualified alias), so a
    renamed/aliased import would itself be a visible diff worth a human
    look rather than a silent miss.
    """
    tree = ast.parse(source)
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in class_names:
                count += 1
    return count


def _count_set_seat_broker_calls(source: str) -> int:
    tree = ast.parse(source)
    count = 0
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "set_seat_broker"
        ):
            count += 1
    return count


def test_every_brokered_use_case_construction_is_wired_to_the_seat_broker() -> None:
    construction_count = 0
    constructed_in: dict[str, int] = {}
    for path in sorted(COMPOSITION_ROOT.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        n = _count_constructions(source, class_names=BROKERED_USE_CASES)
        if n:
            constructed_in[path.name] = n
        construction_count += n

    wiring_count = _count_set_seat_broker_calls(MAIN_MODULE.read_text(encoding="utf-8"))

    assert construction_count == wiring_count, (
        f"Found {construction_count} construction(s) of a brokered seat use case "
        f"({sorted(BROKERED_USE_CASES)}) across composition/ ({constructed_in}), "
        f"but only {wiring_count} `set_seat_broker(...)` call(s) in main.py. "
        "A new construction of EditRosterAdd/ResumeEnrollment/TransferEnrollment/"
        "PromoteFromWaitlist must be followed by a `<instance>.set_seat_broker"
        "(_holds.seat_broker)` line in main.py (see the existing block around "
        "`compose_enrollment_holds`), or hold reclaim silently does not apply "
        "to that instance — exactly the #697 defect where compose_parent's "
        "event-driven PromoteFromWaitlist (used by "
        "event_handlers.on_enrollment_cancelled) was never wired."
    )
    # Sanity: this test is only meaningful while it actually finds the known
    # constructions — five, at the time this test was written (four in
    # composition/admin.py, one in composition/parent.py). If that count
    # drops to zero the assertion above would trivially pass on a wiring
    # regression that deletes SeatBroker usage entirely, so pin a floor.
    assert construction_count >= 5, (
        "Expected at least 5 constructions of brokered seat use cases across "
        "composition/ (four in admin.py, one in parent.py) — found "
        f"{construction_count}. If use cases were consolidated, update this "
        "floor deliberately; do not lower it to make a real regression pass."
    )
