"""Family and student CSV import: preview (dry run) and commit (roadmap L8a).

``PreviewFamilyImport`` parses the file (``domain/family_import.py``), plans
every row against the academy's current families and stores the plan as an
import batch (``domain/import_batches.py``). Nothing else is written.

``CommitFamilyImport`` takes only the batch id. It claims the batch, plans
the stored rows AGAIN against the data as it is now (another admin may have
added one of these families since the preview), refuses when the plan has
any error, and otherwise inserts every row planned ``create``.

What a row becomes
------------------

Each family of the file (rows sharing a parent email, or a phone) is looked
up with the People CRM duplicate finder (``FindPossibleDuplicates``, L1c),
on a family index built fresh for this call:

* its email or phone belongs to exactly ONE existing family: the children
  are added to that family, and a child the family already has (same name,
  ``full_name_key``) is skipped. This is what makes re-uploading a file a
  no-op;
* it belongs to more than one family, to a family contact (a second
  guardian) or to a staff account: an error. The import never guesses which
  record a person is;
* otherwise it is a new roster family: the students carry the parent's
  name, email and phone (the ``parent_*`` roster fields), keyed by a parent
  id minted at preview. No user account and no Firebase login is created,
  and nobody is emailed; Billing Setup's invite provisions the login later,
  exactly as for the other roster parents.

A matching inquiry or a family with the same name only is a warning.

Idempotency
-----------

* Ids are minted at preview and stored on the batch, and every student is
  written with an insert-if-absent keyed by ``(academy_id, student_id)``, so
  running the same commit twice inserts nothing the second time.
* A committed batch answers its stored result again (``already_committed``).
* Two commits of the same batch at once: one claims it, the other gets 409
  (``in_progress``). A claim older than five minutes is a crashed commit and
  the next commit resumes it.

Tenancy: the batch store and the finder's lookups read the tenant context;
the index and the member lookup are handed the same academy id by the
route. Another academy's batch id is not found (404).
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime

from backend.v2.contexts.crm.application.family_index import FamilyIndexUnavailable
from backend.v2.contexts.crm.application.ports import (
    AcademyMemberLookup,
    CrmContactLookup,
    FamilyContactLookup,
    FamilyIndexSource,
    ImportAuditLog,
    ImportBatchRepository,
    ImportedStudentWriter,
)
from backend.v2.contexts.crm.application.use_cases.find_possible_duplicates import (
    DuplicateCheckQuery,
    FindPossibleDuplicates,
)
from backend.v2.contexts.crm.domain.duplicates import DuplicateMatch
from backend.v2.contexts.crm.domain.errors import (
    ImportBatchNotFound,
    ImportNotCommittable,
    ImportUnavailable,
)
from backend.v2.contexts.crm.domain.family_import import (
    IMPORT_COLUMNS,
    MAX_IMPORT_BYTES,
    MAX_IMPORT_ROWS,
    ImportRow,
    RowIssue,
    group_rows,
    parse_family_csv,
)
from backend.v2.contexts.crm.domain.family_index import FamilyIndex, FamilyRecord
from backend.v2.contexts.crm.domain.import_batches import (
    COMMIT_CLAIM_STALE_AFTER,
    FamilyAction,
    ImportBatch,
    ImportSummary,
    PlannedRow,
    summarize,
)
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.names import full_name_key

#: Duplicate lookups in flight at once (each is a handful of indexed reads).
_LOOKUP_CONCURRENCY = 8

AUDIT_PREVIEWED = "crm.import.families.previewed"
AUDIT_COMMITTED = "crm.import.families.committed"

__all__ = [
    "AUDIT_COMMITTED",
    "AUDIT_PREVIEWED",
    "IMPORT_COLUMNS",
    "MAX_IMPORT_BYTES",
    "MAX_IMPORT_ROWS",
    "CommitFamilyImport",
    "CommitFamilyImportResult",
    "FamilyImportPlanner",
    "ImportBatch",
    "ImportSummary",
    "PlannedRow",
    "PreviewFamilyImport",
    "RowIssue",
]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_family_id() -> str:
    return f"parent_{new_ulid().lower()}"


def _own(batch: ImportBatch | None, academy_id: str) -> ImportBatch | None:
    """The batch only when it belongs to ``academy_id``.

    Belt and braces over the store's tenant scoping: a batch stored under
    another academy reads as absent, never as committable.
    """
    if batch is None:
        return None
    if batch.academy_id is not None and batch.academy_id != academy_id:
        return None
    return batch


class _FixedIndex:
    """Hands the finder the one index this call built (never a cached one)."""

    def __init__(self, index: FamilyIndex) -> None:
        self._index = index

    async def build(self, academy_id: str) -> FamilyIndex:
        return self._index


@dataclass(frozen=True)
class _Decision:
    family: FamilyRecord | None = None
    errors: tuple[RowIssue, ...] = ()
    warnings: tuple[str, ...] = ()


def _decide(matches: Sequence[DuplicateMatch], index: FamilyIndex) -> _Decision:
    by_id = {record.family_id: record for record in index.families}
    on_contact = [m for m in matches if {"email", "phone"} & set(m.matched_on)]
    family_ids = list(dict.fromkeys(m.record_id for m in on_contact if m.kind == "family"))
    warnings: list[str] = []
    for match in matches:
        if match.kind == "inquiry":
            warnings.append(f"Matches the inquiry from {match.display_name}.")
        elif match.kind == "family" and match.matched_on == ("name",):
            warnings.append(
                f"A family named {match.display_name} already exists; the email and phone "
                "differ, so this is kept as a separate family."
            )
    if len(family_ids) > 1:
        return _Decision(
            errors=(
                RowIssue(
                    "parent_email",
                    "The email or phone matches more than one existing family. "
                    "Add these children by hand.",
                ),
            ),
            warnings=tuple(warnings),
        )
    if family_ids:
        record = by_id.get(family_ids[0])
        if record is None:  # the finder only reports rows of this index
            raise ImportUnavailable("family index changed during the import check")
        return _Decision(family=record, warnings=tuple(warnings))
    for match in on_contact:
        if match.kind == "family_contact":
            return _Decision(
                errors=(
                    RowIssue(
                        "parent_email",
                        f"The email or phone belongs to {match.display_name}, a contact of an "
                        "existing family. Add this child from that family's page.",
                    ),
                ),
                warnings=tuple(warnings),
            )
        if match.kind == "user":
            return _Decision(
                errors=(
                    RowIssue(
                        "parent_email",
                        f"The email belongs to {match.display_name}, who already has an "
                        "account here. Add this child by hand.",
                    ),
                ),
                warnings=tuple(warnings),
            )
    return _Decision(warnings=tuple(warnings))


class FamilyImportPlanner:
    """Plans stored rows against the academy's data as it is now."""

    def __init__(
        self,
        *,
        families: FamilyIndexSource,
        family_contacts: FamilyContactLookup,
        members: AcademyMemberLookup,
        inquiries: CrmContactLookup,
    ) -> None:
        self._families = families
        self._family_contacts = family_contacts
        self._members = members
        self._inquiries = inquiries

    async def _index(self, academy_id: str) -> FamilyIndex:
        try:
            return await self._families.build(academy_id)
        except FamilyIndexUnavailable as exc:
            # The finder would skip families silently; an import must not.
            raise ImportUnavailable("the family list could not be read; try again") from exc

    async def plan(self, academy_id: str, rows: Sequence[PlannedRow]) -> tuple[PlannedRow, ...]:
        index = await self._index(academy_id)
        finder = FindPossibleDuplicates(
            families=_FixedIndex(index),
            family_contacts=self._family_contacts,
            members=self._members,
            inquiries=self._inquiries,
        )
        groups: dict[str, list[PlannedRow]] = {}
        for planned in rows:
            if planned.family_key is not None:
                groups.setdefault(planned.family_key, []).append(planned)

        gate = asyncio.Semaphore(_LOOKUP_CONCURRENCY)

        async def decide(members: list[PlannedRow]) -> _Decision:
            first = members[0].row
            email = next((m.row.parent_email for m in members if m.row.parent_email), None)
            phone = next((m.row.parent_phone for m in members if m.row.parent_phone), None)
            async with gate:
                matches = await finder.execute(
                    academy_id,
                    DuplicateCheckQuery(email=email, phone=phone, name=first.parent_name),
                )
            return _decide(matches, index)

        keys = list(groups)
        decided = await asyncio.gather(*(decide(groups[key]) for key in keys))
        decisions = dict(zip(keys, decided, strict=True))

        known: dict[str, dict[str, int | None]] = {}
        planned_rows: list[PlannedRow] = []
        for planned in rows:
            planned_rows.append(self._plan_row(planned, decisions, known))
        return tuple(planned_rows)

    @staticmethod
    def _plan_row(
        planned: PlannedRow,
        decisions: Mapping[str, _Decision],
        known: dict[str, dict[str, int | None]],
    ) -> PlannedRow:
        base = replace(
            planned,
            status="error",
            family_action=None,
            family_id=None,
            family_name=None,
            plan_errors=(),
            plan_warnings=(),
        )
        if planned.family_key is None or planned.row.errors:
            return base
        decision = decisions[planned.family_key]
        if decision.errors:
            return replace(base, plan_errors=decision.errors, plan_warnings=decision.warnings)
        action: FamilyAction
        family_id: str
        if decision.family is not None:
            record = decision.family
            family_id = record.family_id
            action = "existing"
            name = record.parent_name
            children = known.setdefault(
                family_id, {full_name_key(child.name): None for child in record.children}
            )
        else:
            family_id = str(planned.new_family_id)
            action = "new"
            name = None
            children = known.setdefault(family_id, {})
        key = planned.row.student_key
        warnings = decision.warnings
        if key in children:
            earlier = children[key]
            note = (
                "Already in this family; nothing to import."
                if earlier is None
                else f"Listed earlier in the file on line {earlier}; nothing to import."
            )
            return replace(
                base,
                status="skip",
                family_action=action,
                family_id=family_id,
                family_name=name,
                plan_warnings=(*warnings, note),
            )
        children[key] = planned.row.line
        return replace(
            base,
            status="create",
            family_action=action,
            family_id=family_id,
            family_name=name,
            plan_warnings=warnings,
        )


