"""CRM domain errors."""

from __future__ import annotations

from backend.v2.shared.http.errors import DomainError


class InvalidContact(DomainError):
    """The create-contact input failed server-side validation (missing name,
    no email and no phone, over a size cap, unknown source or stage)."""

    code = "Crm.InvalidContact"
    status_code = 422


class InvalidFamilyNote(DomainError):
    """A family note failed validation (empty body, over the size cap)."""

    code = "Crm.InvalidFamilyNote"
    status_code = 422


class InvalidFollowUp(DomainError):
    """A follow-up failed validation (empty title, bad date, unknown status,
    an assignee who is not staff of this academy)."""

    code = "Crm.InvalidFollowUp"
    status_code = 422


class FamilyNotFound(DomainError):
    """The id is not a family of the caller's academy (or no such family)."""

    code = "Crm.FamilyNotFound"
    status_code = 404


class FamilyNoteNotFound(DomainError):
    code = "Crm.FamilyNoteNotFound"
    status_code = 404


class FamilyFollowUpNotFound(DomainError):
    code = "Crm.FamilyFollowUpNotFound"
    status_code = 404


class NoteEditForbidden(DomainError):
    """Only the note's author or an academy owner may change or delete it."""

    code = "Crm.NoteEditForbidden"
    status_code = 403


class DuplicateCrmRecordId(DomainError):
    """A note or follow-up id already exists in this academy (unique index)."""

    code = "Crm.DuplicateRecordId"
    status_code = 409
