"""Every direct caller of ``try_reserve_seat`` must be routed through
``SeatBroker`` — and production wiring must actually connect it.

Departures design contract §3.1/§3.2: demand for a seat is detected in
exactly one place (a failed ``try_reserve_seat``), and reclaim only happens
for callers routed through ``SeatBroker.acquire``. The previous version of
this test hardcoded the four classes known to call ``try_reserve_seat``
(``EditRosterAdd``, ``ResumeEnrollment``, ``TransferEnrollment``,
``PromoteFromWaitlist``) and only checked that count against the number of
``set_seat_broker(...)`` calls in ``main.py``. That hardcoded list is exactly
how a FIFTH seat-reserving site — ``AdminRegistrationReview.approve``, a
direct ``self._sessions.try_reserve_seat(...)`` call with no broker escape
hatch at all — went uncounted and un-reclaimed: approving a registration
into a class that was full only because held enrollments occupied it raised
"Selected session is full" instead of reclaiming the longest-held hold.

This version does not hardcode which classes matter. It walks every
non-test module under ``backend/v2`` for AST calls to ``.try_reserve_seat(``
(the one exception is ``seat_broker.py`` itself — ``SeatBroker.acquire``'s
own call to ``SessionWriter.try_reserve_seat`` is the canonical, single
demand-detection point every other caller is supposed to route through) and
requires the enclosing class of every such call to expose a
``set_seat_broker`` method — the escape hatch production wiring uses to
inject the broker. A caller with no such method structurally CANNOT ever be
brokered, which is precisely how the fifth site above hid. It then re-checks
the old invariant — every construction of a brokerable class anywhere under
``backend/v2`` (non-test) has a matching ``set_seat_broker(...)`` call in
``main.py`` — but against the classes this scan actually discovers, not a
fixed list a future site can fall outside of, and across the WHOLE tree, not
just ``composition/*.py``'s top level — a second review found a sixth site,
``CoachAddStudentToRoster``'s per-request ``EditRosterAdd`` in
``contexts/enrollment/application/use_cases/coach_roster_writes.py``, that a
composition/-only, non-recursive scan could never have seen (issue #704).
"""

from __future__ import annotations

import ast
from pathlib import Path

V2_ROOT = Path(__file__).resolve().parents[2]
COMPOSITION_ROOT = V2_ROOT / "composition"
MAIN_MODULE = V2_ROOT / "main.py"

#: SeatBroker.acquire's own delegation to SessionWriter.try_reserve_seat IS
#: the canonical demand-detection point (see the module docstring there) —
#: the one direct call that must NOT be routed back through itself.
_EXEMPT = {V2_ROOT / "contexts/enrollment/application/seat_broker.py"}


def _v2_python_files() -> list[Path]:
    files = []
    for path in V2_ROOT.rglob("*.py"):
        rel = path.relative_to(V2_ROOT)
        if "tests" in rel.parts:
            continue
        if path in _EXEMPT:
            continue
        files.append(path)
    return sorted(files)


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _enclosing_class(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.ClassDef | None:
    cur: ast.AST | None = parents.get(node)
    while cur is not None:
        if isinstance(cur, ast.ClassDef):
            return cur
        cur = parents.get(cur)
    return None


def _class_defines(cls: ast.ClassDef, method_name: str) -> bool:
    return any(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == method_name
        for n in cls.body
    )


def _find_try_reserve_seat_calls(
    path: Path,
) -> list[tuple[int, ast.ClassDef | None]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    parents = _parent_map(tree)
    hits: list[tuple[int, ast.ClassDef | None]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "try_reserve_seat"
        ):
            hits.append((node.lineno, _enclosing_class(node, parents)))
    return hits


def _count_constructions(source: str, *, class_names: frozenset[str]) -> int:
    """Count top-level ``Name(...)`` calls constructing one of ``class_names``
    (every composition module imports these use cases directly by name, never
    via a module-qualified alias — a renamed/aliased import is itself a
    visible diff worth a human look rather than a silent miss)."""
    tree = ast.parse(source)
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in class_names
    )


def _count_set_seat_broker_calls(source: str) -> int:
    tree = ast.parse(source)
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "set_seat_broker"
    )


