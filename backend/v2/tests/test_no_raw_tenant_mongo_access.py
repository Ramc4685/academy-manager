"""Static guard against raw Mongo access to tenant-owned collections.

This test is a *structural ratchet*, not a security boundary: it walks the
v2 AST and fails when code reaches a tenant-owned Mongo collection
(``db["students"].find(...)`` and friends) without a visible tenant-scoping
signal. Correctness of the runtime scoping is covered by ``TenantScopedRepository``
and the C4 behavioural tests; this guard exists to catch *accidental* raw
access sneaking in.

Scope (tightened by MT4, 2026-07-21):
- Every ``*.py`` under v2 is scanned except tests, migrations, the tenancy
  enforcement point itself (``shared/tenancy/repository.py``), and a small,
  explicit, per-file composition allowlist (see ``APPROVED_COMPOSITION_EXCEPTIONS``).
  The previous blanket exemption of *all* ``contexts/*/infrastructure`` and of
  ``composition/{parent,coach}.py`` has been removed — those are exactly the
  directories where the audit (Critical #4) found raw tenant queries.
- An access is treated as tenant-scoped (and therefore allowed) when the call
  site or its enclosing function carries a scoping signal: an ``academy_id``
  filter/parameter, or a ``TenantScopedRepository._scoped(...)`` helper call.
  Reaching into *another* object's ``.collection`` (bypassing its scoped
  methods) is always flagged.
- A repository's OWN ``self.collection`` is also inspected for the mutating
  methods (update / replace / delete / find_one_and_*): inside a class that
  declares a literal ``collection_name`` not listed in ``GLOBAL_COLLECTIONS``,
  such a call must carry a scoping signal (issue #880: the digest mark_*
  updates filtered on a bare ``digest_id`` and nothing here noticed, because
  ``self.collection`` was never looked at). Reads on ``self.collection`` are
  left alone to keep the ratchet from over-firing on already-scoped list
  queries. See docs/agent/backend-api-rules.md, "Tenant-scope guard test".

The heuristic deliberately over-approves (a function that merely mentions
``academy_id`` is trusted). That is acceptable for a ratchet: it reliably
catches the un-scoped ``db["students"].find({})`` mistake while never
requiring a path-level blanket. If a genuinely un-scopable raw access ever
appears, fix the call site (thread ``academy_id`` through) or add a narrow,
documented per-line entry here — never re-introduce a directory blanket.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

V2_ROOT = Path(__file__).resolve().parents[1]

# Collections that are per-academy and MUST be tenant-scoped on every access.
TENANT_OWNED_COLLECTIONS = {
    "account_credit_ledger",
    "academy_feature_flags",
    "academy_roles",
    "academy_settings",
    "announcements",
    "attendance",
    "audit_logs",
    "billing_calculation_snapshots",
    "billing_generation_runs",
    "billing_invoice_keys",
    "billing_policies",
    "dunning_states",
    "enrollment_events",
    "enrollments",
    "invoices",
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
    "stripe_webhook_events",
    "students",
    "subscriptions",
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
    # curriculum (migration 0124) — added by #881
    "lesson_cards",
    "curriculum_video_refs",
    # digest sends: per-academy rows, written from a cron path that scopes
    # explicitly rather than through the ContextVar (#880)
    "coach_digest_sends",
    "parent_digest_sends",
    # People CRM leads shared with the public tenant page (migration 0192)
    "crm_contacts",
}

# Global / cross-tenant collections. These intentionally span academies (or are
# resolved before a tenant context exists), so raw access to them is allowed and
# must NOT be forced through TenantScopedRepository. Each carries its rationale.
GLOBAL_COLLECTIONS = {
    # A user identity spans academies; looked up by email / firebase uid at
    # auth time, before the tenant ContextVar is set.
    "users",
    # The tenant registry itself — the row that *defines* an academy.
    "academies",
    # Maps users <-> academies; queried by (academy_id, user_id) during the
    # auth bootstrap, before tenant context exists (see MongoMembershipRepository).
    "academy_memberships",
    # Host -> academy mapping, resolved globally by hostname during request
    # tenant resolution (see shared/tenancy/resolver.py).
    "academy_domains",
}

assert not (TENANT_OWNED_COLLECTIONS & GLOBAL_COLLECTIONS), (
    "A collection cannot be both tenant-owned and global"
)

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

# Methods that write. An unscoped one of these on a repository's own
# ``self.collection`` can change another tenant's row (#880); unscoped reads
# are a leak too, but are left to the collection-literal check above so this
# ratchet does not fire on list queries that scope by their own filter.
MUTATING_METHODS = {
    "delete_many",
    "delete_one",
    "find_one_and_delete",
    "find_one_and_replace",
    "find_one_and_update",
    "replace_one",
    "update_many",
    "update_one",
}
assert MUTATING_METHODS <= MONGO_METHODS

# Substrings whose presence at a call site or in the enclosing function marks an
# access as tenant-scoped. ``academy_id`` also matches ``current_academy_id(``.
SCOPING_TOKENS = ("academy_id", "_scoped(")

# Narrow, per-file composition allowlist. Each entry MUST name the tracker item
# that removes it. The blanket ``composition/{parent,coach}.py`` entries were
# dropped once C4 (#317) moved those paths onto request-time tenant claims.
# The ``composition/admin.py`` entry was removed by MT1 Phases B-E: the report
# pipelines and payout read models that carried its raw reads now live in
# ``contexts/{billing,coaching}/infrastructure``, and the file is scanned like
# any other.
APPROVED_COMPOSITION_EXCEPTIONS = {
    Path("interfaces/admin/progress_routes.py"): (
        "Transitional: fire-and-forget audit_logs.insert_one written inline as a "
        "pathway-placement side effect until an AuditLogRepository is introduced."
    ),
}


# By-design cross-tenant readers. Unlike the transitional entries above these
# are NOT scheduled for removal: the file's whole purpose is to aggregate across
# academies, so threading `academy_id` through would defeat it. Each entry must
# say what it reads and why the read cannot be tenant-scoped. Admission bar:
# read-only, operator-facing, never reachable from a tenant request path.
APPROVED_CROSS_TENANT_EXCEPTIONS = {
    Path("shared/observability/owner_daily_brief.py"): (
        "By design cross-tenant and read-only: the daily owner brief (issue #776) "
        "counts enrollments, enrollment_events, onboarding_applications, payments, "
        "invoices, students, waiver_acceptances and email_suppressions across every "
        "academy, the same way its sibling ops_digest does. It runs only from the "
        "scheduler (no request path reaches it) and writes nothing at all."
    ),
    Path("shared/observability/ops_digest.py"): (
        "By design cross-tenant and read-only: the daily owner ops digest counts "
        "stripe_webhook_events, dead_letter_events, dunning_states and the coach/"
        "parent digest_sends collections across every "
        "academy. It runs only from the scheduler (no request path reaches it) and "
        "its single write targets the global ops_job_runs collection."
    ),
}

assert not (APPROVED_COMPOSITION_EXCEPTIONS.keys() & APPROVED_CROSS_TENANT_EXCEPTIONS.keys()), (
    "A file cannot be both a transitional and a by-design exception"
)


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
        "Raw Mongo access to tenant-owned collections must be tenant-scoped "
        "(academy_id filter / _scoped() helper) or go through "
        "TenantScopedRepository. Fix the call site or add a documented entry — "
        "do not re-add a directory blanket.\n" + "\n".join(access.format() for access in violations)
    )


def test_composition_exceptions_are_explicit_and_documented() -> None:
    for rel_path, rationale in APPROVED_COMPOSITION_EXCEPTIONS.items():
        assert (V2_ROOT / rel_path).exists(), f"Missing approved exception path: {rel_path}"
        assert "Transitional" in rationale
        # Every exception must document how/when it is removed.
        assert "until" in rationale, rel_path


def test_cross_tenant_exceptions_are_explicit_and_documented() -> None:
    for rel_path, rationale in APPROVED_CROSS_TENANT_EXCEPTIONS.items():
        assert (V2_ROOT / rel_path).exists(), f"Missing approved exception path: {rel_path}"
        # The bar for a permanent exception: say it is cross-tenant on purpose,
        # and say it does not write tenant-owned data.
        assert "cross-tenant" in rationale, rel_path
        assert "read-only" in rationale, rel_path


def test_infrastructure_and_transitional_composition_are_no_longer_blanket_exempt() -> None:
    # Guard the ratchet itself: the risky directories the audit flagged must be
    # scanned, and the C4-hardened composition paths must no longer be exempt.
    assert not _is_approved_path(Path("contexts/enrollment/infrastructure/mongo_student_repo.py"))
    assert not _is_approved_path(Path("composition/parent.py"))
    assert not _is_approved_path(Path("composition/coach.py"))
    assert Path("composition/parent.py") not in APPROVED_COMPOSITION_EXCEPTIONS
    assert Path("composition/coach.py") not in APPROVED_COMPOSITION_EXCEPTIONS
    # MT1 drained the admin composition root; its exemption must not come back.
    assert not _is_approved_path(Path("composition/admin.py"))
    assert Path("composition/admin.py") not in APPROVED_COMPOSITION_EXCEPTIONS


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


def test_scoped_access_via_academy_id_filter_is_clean(tmp_path) -> None:
    path = tmp_path / "ok_filter.py"
    path.write_text(
        "async def ok(db, academy_id):\n"
        "    return await db['students'].find_one(\n"
        "        {'academy_id': academy_id, 'student_id': 's1'}\n"
        "    )\n",
        encoding="utf-8",
    )
    assert _raw_mongo_accesses(path, Path("ok_filter.py")) == []


def test_scoped_access_via_scoped_helper_is_clean(tmp_path) -> None:
    # Cross-collection read inside a repository that uses the _scoped() helper.
    path = tmp_path / "ok_scoped.py"
    path.write_text(
        "class Repo(TenantScopedRepository):\n"
        "    async def count(self, session_id):\n"
        "        return await self._db['enrollments'].count_documents(\n"
        "            self._scoped({'session_id': session_id})\n"
        "        )\n",
        encoding="utf-8",
    )
    assert _raw_mongo_accesses(path, Path("ok_scoped.py")) == []


def test_unscoped_cross_collection_read_is_flagged(tmp_path) -> None:
    # A repo method that reaches another tenant-owned collection with no
    # scoping signal anywhere is a real accidental-leak risk — flag it.
    path = tmp_path / "bad_cross.py"
    path.write_text(
        "class Repo(TenantScopedRepository):\n"
        "    async def leak(self, student_id):\n"
        "        return await self._db['enrollments'].find_one({'student_id': student_id})\n",
        encoding="utf-8",
    )
    accesses = _raw_mongo_accesses(path, Path("bad_cross.py"))
    assert len(accesses) == 1
    assert "enrollments" in accesses[0].detail


def test_global_collection_raw_access_is_clean(tmp_path) -> None:
    path = tmp_path / "ok_global.py"
    path.write_text(
        "async def by_email(db, email):\n    return await db['users'].find_one({'email': email})\n",
        encoding="utf-8",
    )
    assert _raw_mongo_accesses(path, Path("ok_global.py")) == []


def test_reaching_into_foreign_repo_collection_is_flagged(tmp_path) -> None:
    path = tmp_path / "bad_foreign.py"
    path.write_text(
        "async def peek(repo):\n    return await repo.collection.find_one({})\n",
        encoding="utf-8",
    )
    accesses = _raw_mongo_accesses(path, Path("bad_foreign.py"))
    assert len(accesses) == 1
    assert ".collection" in accesses[0].detail


def test_unscoped_mutation_on_own_collection_is_flagged(tmp_path) -> None:
    # The #880 shape: a repository updating its own collection by a bare id.
    path = tmp_path / "bad_own.py"
    path.write_text(
        "class BadRepo(TenantScopedRepository):\n"
        '    collection_name = "coach_digest_sends"\n'
        "    async def mark(self, digest_id):\n"
        "        await self.collection.update_one({'digest_id': digest_id}, {'$set': {}})\n",
        encoding="utf-8",
    )
    accesses = _raw_mongo_accesses(path, Path("bad_own.py"))
    assert len(accesses) == 1
    assert accesses[0].detail == (
        "unscoped `self.collection.update_one` in the repository for `coach_digest_sends`"
    )


def test_unscoped_mutation_is_flagged_for_an_unregistered_collection_too(tmp_path) -> None:
    # A NEW collection needs no registration to be guarded: any declared
    # repository collection that is not listed as global is treated as tenant-owned.
    path = tmp_path / "bad_new.py"
    path.write_text(
        "class NewRepo(TenantScopedRepository):\n"
        '    collection_name = "brand_new_things"\n'
        "    async def drop(self, thing_id):\n"
        "        await self.collection.delete_one({'thing_id': thing_id})\n",
        encoding="utf-8",
    )
    accesses = _raw_mongo_accesses(path, Path("bad_new.py"))
    assert len(accesses) == 1
    assert "brand_new_things" in accesses[0].detail


def test_explicitly_scoped_mutation_on_own_collection_is_clean(tmp_path) -> None:
    # The cron-path pattern: academy_id threaded through as a parameter.
    path = tmp_path / "ok_own_explicit.py"
    path.write_text(
        "class Repo(TenantScopedRepository):\n"
        '    collection_name = "coach_digest_sends"\n'
        "    async def mark(self, academy_id, digest_id):\n"
        "        await self.collection.update_one(\n"
        "            {'academy_id': academy_id, 'digest_id': digest_id}, {'$set': {}}\n"
        "        )\n",
        encoding="utf-8",
    )
    assert _raw_mongo_accesses(path, Path("ok_own_explicit.py")) == []


def test_helper_scoped_mutation_on_own_collection_is_clean(tmp_path) -> None:
    # The request-path pattern: the TenantScopedRepository helpers inject
    # academy_id via _scoped(); they never touch self.collection directly here.
    path = tmp_path / "ok_own_helper.py"
    path.write_text(
        "class Repo(TenantScopedRepository):\n"
        '    collection_name = "lesson_cards"\n'
        "    async def rename(self, card_id, title):\n"
        "        await self._update_one({'card_id': card_id}, {'$set': {'title': title}})\n"
        "    async def raw(self, card_id):\n"
        "        await self.collection.update_one(self._scoped({'card_id': card_id}), {})\n",
        encoding="utf-8",
    )
    assert _raw_mongo_accesses(path, Path("ok_own_helper.py")) == []


def test_unscoped_mutation_on_a_global_collection_is_clean(tmp_path) -> None:
    path = tmp_path / "ok_global_repo.py"
    path.write_text(
        "class Users(TenantScopedRepository):\n"
        '    collection_name = "users"\n'
        "    async def touch(self, user_id):\n"
        "        await self.collection.update_one({'user_id': user_id}, {'$set': {}})\n",
        encoding="utf-8",
    )
    assert _raw_mongo_accesses(path, Path("ok_global_repo.py")) == []


def test_own_collection_reads_are_not_flagged(tmp_path) -> None:
    # Reads are covered by the collection-literal check, not this one: a
    # list query scoped by its own filter must not trip the ratchet.
    path = tmp_path / "ok_own_read.py"
    path.write_text(
        "class Repo(TenantScopedRepository):\n"
        '    collection_name = "coach_digest_sends"\n'
        "    def recent(self, limit):\n"
        "        return self.collection.find({}).limit(limit)\n",
        encoding="utf-8",
    )
    assert _raw_mongo_accesses(path, Path("ok_own_read.py")) == []


def test_issue_881_collections_are_registered_as_tenant_owned() -> None:
    assert {
        "lesson_cards",
        "curriculum_video_refs",
        "coach_digest_sends",
        "parent_digest_sends",
    } <= TENANT_OWNED_COLLECTIONS


def _is_approved_path(rel_path: Path) -> bool:
    parts = rel_path.parts
    if "tests" in parts or "migrations" in parts:
        return True
    if rel_path == Path("shared/tenancy/repository.py"):
        return True
    return (
        rel_path in APPROVED_COMPOSITION_EXCEPTIONS or rel_path in APPROVED_CROSS_TENANT_EXCEPTIONS
    )


def _raw_mongo_accesses(path: Path, rel_path: Path) -> list[RawMongoAccess]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    visitor = _RawMongoAccessVisitor(rel_path, source)
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
    def __init__(self, rel_path: Path, source: str) -> None:
        self.rel_path = rel_path
        self.source = source
        self.aliases: dict[str, str] = {}
        self.accesses: list[RawMongoAccess] = []
        self._func_stack: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        # Literal ``collection_name`` of each enclosing class (None when absent).
        self._class_collection_stack: list[str | None] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_collection_stack.append(_declared_collection_name(node))
        self.generic_visit(node)
        self._class_collection_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._func_stack.append(node)
        self.generic_visit(node)
        self._func_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

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
                if not self._is_scoped(node):
                    self.accesses.append(
                        RawMongoAccess(
                            path=self.rel_path,
                            line=node.lineno,
                            detail=f"raw access to `{collection}` via `{node.func.attr}`",
                        )
                    )
            elif self._is_foreign_repository_collection(node.func.value):
                if not self._is_scoped(node):
                    self.accesses.append(
                        RawMongoAccess(
                            path=self.rel_path,
                            line=node.lineno,
                            detail=f"raw repository `.collection` access via `{node.func.attr}`",
                        )
                    )
            elif node.func.attr in MUTATING_METHODS and _is_own_collection(node.func.value):
                own = self._own_collection_name()
                if own is not None and own not in GLOBAL_COLLECTIONS and not self._is_scoped(node):
                    self.accesses.append(
                        RawMongoAccess(
                            path=self.rel_path,
                            line=node.lineno,
                            detail=(
                                f"unscoped `self.collection.{node.func.attr}` in the "
                                f"repository for `{own}`"
                            ),
                        )
                    )
        self.generic_visit(node)

    def _own_collection_name(self) -> str | None:
        return self._class_collection_stack[-1] if self._class_collection_stack else None

    def _is_scoped(self, node: ast.Call) -> bool:
        segment = ast.get_source_segment(self.source, node) or ""
        if any(token in segment for token in SCOPING_TOKENS):
            return True
        if self._func_stack:
            func_segment = ast.get_source_segment(self.source, self._func_stack[-1]) or ""
            if any(token in func_segment for token in SCOPING_TOKENS):
                return True
        return False

    def _collection_from_expr(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Subscript) and _is_collection_lookup(node):
            return _constant_slice_value(node.slice)
        if isinstance(node, ast.Name):
            return self.aliases.get(node.id)
        if isinstance(node, ast.Attribute):
            return self.aliases.get(node.attr)
        return None

    @staticmethod
    def _is_foreign_repository_collection(node: ast.AST) -> bool:
        # `<something>.collection.<method>()` where `<something>` is NOT `self`:
        # reaching into another repository's raw collection, bypassing its
        # tenant-scoped methods. `self.collection` is the repo's own declared
        # collection and is handled by TenantScopedRepository.
        if not (isinstance(node, ast.Attribute) and node.attr == "collection"):
            return False
        return not (isinstance(node.value, ast.Name) and node.value.id == "self")


def _is_own_collection(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "collection"
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )


def _declared_collection_name(node: ast.ClassDef) -> str | None:
    """The class's literal ``collection_name = "<name>"``, if it declares one."""
    for stmt in node.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(stmt, ast.Assign):
            targets, value = list(stmt.targets), stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            targets, value = [stmt.target], stmt.value
        if any(isinstance(t, ast.Name) and t.id == "collection_name" for t in targets):
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
    return None


def _is_collection_lookup(node: ast.Subscript) -> bool:
    return isinstance(_constant_slice_value(node.slice), str)


def _constant_slice_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None