class PreviewFamilyImport:
    def __init__(
        self,
        *,
        planner: FamilyImportPlanner,
        batches: ImportBatchRepository,
        audit: ImportAuditLog,
        clock: Callable[[], datetime] = _utc_now,
        new_id: Callable[[], str] = new_ulid,
        new_family_id: Callable[[], str] = _new_family_id,
    ) -> None:
        self._planner = planner
        self._batches = batches
        self._audit = audit
        self._clock = clock
        self._new_id = new_id
        self._new_family_id = new_family_id

    async def execute(
        self,
        academy_id: str,
        *,
        csv_text: str | bytes,
        filename: str | None,
        actor_id: str,
        today: date,
    ) -> ImportBatch:
        parsed = parse_family_csv(csv_text, today=today)
        grouped, keys = group_rows(parsed.rows)
        family_ids: dict[str, str] = {}
        stored: list[PlannedRow] = []
        for row in grouped:
            key = keys.get(row.line)
            family_id = None
            if key is not None:
                family_id = family_ids.setdefault(key, self._new_family_id())
            stored.append(
                PlannedRow(
                    row=row,
                    family_key=key,
                    new_family_id=family_id,
                    student_id=self._new_id() if key is not None else None,
                    status="error",
                )
            )
        planned = await self._planner.plan(academy_id, stored)
        now = self._clock()
        raw = csv_text.encode("utf-8") if isinstance(csv_text, str) else csv_text
        batch = ImportBatch(
            import_batch_id=self._new_id(),
            kind="families",
            status="previewed",
            file_sha256=hashlib.sha256(raw).hexdigest(),
            filename=(filename or None),
            created_by=actor_id,
            created_at=now,
            updated_at=now,
            rows=planned,
            summary=summarize(planned),
            academy_id=academy_id,
        )
        await self._batches.add(batch)
        await self._audit.record(
            actor_id=actor_id,
            action=AUDIT_PREVIEWED,
            import_batch_id=batch.import_batch_id,
            summary=batch.summary,
        )
        return batch


