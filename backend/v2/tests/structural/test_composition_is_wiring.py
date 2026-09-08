"""Tripwire keeping the composition root from re-growing business logic.

Import-linter can only constrain import *direction* (Rule 7,
``composition-is-outermost`` in ``backend/pyproject.toml``), not "no business
logic in this module". MT1 drained ~2,500 lines of money math, report
pipelines, payout read models and email templating out of
``composition/admin.py``; this ratchet is what stops them coming back.

If a change trips the line budget, the fix is to put the new logic in the
owning context, not to raise the number. Lowering the number as more wiring
gets extracted is always fine.
"""

from __future__ import annotations

import ast
from pathlib import Path

V2_ROOT = Path(__file__).resolve().parents[2]
COMPOSITION_ROOT = V2_ROOT / "composition"

# Ratchet: admin.py was 7,203 lines when the audit was written and 6,870 at the
# start of MT1 Phase B. Post-extraction it is ~4,400, and the Billing Health
# trim (spec 2026-09-07 §5.1) moved the Stripe-plumbing wiring out to
# composition/billing_health.py, taking it to ~4,330. The budget leaves room
# for genuine new wiring without leaving room for another report pipeline.
ADMIN_COMPOSITION_LINE_BUDGET = 4_500

#: Wiring that must NOT be back inside admin.py: it belongs to the page-scoped
#: composition modules that exist because admin.py has no room left.
EXTRACTED_CLOSURES = (
    "async def get_connect_readiness",
    "async def list_reconciliation_runs",
    "async def run_reconciliation",
    "async def replay_webhook_event",
    "async def list_billing_webhook_events",
    "async def get_billing_reconciliation_report",
    "async def confirm_legacy_match",
)


def test_admin_composition_stays_within_line_budget() -> None:
    line_count = len((COMPOSITION_ROOT / "admin.py").read_text(encoding="utf-8").splitlines())
    assert line_count <= ADMIN_COMPOSITION_LINE_BUDGET, (
        f"composition/admin.py is {line_count} lines, over the "
        f"{ADMIN_COMPOSITION_LINE_BUDGET}-line wiring budget. Composition modules "
        "are wiring only — move the new logic into the owning context "
        "(see docs/audit/plans/MT1-drain-composition-root.md) rather than "
        "raising this number."
    )


def test_billing_health_wiring_left_admin_composition() -> None:
    """The Billing Health closures live in their own module and are wired there.

    Spec 2026-09-07 §5.1: admin.py had ~49 lines of headroom, so this page's
    wiring moved out wholesale rather than being trimmed. If it drifts back,
    the line budget above fails days later on someone else's change — fail here
    instead, where the cause is obvious.
    """
    admin_src = (COMPOSITION_ROOT / "admin.py").read_text(encoding="utf-8")
    back_inside = [name for name in EXTRACTED_CLOSURES if name in admin_src]
    assert not back_inside, f"Billing Health wiring is back in admin.py: {back_inside}"

    health_src = (COMPOSITION_ROOT / "billing_health.py").read_text(encoding="utf-8")
    for name in EXTRACTED_CLOSURES:
        assert name in health_src, f"{name} is missing from composition/billing_health.py"

    main_src = (V2_ROOT / "main.py").read_text(encoding="utf-8")
    assert "compose_admin_billing_health" in main_src
    assert "app.state.admin_billing_health" in main_src


def test_no_context_or_shared_module_imports_composition() -> None:
    """Backstop for import-linter's ``composition-is-outermost`` contract.

    Same rationale as ``test_layering.py``: the contract is the primary
    enforcer, this catches the violation on a fresh clone without
    import-linter installed.
    """
    offenders: list[str] = []
    for root in (V2_ROOT / "contexts", V2_ROOT / "shared"):
        for path in root.rglob("*.py"):
            if "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                elif isinstance(node, ast.Import):
                    module = node.names[0].name
                else:
                    continue
                if module.startswith("backend.v2.composition"):
                    offenders.append(f"{path.relative_to(V2_ROOT)}: {module}")

    assert not offenders, (
        "Composition is the outermost layer — contexts and shared may not "
        "import it. Invert the dependency (inject the collaborator) instead:\n"
        + "\n".join(offenders)
    )
