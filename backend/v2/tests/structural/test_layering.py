"""Structural enforcement of the layering rules from ADR-0005.

This test is a backstop. `import-linter` is the primary enforcer (configured in
backend/pyproject.toml). When import-linter is unavailable (e.g., a fresh
clone), this test still catches the most obvious violations.
"""

from __future__ import annotations

import ast
import pathlib

V2_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _iter_python_files(root: pathlib.Path):
    for p in root.rglob("*.py"):
        # Skip tests; they may import anything.
        if "tests" in p.parts:
            continue
        yield p


def _imports_for(file: pathlib.Path) -> list[str]:
    try:
        tree = ast.parse(file.read_text())
    except SyntaxError:
        return []
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out.append(alias.name)
    return out


def test_domain_does_not_import_infrastructure_or_interfaces() -> None:
    contexts_root = V2_ROOT / "contexts"
    if not contexts_root.exists():
        return  # no contexts yet (Phase 0); skip.
    for file in _iter_python_files(contexts_root):
        if "/domain/" not in str(file):
            continue
        for imp in _imports_for(file):
            assert "infrastructure" not in imp, f"{file} imports infrastructure: {imp}"
            assert "interfaces" not in imp, f"{file} imports interfaces: {imp}"


def test_application_does_not_import_infrastructure() -> None:
    contexts_root = V2_ROOT / "contexts"
    if not contexts_root.exists():
        return
    for file in _iter_python_files(contexts_root):
        if "/application/" not in str(file):
            continue
        for imp in _imports_for(file):
            assert "infrastructure" not in imp, (
                f"{file} (application) imports infrastructure: {imp}"
            )


def test_no_cross_context_imports() -> None:
    contexts_root = V2_ROOT / "contexts"
    if not contexts_root.exists():
        return
    for file in _iter_python_files(contexts_root):
        parts = file.relative_to(contexts_root).parts
        if len(parts) < 2:
            continue
        own_context = parts[0]
        for imp in _imports_for(file):
            if "backend.v2.contexts." in imp:
                imported_context = imp.split("backend.v2.contexts.")[1].split(".")[0]
                assert imported_context == own_context, (
                    f"{file} imports another context: {imp}"
                )