@dataclass(frozen=True)
class CommitFamilyImportResult:
    batch: ImportBatch
    #: True when the batch had already been committed; nothing was written.
    already_committed: bool
    #: Students inserted by THIS call.
    students_inserted: int


class CommitFamilyImport:
    def __init__(
        self,
        *,
        planner: FamilyImportPlanner,
        batches: ImportBatchRepository,
        students: ImportedStudentWriter,
        audit: ImportAuditLog,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._planner = planner
        self._batches = batches
        self._students = students
        self._audit = audit
        self._clock = clock

    async def execute(
        self, academy_id: str, *, import_batch_id: str, actor_id: str
    ) -> CommitFamilyImportResult:
        batch = _own(await self._batches.get(import_batch_id), academy_id)
        if batch is None:
            raise ImportBatchNotFound("import batch not found", import_batch_id=import_batch_id)
        if batch.status == "committed":
            return CommitFamilyImportResult(batch, already_committed=True, students_inserted=0)
        now = self._clock()
        if batch.status == "previewed" and batch.expired(now):
            raise ImportNotCommittable(
                "This preview is more than a day old. Upload the file again.", reason="expired"
            )
        claimed = await self._batches.claim_for_commit(
            import_batch_id,
            actor_id=actor_id,
            now=now,
            stale_before=now - COMMIT_CLAIM_STALE_AFTER,
        )
        if claimed is None:
            current = await self._batches.get(import_batch_id)
            if current is not None and current.status == "committed":
                return CommitFamilyImportResult(
                    current, already_committed=True, students_inserted=0
                )
            raise ImportNotCommittable(
                "This import is already being committed.", reason="in_progress"
            )
        if _own(claimed, academy_id) is None:
            raise ImportBatchNotFound("import batch not found", import_batch_id=import_batch_id)

        planned = await self._planner.plan(academy_id, claimed.rows)
        summary = summarize(planned)
        if summary.has_errors:
            await self._batches.release_claim(
                import_batch_id, rows=planned, summary=summary, now=self._clock()
            )
            raise ImportNotCommittable(
                "Some rows have errors. Fix the file and preview it again.",
                reason="has_errors",
                rows_error=summary.rows_error,
            )

        parents = _new_family_parents(planned)
        inserted = 0
        for planned_row in planned:
            if planned_row.status != "create":
                continue
            written = await self._write(planned_row, parents, claimed.import_batch_id, actor_id)
            inserted += int(written)
        committed = await self._batches.mark_committed(
            import_batch_id,
            rows=planned,
            summary=summary,
            students_created=inserted,
            now=self._clock(),
        )
        if committed is None:
            # A stale-claim resume finished the batch first.
            current = await self._batches.get(import_batch_id)
            if current is not None and current.status == "committed":
                return CommitFamilyImportResult(
                    current, already_committed=True, students_inserted=inserted
                )
            raise ImportNotCommittable(
                "This import is already being committed.", reason="in_progress"
            )
        await self._audit.record(
            actor_id=actor_id,
            action=AUDIT_COMMITTED,
            import_batch_id=import_batch_id,
            summary=summary,
            extra={"students_inserted": inserted},
        )
        return CommitFamilyImportResult(
            committed, already_committed=False, students_inserted=inserted
        )

    async def _write(
        self,
        planned: PlannedRow,
        parents: Mapping[str, _ParentDetails],
        import_batch_id: str,
        actor_id: str,
    ) -> bool:
        row: ImportRow = planned.row
        # A family this import minted is known only through the students'
        # ``parent_*`` roster fields, so they are written (the family's first
        # name, email and phone, the same on every child). A family that
        # already existed keeps the parent details it has. A resumed commit
        # finds its own minted family as "existing"; it is still ours.
        parent = parents.get(str(planned.family_id))
        return await self._students.ensure_imported(
            student_id=str(planned.student_id),
            parent_id=str(planned.family_id),
            full_name=row.student_name,
            date_of_birth=row.student_date_of_birth,
            parent_name=parent.name if parent else None,
            parent_email=parent.email if parent else None,
            parent_phone=parent.phone if parent else None,
            import_batch_id=import_batch_id,
            imported_by=actor_id,
        )


@dataclass(frozen=True)
class _ParentDetails:
    name: str
    email: str | None
    phone: str | None


def _new_family_parents(rows: Sequence[PlannedRow]) -> dict[str, _ParentDetails]:
    """Parent details per family minted by this batch, first value wins."""
    found: dict[str, _ParentDetails] = {}
    for planned in rows:
        family = planned.new_family_id
        if family is None or planned.family_id != family or planned.row.errors:
            continue
        current = found.get(family)
        row = planned.row
        if current is None:
            found[family] = _ParentDetails(row.parent_name, row.parent_email, row.parent_phone)
        else:
            found[family] = _ParentDetails(
                current.name,
                current.email or row.parent_email,
                current.phone or row.parent_phone,
            )
    return found
