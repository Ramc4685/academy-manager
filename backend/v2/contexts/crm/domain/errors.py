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


class InvalidFamilyContact(DomainError):
    """A family contact failed validation (missing name, bad email or phone,
    a switch turned on with no email to send to). ``details.field`` names the
    offending field so the form can show the error next to it."""

    code = "Crm.InvalidFamilyContact"
    status_code = 422


class FamilyContactNotFound(DomainError):
    code = "Crm.FamilyContactNotFound"
    status_code = 404


class DuplicateFamilyContactEmail(DomainError):
    """This family already has a contact with that email (the partial unique
    ``(academy_id, parent_id, email)`` index decides)."""

    code = "Crm.DuplicateFamilyContactEmail"
    status_code = 409


class TooManyFamilyContacts(DomainError):
    code = "Crm.TooManyFamilyContacts"
    status_code = 422


class InvalidFamilyDetails(DomainError):
    """A family details field failed validation (over a size cap, unknown
    preferred channel, too many tags). ``details.field`` names the field."""

    code = "Crm.InvalidFamilyDetails"
    status_code = 422


class InvalidImportFile(DomainError):
    """The uploaded CSV cannot be imported as a whole (not UTF-8, too large,
    too many rows, unknown or missing columns). Row problems are not this
    error: they are reported per row in the preview."""

    code = "Crm.InvalidImportFile"
    status_code = 422


class ImportBatchNotFound(DomainError):
    """No import batch with this id in the caller's academy."""

    code = "Crm.ImportBatchNotFound"
    status_code = 404


class ImportNotCommittable(DomainError):
    """The batch cannot be committed now. ``details.reason`` is ``has_errors``
    (fix the file and preview again), ``expired`` (the preview is over a day
    old) or ``in_progress`` (another commit holds it)."""

    code = "Crm.ImportNotCommittable"
    status_code = 409


class ImportUnavailable(DomainError):
    """The academy's family list could not be read, so duplicates cannot be
    checked; the import refuses rather than risk creating duplicates."""

    code = "Crm.ImportUnavailable"
    status_code = 503
