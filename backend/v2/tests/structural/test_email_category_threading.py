"""Every non-transactional send loop must pass an explicit ``category=`` (#556).

``EmailSendPort.send`` defaults ``category`` to ``TRANSACTIONAL`` so that the
many one-off transactional adapters did not all need editing. The cost of that
default is that a *bulk* send loop which forgets the kwarg is silently gated as
transactional — which is exactly what shipped first: ``SendCampaign`` and both
daily digests called ``sender.send(...)`` with no category, so a ``complaint``
suppression (which by design blocks only DIGEST and CAMPAIGN) blocked nothing at
all in production while the behavioural tests stayed green.

Behavioural tests cover the four loops that exist today. This AST tripwire
covers the fifth one somebody adds next year: any use case whose module name
says it sends a digest or a campaign must name its category explicitly.

#612 widened the sweep to the composition-layer notification adapters. Their
send loops are not in ``use_cases/`` (they need enrollment *and* communications
at once, which only ``composition/`` may do), so the original glob could not
see them — and a roster alert that lost its ``category=`` would silently become
TRANSACTIONAL, meaning every unsubscribe and every complaint suppression would
stop blocking it. That is precisely the bug this file was written for.
"""

from __future__ import annotations

import ast
from pathlib import Path

V2_ROOT = Path(__file__).resolve().parents[2]
USE_CASES_ROOT = V2_ROOT / "contexts" / "communications" / "application" / "use_cases"
COMPOSITION_ROOT = V2_ROOT / "composition"

#: Modules whose sends are bulk/marketing and therefore suppressible.
BULK_MODULE_MARKERS = ("digest", "campaign")

#: Composition adapters that send on a recipient's behalf and must classify
#: every message (#612). Listed by name rather than globbed: composition is
#: full of modules that never send, and a glob would either miss these or
#: sweep in wiring that has no send loop at all.
COMPOSITION_SEND_MODULES = (
    "roster_notifications.py",
    "enrollment_welcome_email.py",
)


def _bulk_modules() -> list[Path]:
    use_cases = [
        path
        for path in USE_CASES_ROOT.rglob("*.py")
        if path.name.startswith("send_")
        and any(marker in path.name for marker in BULK_MODULE_MARKERS)
    ]
    adapters = [COMPOSITION_ROOT / name for name in COMPOSITION_SEND_MODULES]
    for path in adapters:
        assert path.exists(), f"{path.name} moved; update COMPOSITION_SEND_MODULES"
    return sorted(use_cases + adapters)


def _sends_without_category(path: Path) -> list[int]:
    """Line numbers of ``*.send(...)`` calls in ``path`` lacking ``category=``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "send"):
            continue
        if not any(kw.arg == "category" for kw in node.keywords):
            offenders.append(node.lineno)
    return offenders


def test_bulk_send_loops_name_their_category() -> None:
    modules = _bulk_modules()
    assert modules, "expected to find digest/campaign send use cases"

    offenders = {path.name: lines for path in modules if (lines := _sends_without_category(path))}

    assert not offenders, (
        "These send loops call sender.send() without an "
        f"explicit category=: {offenders}. They would be gated as "
        "TRANSACTIONAL, so a complaint/unsubscribe suppression would never "
        "block them. Pass category=EmailCategory.DIGEST or "
        "EmailCategory.CAMPAIGN / EmailCategory.NOTIFICATION (see "
        "contexts/communications/domain/email_category.py)."
    )
