"""Static guard against raw Mongo access to tenant-owned collections.

The goal is not to fix every current transitional BFF composition read in
this task. Instead, this locks the rule and keeps any exception explicit.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

V2_ROOT = Path(__file__).resolve().parents[1]

TENANT_OWNED_COLLECTIONS = {
    "account_credit_ledger",
    "academies",
    "academy_domains",
    "academy_feature_flags",
    "academy_memberships",
    "academy_roles",
    "academy_settings",
    "announcements",
    "attendance",
    "audit_logs",
    "billing_calculation_snapshots",
    "billing_invoice_keys",
    "billing_policies",
    "enrollment_events",
    "enrollments",
    "expenses",
    "lesson_plans",
    "messages",
    "onboarding_applications",
    "payments",
    "payouts",
    "progress_notes",
    "session_occurrence_overrides",
    "session_occurrences",
    "sessions",
    "students",
    "subscriptions",
    "users",
    "waiver_acceptances",
    "waiver_versions",
    "waivers",
    "waitlist",
    # skill pathway collections
    "skill_programs",
    "skill_levels",
    "skills",
    "skill_criteria",
    "external_lesson_refs",
    "student_level_progress",
    "student_skill_progress",
    "test_attempts",
    "level_up_recommendations",
    "skill_certificates",
    "coach_skill_notes",
}

MONGO_METHODS = {
    "aggregate",
    "bulk_write",
    "count_documents",
    "delete_many",
    "delete_one",
    "distinct",
    "find",
    "find_one",
    "find_one_and_delete",
    "find_one_and_replace",
    "find_one_and_update",
    "insert_many",
    "insert_one",
    "replace_one",
    "update_many",
    "update_one",
}

APPROVED_COMPOSITION_EXCEPTIONS = {
    Path("composition/admin.py"): (
        "Transitional Admin BFF read-model composition while Agent A/B replace "
        "default-academy wiring with request tenant claims."
    ),
    Path("composition/coach.py"): (
        "Transitional Coach dashboard aggregation while Agent A/B replace "
        "default-academy wiring with request tenant claims."
    ),
    Path("composition/parent.py"): (
        "Transitional Parent BFF read-model composition while Agent A/B replace "
        "default-academy wiring with request tenant claims."
    ),
    Path("interfaces/admin/progress_routes.py"): (
        "Transitional: fire-and-forget audit_logs.insert_one written inline as a "
        "pathway-placement side effect until an AuditLogRepository is introduced."
    ),
}


@dataclass(frozen=True)
class RawMongoAccess:
    path: Path
    line: int
    detail: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: {self.detail}"


def test_no_unapproved_raw_mongo_access_to_tenant_owned_collections() -> None:
    violations: list[RawMongoAccess] = []
    for path in sorted(V2_ROOT.rglob("*.py")):
        rel_path = path.relative_to(V2_ROOT)
        if _is_approved_path(rel_path):
            continue
        violations.extend(_raw_mongo_accesses(path, rel_path))

    assert not violations, (
        "Raw Mongo access to tenant-owned collections must go through "
        "TenantScopedRepository-backed infrastructure or an explicitly listed "
        "composition exception.\n" + "\n".join(access.format() for access in violations)
    )


def test_composition_exceptions_are_explicit_and_documented() -> None:
    for rel_path, rationale in APPROVED_COMPOSITION_EXCEPTIONS.items():
        assert (V2_ROOT / rel_path).exists(), f"Missing approved exception path: {rel_path}"
        assert "Transitional" in rationale


def test_hardened_admin_composition_paths_use_request_tenant_not_default() -> None:
    guarded_functions = [
        "list_audit_logs",
        "list_dues_followup",
        "get_billing_invoice_detail",
        "generate_billing_invoice_artifact",
        "export_report_csv",
        "get_enrollment_funnel",
        "get_attendance_trends",
        "get_coach_utilization",
    ]
    source = (V2_ROOT / "composition/admin.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()

    for function_name in guarded_functions:
        function_source = _node_source(
            _find_function(tree, function_name),
            lines,
        )
        assert "current_academy_id" in function_source, function_name
        assert "settings.default_academy_id" not in function_source, function_name


def test_parent_composition_requires_explicit_academy_id() -> None:
    source = (V2_ROOT / "composition/parent.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()

    for function_name in ("compose_parent", "compose_parent_webhook_handler"):
        function_source = _node_source(_find_function(tree, function_name), lines)
        assert "academy_id: str" in function_source, function_name
        assert "_require_academy_id(academy_id)" in function_source, function_name
        assert "settings.default_academy_id" not in function_source, function_name

    helper_source = _node_source(_find_function(tree, "_require_academy_id"), lines)
    assert "if not academy_id:" in helper_source


def test_raw_mongo_guard_reports_tenant_owned_direct_access(tmp_path) -> None:
    path = tmp_path / "bad_repo.py"
    path.write_text(
        "async def bad(db):\n    return await db['students'].find_one({'student_id': 's1'})\n",
        encoding="utf-8",
    )

    accesses = _raw_mongo_accesses(path, Path("bad_repo.py"))

    assert len(accesses) == 1
    assert accesses[0].detail == "raw access to `students` via `find_one`"


def _is_approved_path(rel_path: Path) -> bool:
    parts = rel_path.parts
    if "tests" in parts or "migrations" in parts:
        return True
    if "contexts" in parts and "infrastructure" in parts:
        return True
    if rel_path == Path("shared/tenancy/repository.py"):
        return True
    return rel_path in APPROVED_COMPOSITION_EXCEPTIONS


def _raw_mongo_accesses(path: Path, rel_path: Path) -> list[RawMongoAccess]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    visitor = _RawMongoAccessVisitor(rel_path)
    visitor.visit(tree)
    return visitor.accesses


def _find_function(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function not found: {name}")


def _node_source(node: ast.AST, lines: list[str]) -> str:
    assert node.end_lineno is not None
    return "\n".join(lines[node.lineno - 1 : node.end_lineno])


class _RawMongoAccessVisitor(ast.NodeVisitor):
    def __init__(self, rel_path: Path) -> None:
        self.rel_path = rel_path
        self.aliases: dict[str, str] = {}
        self.accesses: list[RawMongoAccess] = []

    def visit_Assign(self, node: ast.Assign) -> None:
        collection = self._collection_from_expr(node.value)
        if collection in TENANT_OWNED_COLLECTIONS:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.aliases[target.id] = collection
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            collection = self._collection_from_expr(node.value)
            if collection in TENANT_OWNED_COLLECTIONS and isinstance(node.target, ast.Name):
                self.aliases[node.target.id] = collection
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr in MONGO_METHODS:
            collection = self._collection_from_expr(node.func.value)
            if collection in TENANT_OWNED_COLLECTIONS:
                self.accesses.append(
                    RawMongoAccess(
                        path=self.rel_path,
                        line=node.lineno,
                        detail=f"raw access to `{collection}` via `{node.func.attr}`",
                    )
                )
            elif self._is_repository_collection_expr(node.func.value):
                self.accesses.append(
                    RawMongoAccess(
                        path=self.rel_path,
                        line=node.lineno,
                        detail=f"raw repository `.collection` access via `{node.func.attr}`",
                    )
                )
        self.generic_visit(node)

    def _collection_from_expr(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Subscript) and _is_collection_lookup(node):
            return _constant_slice_value(node.slice)
        if isinstance(node, ast.Name):
            return self.aliases.get(node.id)
        if isinstance(node, ast.Attribute):
            return self.aliases.get(node.attr)
        return None

    @staticmethod
    def _is_repository_collection_expr(node: ast.AST) -> bool:
        return isinstance(node, ast.Attribute) and node.attr == "collection"


def _is_collection_lookup(node: ast.Subscript) -> bool:
    return isinstance(_constant_slice_value(node.slice), str)


def _constant_slice_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None
