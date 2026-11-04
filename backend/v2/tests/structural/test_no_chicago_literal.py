"""No hardcoded ``"America/Chicago"`` outside the one legacy-fallback constant.

Hardcoded-values row 7: the zone used to be a silent fallback at ~14 sites,
so any tenant outside US Central had sessions, bills and emails read on
BLNO's clock. The single remaining copy is ``LEGACY_FALLBACK_TIMEZONE`` in
``shared/time/academy_timezone.py``; every site resolves session zone ->
academy zone -> that constant via ``resolve_session_timezone``.

Only string constants are scanned (AST), so comments and docstrings that
mention Chicago as an example are fine. Migrations are frozen history and
tests are fixtures, so both are exempt.
"""

from __future__ import annotations

import ast
from pathlib import Path

V2_ROOT = Path(__file__).resolve().parents[2]

ALLOWED = {V2_ROOT / "shared" / "time" / "academy_timezone.py"}
EXEMPT_DIRS = ("migrations", "tests")


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def test_no_america_chicago_literal_outside_the_legacy_constant() -> None:
    offenders: list[str] = []
    for path in sorted(V2_ROOT.rglob("*.py")):
        rel = path.relative_to(V2_ROOT)
        if rel.parts and rel.parts[0] in EXEMPT_DIRS:
            continue
        if path in ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "America/Chicago" in node.value
                and id(node) not in docstrings
            ):
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        "Hardcoded 'America/Chicago' found; resolve the zone with "
        "backend.v2.shared.time.resolve_session_timezone (session -> academy -> "
        f"LEGACY_FALLBACK_TIMEZONE) instead: {offenders}"
    )
