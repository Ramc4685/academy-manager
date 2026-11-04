"""The departure reason vocabulary is mirrored in the frontend (issue #775).

``DepartureReasonCode`` is a closed vocabulary the admin picks from in two
dialogs (Drop and Stop all classes). There is no endpoint that serves it, so
the option list is hand-mirrored in ``frontend/lib/admin/departure-reasons.ts``
— and a hand-mirrored list drifts. The review that asked for this said it
plainly: the codes were plumbed end-to-end through the backend and no admin
could ever set one, because the dialogs never offered them. This test is the
thing that notices when the two halves stop agreeing: add a code to the
backend without adding its option here, and the dialogs quietly cannot record
it; remove one from the backend and the dialog offers a value the route will
reject with a 422.
"""

from __future__ import annotations

import pathlib
import re

from backend.v2.contexts.enrollment.domain.departure_policy import DEPARTURE_REASON_CODES

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
MIRROR = REPO_ROOT / "frontend" / "lib" / "admin" / "departure-reasons.ts"

_OPTION = re.compile(r'\{\s*value:\s*"([a-z_]+)"\s*,\s*label:\s*"')


def test_frontend_offers_every_backend_departure_reason_code() -> None:
    source = MIRROR.read_text(encoding="utf-8")
    offered = _OPTION.findall(source)
    assert offered, f"no DEPARTURE_REASON_OPTIONS entries found in {MIRROR}"
    assert tuple(offered) == tuple(DEPARTURE_REASON_CODES), (
        "frontend/lib/admin/departure-reasons.ts must offer exactly the backend "
        f"vocabulary, in order: {DEPARTURE_REASON_CODES}, got {tuple(offered)}"
    )
