"""Mongo store for CSV import batches (``import_batches``, migration 0199) and
their audit rows.

Both extend ``TenantScopedRepository``: ``academy_id`` comes from the tenant
context on every query and every insert, so a batch id of another academy
is never found and never changed. The status moves are conditional updates
(``previewed`` -> ``committing`` -> ``committed``), so two commits racing on
one batch cannot both claim it. The claim is two sequential conditional
updates, never an ``$or``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, cast

from backend.v2.contexts.crm.domain.family_import import ImportRow, RowIssue
from backend.v2.contexts.crm.domain.import_batches import (
    ImportBatch,
    ImportSummary,
    PlannedRow,
)
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id
from backend.v2.shared.time import ensure_utc


def _utc(value: object) -> datetime:
    return ensure_utc(cast(datetime, value))


def _opt_utc(value: object) -> datetime | None:
    return None if value is None else _utc(value)


def _issues(values: Sequence[RowIssue]) -> list[dict[str, str]]:
    return [{"field": issue.field, "message": issue.message} for issue in values]


def _issues_back(values: object) -> tuple[RowIssue, ...]:
    return tuple(
        RowIssue(field=str(item["field"]), message=str(item["message"]))
        for item in cast("list[Mapping[str, Any]]", values or [])
    )


def row_to_doc(planned: PlannedRow) -> dict[str, Any]:
    row = planned.row
    return {
        "line": row.line,
        "parent_name": row.parent_name,
        "student_name": row.student_name,
        "parent_email": row.parent_email,
        "parent_phone": row.parent_phone,
        "student_date_of_birth": row.student_date_of_birth,
        "row_errors": _issues(row.errors),
        "row_warnings": list(row.warnings),
        "family_key": planned.family_key,
        "new_family_id": planned.new_family_id,
        "student_id": planned.student_id,
        "status": planned.status,
        "family_action": planned.family_action,
        "family_id": planned.family_id,
        "family_name": planned.family_name,
        "plan_errors": _issues(planned.plan_errors),
        "plan_warnings": list(planned.plan_warnings),
    }


def row_from_doc(doc: Mapping[str, Any]) -> PlannedRow:
    return PlannedRow(
        row=ImportRow(
            line=int(doc["line"]),
            parent_name=str(doc.get("parent_name") or ""),
            student_name=str(doc.get("student_name") or ""),
            parent_email=doc.get("parent_email"),
            parent_phone=doc.get("parent_phone"),
            student_date_of_birth=doc.get("student_date_of_birth"),
            errors=_issues_back(doc.get("row_errors")),
            warnings=tuple(str(w) for w in doc.get("row_warnings") or ()),
        ),
        family_key=doc.get("family_key"),
        new_family_id=doc.get("new_family_id"),
        student_id=doc.get("student_id"),
        status=doc["status"],
        family_action=doc.get("family_action"),
        family_id=doc.get("family_id"),
        family_name=doc.get("family_name"),
        plan_errors=_issues_back(doc.get("plan_errors")),
        plan_warnings=tuple(str(w) for w in doc.get("plan_warnings") or ()),
    )


def _summary_doc(summary: ImportSummary) -> dict[str, int]:
    return {
        "rows_total": summary.rows_total,
        "rows_create": summary.rows_create,
        "rows_skip": summary.rows_skip,
        "rows_error": summary.rows_error,
        "families_new": summary.families_new,
        "families_existing": summary.families_existing,
    }


def _summary_back(doc: Mapping[str, Any]) -> ImportSummary:
    return ImportSummary(**{key: int(doc.get(key) or 0) for key in _summary_doc_keys()})


def _summary_doc_keys() -> tuple[str, ...]:
    return (
        "rows_total",
        "rows_create",
        "rows_skip",
        "rows_error",
        "families_new",
        "families_existing",
    )


class MongoImportBatchRepository(TenantScopedRepository):
    collection_name = "import_batches"

    @staticmethod
    def _to_domain(doc: Mapping[str, Any]) -> ImportBatch:
        return ImportBatch(
            import_batch_id=str(doc["import_batch_id"]),
            kind=doc.get("kind") or "families",
            status=doc["status"],
            file_sha256=str(doc.get("file_sha256") or ""),
            filename=doc.get("filename"),
            created_by=str(doc.get("created_by") or ""),
            created_at=_utc(doc["created_at"]),
            updated_at=_utc(doc.get("updated_at") or doc["created_at"]),
            rows=tuple(row_from_doc(row) for row in doc.get("rows") or ()),
            summary=_summary_back(doc.get("summary") or {}),
            claimed_at=_opt_utc(doc.get("claimed_at")),
            committed_at=_opt_utc(doc.get("committed_at")),
            committed_by=doc.get("committed_by"),
            students_created=doc.get("students_created"),
        )

    async def add(self, batch: ImportBatch) -> None:
        await self._insert_one(
            {
                "import_batch_id": batch.import_batch_id,
                "academy_id": current_academy_id(),
                "kind": batch.kind,
                "status": batch.status,
                "file_sha256": batch.file_sha256,
                "filename": batch.filename,
                "created_by": batch.created_by,
                "created_at": batch.created_at,
                "updated_at": batch.updated_at,
                "rows": [row_to_doc(row) for row in batch.rows],
                "summary": _summary_doc(batch.summary),
            }
        )

    async def get(self, import_batch_id: str) -> ImportBatch | None:
        doc = await self._find_one({"import_batch_id": import_batch_id})
        return self._to_domain(doc) if doc else None

    async def claim_for_commit(
        self, import_batch_id: str, *, actor_id: str, now: datetime, stale_before: datetime
    ) -> ImportBatch | None:
        claim = {
            "$set": {
                "status": "committing",
                "claimed_at": now,
                "committed_by": actor_id,
                "updated_at": now,
            }
        }
        doc = await self._find_one_and_update(
            {"import_batch_id": import_batch_id, "status": "previewed"}, claim
        )
        if doc is None:
            # A crashed commit: resume it. Sequential, never an ``$or``.
            doc = await self._find_one_and_update(
                {
                    "import_batch_id": import_batch_id,
                    "status": "committing",
                    "claimed_at": {"$lt": stale_before},
                },
                claim,
            )
        return self._to_domain(doc) if doc else None

    async def release_claim(
        self,
        import_batch_id: str,
        *,
        rows: Sequence[PlannedRow],
        summary: ImportSummary,
        now: datetime,
    ) -> None:
        await self._update_one(
            {"import_batch_id": import_batch_id, "status": "committing"},
            {
                "$set": {
                    "status": "previewed",
                    "rows": [row_to_doc(row) for row in rows],
                    "summary": _summary_doc(summary),
                    "updated_at": now,
                },
                "$unset": {"claimed_at": "", "committed_by": ""},
            },
        )

    async def mark_committed(
        self,
        import_batch_id: str,
        *,
        rows: Sequence[PlannedRow],
        summary: ImportSummary,
        students_created: int,
        now: datetime,
    ) -> ImportBatch | None:
        doc = await self._find_one_and_update(
            {"import_batch_id": import_batch_id, "status": "committing"},
            {
                "$set": {
                    "status": "committed",
                    "rows": [row_to_doc(row) for row in rows],
                    "summary": _summary_doc(summary),
                    "students_created": students_created,
                    "committed_at": now,
                    "updated_at": now,
                }
            },
        )
        return self._to_domain(doc) if doc else None


class MongoImportAuditLog(TenantScopedRepository):
    """``audit_logs`` rows for imports: counts only, never names or contacts."""

    collection_name = "audit_logs"

    def __init__(self, db: Any, *, clock: Any = None) -> None:
        super().__init__(db)
        self._clock = clock

    async def record(
        self,
        *,
        actor_id: str,
        action: str,
        import_batch_id: str,
        summary: ImportSummary,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        now = self._clock() if self._clock is not None else datetime.now(UTC)
        after: dict[str, object] = {**_summary_doc(summary), **dict(extra or {})}
        await self._insert_one(
            {
                "audit_id": new_ulid(),
                "actor_id": actor_id,
                "action": action,
                "entity_type": "import_batch",
                "entity_id": import_batch_id,
                "reason": "CSV family import",
                "changed_keys": sorted(after),
                "before": {},
                "after": after,
                "created_at": now,
            }
        )
