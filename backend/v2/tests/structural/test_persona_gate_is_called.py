"""Every persona/owner gate must be CALLED, not handed to Depends bare.

``require_owner`` and ``require_persona`` are factories: they return the
dependency that actually checks the caller. ``Depends(require_owner)`` makes
FastAPI inject the factory's *return value* — a function object — and no
check ever runs, so the route is silently open to anyone the router lets
through. A one-character omission removes an authorisation gate without
failing a single behavioural test, which is exactly how the leaving report
shipped ungated in #698.
"""

from __future__ import annotations

import re
from pathlib import Path

INTERFACES = Path(__file__).resolve().parents[2] / "interfaces"

#: ``Depends(require_owner)`` / ``Depends(require_persona)`` with no call.
BARE_GATE = re.compile(r"Depends\(\s*(require_owner|require_persona)\s*[,)]")


def test_no_persona_gate_is_passed_to_depends_uncalled() -> None:
    offenders: list[str] = []
    for path in sorted(INTERFACES.rglob("*.py")):
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if BARE_GATE.search(line):
                offenders.append(f"{path.relative_to(INTERFACES.parent)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "These routes hand the gate factory to Depends instead of calling it, "
        "so no authorisation check runs:\n  " + "\n  ".join(offenders)
    )
