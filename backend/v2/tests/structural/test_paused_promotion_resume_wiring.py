"""A paused student promoted off the waitlist must resume, never status-flip.

Issue #782. ``PromoteFromWaitlist`` takes an optional ``resume=`` port (the
``ResumeEnrollment`` use case). When it is wired, a paused head-of-queue row
goes back through the ONE resume path: seat reserve, waitlist cleanup, the
lifecycle event, the billing deferral close, autopay reactivation, the
``billing_sync`` "resumed" call and the family's email. When it is NOT wired
the use case falls back to a bare ``update_status(..., "active")`` — kept only
so old callers keep working — and every one of those follow-ups is skipped.

``composition/admin.py`` wired it. ``composition/parent.py`` did not, and the
outbox handler that promotes off a seat release runs the *parent* instance
(``composition/event_handlers.py`` reads ``HandlerDeps.promote_from_waitlist``).
So the promotion that actually happens in production — a seat freed by a drop —
silently un-paused the child in the roster while autopay stayed paused, the
pause deferral stayed open and monthly invoicing kept skipping them. Nothing
errored; the money just stopped.

A behavioural test cannot catch this: both compositions build a correct object,
one of them simply omits an optional argument. The defect only exists at the
construction site, so that is what is checked here — the same shape as
``test_seat_broker_wiring.py``, which pins the sibling "optional port nobody
wired" failure for ``SeatBroker``.
"""

from __future__ import annotations

import ast
from pathlib import Path

V2_ROOT = Path(__file__).resolve().parents[2]

#: The use case whose ``resume=`` port is load-bearing.
_TARGET = "PromoteFromWaitlist"


def _v2_python_files() -> list[Path]:
    return sorted(
        path for path in V2_ROOT.rglob("*.py") if "tests" not in path.relative_to(V2_ROOT).parts
    )


def _constructions(tree: ast.AST) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else func.attr
            if isinstance(func, ast.Attribute)
            else None
        )
        if name == _TARGET:
            calls.append(node)
    return calls


def test_every_promote_from_waitlist_construction_wires_resume() -> None:
    offenders: list[str] = []
    seen = 0
    for path in _v2_python_files():
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover - defensive
            continue
        for call in _constructions(tree):
            seen += 1
            if not any(kw.arg == "resume" for kw in call.keywords):
                offenders.append(f"{path.relative_to(V2_ROOT)}:{call.lineno}")

    assert seen, f"no {_TARGET}(...) construction found — has it been renamed?"
    assert not offenders, (
        f"{_TARGET} built without `resume=` at: {', '.join(offenders)}. "
        "A paused student at the head of the waitlist would be flipped to "
        "active by a bare update_status, skipping the billing deferral close, "
        "autopay reactivation and the billing_sync 'resumed' call (issue #782). "
        "Pass resume=ResumeEnrollment(...) the way composition/admin.py does."
    )
