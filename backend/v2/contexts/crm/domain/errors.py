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


class ContactNotFound(DomainError):
    """No ``crm_contacts`` row with this id in the caller's academy."""

    code = "Crm.ContactNotFound"
    status_code = 404


class PipelineMoveNotAllowed(DomainError):
    """A Pipeline board move the stage-skip guard refuses. ``details.reason``
    is ``stage_skip``, ``needs_system_write``, ``contact_enrolled``,
    ``unknown_column`` or ``changed`` (the card moved while saving)."""

    code = "Crm.PipelineMoveNotAllowed"
    status_code = 409


class InvalidContactLog(DomainError):
    """A logged contact failed validation (unknown channel or status, a note
    over the size cap). ``details.field`` names the offending field."""

    code = "Crm.InvalidContactLog"
    status_code = 422


class ContactLogNotFound(DomainError):
    """No logged contact with this id on this family of the caller's academy."""

    code = "Crm.ContactLogNotFound"
    status_code = 404


class ContactLogEditForbidden(DomainError):
    """Only the staff member who logged the contact, or an academy owner, may
    complete it."""

    code = "Crm.ContactLogEditForbidden"
    status_code = 403