def test_every_try_reserve_seat_caller_can_be_routed_through_the_broker() -> None:
    """Every direct ``try_reserve_seat`` call site's enclosing class must
    define ``set_seat_broker`` — the mechanism that lets production wiring
    inject the broker at all. A module-level call (no enclosing class) can
    never be brokered either and is reported the same way."""
    offenders: list[str] = []
    for path in _v2_python_files():
        for lineno, cls in _find_try_reserve_seat_calls(path):
            if cls is not None and _class_defines(cls, "set_seat_broker"):
                continue
            rel = path.relative_to(V2_ROOT)
            where = cls.name if cls is not None else "<module level>"
            offenders.append(f"{rel}:{lineno} (in {where}, no set_seat_broker escape hatch)")

    assert not offenders, (
        "Found a direct try_reserve_seat call whose class has no "
        "set_seat_broker method, so it can NEVER be routed through "
        "SeatBroker — this is exactly how AdminRegistrationReview.approve "
        "hid as an uncounted fifth reservation site. Give the class a "
        "seat_broker constructor param + set_seat_broker setter (mirror "
        "EditRosterAdd) and wire it from main.py, or fix the call itself:\n" + "\n".join(offenders)
    )


def test_every_brokerable_use_case_construction_is_wired_to_the_seat_broker() -> None:
    """Every class this scan finds CAN be brokered (previous test) must
    actually BE brokered in production: the number of times it is
    constructed anywhere under ``backend/v2`` (non-test) must equal the
    number of ``set_seat_broker(...)`` calls made against it in main.py.

    Issue #704 (second-review correction): this used to glob only the TOP
    LEVEL of ``composition/*.py`` — non-recursively, and blind to any other
    package under ``backend/v2``. That is exactly how
    ``CoachAddStudentToRoster``'s per-request construction of
    ``EditRosterAdd`` (in
    ``contexts/enrollment/application/use_cases/coach_roster_writes.py``,
    wired via ``composition/coach.py`` -> ``interfaces/coach/deps.py``) hid
    as an unbrokered, uncounted call site: a coach adding a student to a
    roster did not reclaim a held seat the way the admin path does, and
    this test could not have caught it. Scanning every non-test module the
    first test already walks (``_v2_python_files()``, recursive) closes
    that gap for this call site and any future one shaped like it.
    """
    brokerable_classes: set[str] = set()
    for path in _v2_python_files():
        for _lineno, cls in _find_try_reserve_seat_calls(path):
            if cls is not None and _class_defines(cls, "set_seat_broker"):
                brokerable_classes.add(cls.name)

    class_names = frozenset(brokerable_classes)
    construction_count = 0
    constructed_in: dict[str, int] = {}
    for path in _v2_python_files():
        source = path.read_text(encoding="utf-8")
        n = _count_constructions(source, class_names=class_names)
        if n:
            constructed_in[str(path.relative_to(V2_ROOT))] = n
        construction_count += n

    wiring_count = _count_set_seat_broker_calls(MAIN_MODULE.read_text(encoding="utf-8"))

    assert construction_count == wiring_count, (
        f"Found {construction_count} construction(s) of a brokerable seat use "
        f"case ({sorted(class_names)}) across backend/v2 (non-test) "
        f"({constructed_in}), but only {wiring_count} `set_seat_broker(...)` "
        "call(s) in main.py. A new construction of a class from that set "
        "must be followed by a `<instance>.set_seat_broker(_holds.seat_broker)` "
        "line in main.py (see the existing block around "
        "`compose_enrollment_holds`), or hold reclaim silently does not apply "
        "to that instance — exactly the #697 defect where compose_parent's "
        "event-driven PromoteFromWaitlist was never wired, and the #704 "
        "defect where CoachAddStudentToRoster's per-request EditRosterAdd "
        "was never wired."
    )
    # Sanity: this test is only meaningful while it actually finds the known
    # brokerable classes. If discovery drops to zero the assertion above
    # would trivially pass on a wiring regression that deletes SeatBroker
    # usage entirely, so pin a floor. At the time this test was widened to
    # scan all of backend/v2 there were eight: EditRosterAdd (constructed
    # twice — composition/admin.py and composition/coach.py),
    # ResumeEnrollment, TransferEnrollment, PromoteFromWaitlist (constructed
    # twice — composition/admin.py and composition/parent.py),
    # AdminRegistrationReview, and ConfirmEnrollment.
    assert construction_count >= 8, (
        "Expected at least 8 constructions of brokerable seat use cases "
        f"across backend/v2 — found {construction_count} ({constructed_in}). "
        "If use cases were consolidated, update this floor deliberately; do "
        "not lower it to make a real regression pass."
    )
