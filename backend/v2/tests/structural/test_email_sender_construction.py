"""One env-gated construction site for the real Resend adapter.

``ResendEmailSendPort`` may only be instantiated where the staging/prod
environment gate is applied. The gate was duplicated three times and one copy
(``digests._build_digest_parts``, wiring the coach daily digest and the
admin-triggered digest test) silently omitted the environment check, so a dev
stack that inherited ``EMAIL_DELIVERY_ENABLED`` + ``RESEND_API_KEY`` mailed real
coaches. Rather than trusting three copies to stay in sync, every send path now
goes through ``digests._build_email_sender``.

This is an AST tripwire, not a behavioural test: it parses the composition
package and fails on any *new* construction site, which is how a future wiring
change would re-introduce the hole.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

V2_ROOT = Path(__file__).resolve().parents[2]
COMPOSITION_ROOT = V2_ROOT / "composition"

# Port name -> ``module::function`` sites allowed to construct the real adapter.
#
# * ``_build_email_sender`` is THE env-gated factory every send path uses.
# * ``compose_email_credential_probe`` deliberately follows the credential
#   rather than the environment (issue #435): it only ever issues a read
#   (``Domains.list``) with an unusable from-address, so no send path is
#   reachable from it. See its docstring.
# * ``compose_ai`` is the one site for the Anthropic adapter, gated on
#   ``V2_AI_ENABLED`` + ``V2_ANTHROPIC_API_KEY`` (AI foundation, plan
#   2026-11-04 Phase 1).
GATED_PORTS: dict[str, frozenset[str]] = {
    "ResendEmailSendPort": frozenset(
        {
            "digests.py::_build_email_sender",
            "digests.py::compose_email_credential_probe",
        }
    ),
    "AnthropicLlmPort": frozenset({"ai.py::compose_ai"}),
}


def _enclosing_function(tree: ast.Module, node: ast.AST) -> str:
    """Name of the innermost function containing ``node`` ("<module>" if none)."""
    name = "<module>"
    for parent in ast.walk(tree):
        if not isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for child in ast.walk(parent):
            if child is node:
                name = parent.name
    return name


def _construction_sites(port_name: str) -> set[str]:
    sites: set[str] = set()
    for path in sorted(COMPOSITION_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else ""
            )
            if called != port_name:
                continue
            sites.add(f"{path.name}::{_enclosing_function(tree, node)}")
    return sites


@pytest.mark.parametrize("port_name", sorted(GATED_PORTS))
def test_gated_port_is_only_constructed_behind_the_env_gate(port_name: str) -> None:
    unexpected = _construction_sites(port_name) - GATED_PORTS[port_name]
    assert not unexpected, (
        f"{port_name} is constructed outside the env-gated factory at: "
        f"{sorted(unexpected)}. Real email must only be wired in staging/prod "
        "(AGENTS.md: 'Do not send real email from local/test environments') and "
        "the real model port only behind V2_AI_ENABLED; call the gated factory "
        "instead of instantiating the adapter directly."
    )


@pytest.mark.parametrize("port_name", sorted(GATED_PORTS))
def test_allowed_construction_sites_still_exist(port_name: str) -> None:
    """Guards the allowlist against silently going stale on a rename."""
    assert _construction_sites(port_name) == set(GATED_PORTS[port_name])
