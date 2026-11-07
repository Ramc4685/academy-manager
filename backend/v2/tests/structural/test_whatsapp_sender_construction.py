"""One env-gated construction site for the real OpenWA adapter.

Mirrors ``test_email_sender_construction``: ``OpenWaWhatsAppSendPort`` talks to
a gateway that posts into real WhatsApp groups as the owner's number, so it may
only be built inside ``composition.whatsapp.build_whatsapp_sender``, where the
staging/prod gate and the local sandbox allowlist are applied. An AST tripwire,
so a future wiring change cannot quietly add a second, ungated copy.
"""

from __future__ import annotations

import ast
from pathlib import Path

V2_ROOT = Path(__file__).resolve().parents[2]
PORT_NAME = "OpenWaWhatsAppSendPort"
ALLOWED_CONSTRUCTION_SITES = frozenset({"whatsapp.py::build_whatsapp_sender"})
SCANNED = (V2_ROOT / "composition", V2_ROOT / "interfaces", V2_ROOT / "contexts")


def _enclosing_function(tree: ast.Module, node: ast.AST) -> str:
    name = "<module>"
    for parent in ast.walk(tree):
        if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef) and any(
            child is node for child in ast.walk(parent)
        ):
            name = parent.name
    return name


def _construction_sites() -> set[str]:
    sites: set[str] = set()
    for root in SCANNED:
        for path in sorted(root.rglob("*.py")):
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
                if called == PORT_NAME:
                    sites.add(f"{path.name}::{_enclosing_function(tree, node)}")
    return sites


def test_openwa_port_is_only_constructed_behind_the_env_gate() -> None:
    sites = _construction_sites()
    unexpected = sites - ALLOWED_CONSTRUCTION_SITES
    assert not unexpected, (
        f"{PORT_NAME} is constructed outside the env-gated factory at: {sorted(unexpected)}. "
        "Real WhatsApp must only be wired in staging/prod or through the local sandbox "
        "allowlist; call composition.whatsapp.build_whatsapp_sender instead."
    )


def test_the_allowed_site_still_exists() -> None:
    assert _construction_sites() >= ALLOWED_CONSTRUCTION_SITES
