"""Import batches: the stored plan behind a CSV preview and its commit (roadmap L8a).

A preview parses the file, plans every row (create, skip, error) and stores
the plan as one ``import_batches`` document. The commit takes only the
batch id, re-plans the stored rows against the academy's current data and
writes the rows planned ``create``. Ids for new families and new students
are minted once, at preview, and stored on the batch, so a commit that runs
twice (a retry, or a resume after a crash) writes the same ids and inserts
nothing the second time.

Pure data: no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal

from backend.v2.contexts.crm.domain.family_import import ImportRow, RowIssue

ImportKind = Literal["families"]
ImportBatchStatus = Literal["previewed", "committing", "committed"]
RowStatus = Literal["create", "skip", "error"]
FamilyAction = Literal["new", "existing"]

#: A preview can be committed for this long after it was made.
PREVIEW_VALID_FOR: Final = timedelta(hours=24)
#: A commit that has held the batch this long without finishing is treated
#: as crashed, and the next commit resumes it.
COMMIT_CLAIM_STALE_AFTER: Final = timedelta(minutes=5)


@dataclass(frozen=True)
class PlannedRow:
    #: The parsed row, with its parse and in-file grouping problems.
    row: ImportRow
    #: The row's family in the file (None when the row has a parse error).
    family_key: str | None
    #: Minted at preview; used when the row's family is new.
    new_family_id: str | None
    #: Minted at preview; the student this row creates.
    student_id: str | None
    status: RowStatus
    family_action: FamilyAction | None = None
    #: The family the child goes into: an existing family id or ``new_family_id``.
    family_id: str | None = None
    #: The existing family's display name (None for a new family).
    family_name: str | None = None
    #: Problems found against the academy's data (duplicate checks).
    plan_errors: tuple[RowIssue, ...] = ()
    plan_warnings: tuple[str, ...] = ()

    @property
    def errors(self) -> tuple[RowIssue, ...]:
        return self.row.errors + self.plan_errors

    @property
    def warnings(self) -> tuple[str, ...]:
        return self.row.warnings + self.plan_warnings


@dataclass(frozen=True)
class ImportSummary:
    rows_total: int
    rows_create: int
    rows_skip: int
    rows_error: int
    families_new: int
    families_existing: int

    @property
    def has_errors(self) -> bool:
        return self.rows_error > 0


def summarize(rows: tuple[PlannedRow, ...]) -> ImportSummary:
    creating = [row for row in rows if row.status == "create"]
    return ImportSummary(
        rows_total=len(rows),
        rows_create=len(creating),
        rows_skip=sum(1 for row in rows if row.status == "skip"),
        rows_error=sum(1 for row in rows if row.status == "error"),
        families_new=len({row.family_id for row in creating if row.family_action == "new"}),
        families_existing=len(
            {
                row.family_id
                for row in rows
                if row.family_action == "existing" and row.status != "error"
            }
        ),
    )


@dataclass(frozen=True)
class ImportBatch:
    import_batch_id: str
    kind: ImportKind
    status: ImportBatchStatus
    file_sha256: str
    filename: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime
    rows: tuple[PlannedRow, ...]
    summary: ImportSummary
    claimed_at: datetime | None = None
    committed_at: datetime | None = None
    committed_by: str | None = None
    #: Set on commit: students inserted by the commit that finished the batch.
    students_created: int | None = None
    #: The academy the batch was stored under (set by the store on read).
    #: The commit refuses a batch whose academy is not the caller's, as a
    #: guard independent of the store's own tenant scoping.
    academy_id: str | None = None

    def expired(self, now: datetime) -> bool:
        return now - self.created_at > PREVIEW_VALID_FOR
