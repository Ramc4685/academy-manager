"""Identity domain errors."""

from __future__ import annotations

from backend.v2.shared.http.errors import DomainError


class UserNotFound(DomainError):
    code = "Identity.UserNotFound"
    status_code = 404


class UserEmailAlreadyExists(DomainError):
    code = "Identity.UserEmailAlreadyExists"
    status_code = 409


class UserEmailUpdateFailed(DomainError):
    code = "Identity.UserEmailUpdateFailed"
    status_code = 502


class UserCreateFailed(DomainError):
    code = "Identity.UserCreateFailed"
    status_code = 502


class UserInactive(DomainError):
    code = "Identity.UserInactive"
    status_code = 403


class InvalidToken(DomainError):
    code = "Identity.InvalidToken"
    status_code = 401


class LoginInviteSendFailed(DomainError):
    """Raised when the set-password invite email could not be sent."""

    code = "Identity.LoginInviteSendFailed"
    status_code = 502


class VerificationEmailThrottled(DomainError):
    """Too many verification emails were requested for one address.

    The public ``/register/parent/verification-email`` endpoint mails whatever
    address the caller's Firebase token carries. Anyone can mint a Firebase
    account for an address they do not own using the public web API key, so
    without a per-address cooldown the endpoint is a mail-bomb gun pointed at
    an arbitrary victim — and it fires from the same Resend domain our invoices
    depend on, so the reputational damage lands on billing mail. The IP rate
    limit is not enough: the attacker controls the address, not just the IP.
    """

    code = "Identity.VerificationEmailThrottled"
    status_code = 429


class MembershipNotFound(DomainError):
    """No active `academy_memberships` row for this (user, academy) pair.

    Raised by `LoadAuthClaims` when the resolved tenant has no membership
    for the authenticated user, or when the membership exists but is not
    active (invited/suspended/removed). The auth surface maps this to 403.
    """

    code = "Identity.MembershipNotFound"
    status_code = 403


class RoleRevocationFailed(DomainError):
    """A role replacement could not be written to the membership row it resolved.

    SaaS claims come from `academy_memberships`, so a replacement that does not
    land there leaves the old grant live. The write is therefore checked, and a
    resolved row that the update did not touch fails the whole operation rather
    than reporting a demotion that never took effect.
    """

    code = "Identity.RoleRevocationFailed"
    status_code = 502


class CannotRemoveLastRole(DomainError):
    """Raised when removing a role would leave the user with no roles."""

    code = "Identity.CannotRemoveLastRole"
    status_code = 409


class CoachHasFutureSessions(DomainError):
    """Raised when a coaching role is removed while future work is assigned.

    Dropping ``coach``/``assistant_coach`` only rewrote ``users.roles``; the
    sessions and occurrences naming that user kept naming them, so the roster
    rendered ``coach_name: None`` and nobody was accountable for the class
    (#785). Removal now has to be preceded by a reassignment.
    """

    code = "Identity.CoachHasFutureSessions"
    status_code = 409


class ParentHasLiveChildren(DomainError):
    """Raised when a parent account is disabled while a child is still enrolled.

    The disable cascade (#785) suspends the membership and the Firebase
    account, which is exactly the problem for a payer: the enrollments keep
    running, invoices keep being raised against them, and the only person who
    could see or pay them can no longer sign in. The academy has to withdraw
    or transfer the live enrollments first.
    """

    code = "Identity.ParentHasLiveChildren"
    status_code = 409


class MagicLinkInvalid(DomainError):
    """The one-time magic-link token is unknown, already used, or tenant-mismatched.

    Deliberately generic (no distinction between "never existed", "already
    consumed", and "belongs to another tenant") so a caller cannot probe which
    tokens exist. The consume surface maps this to 401.
    """

    code = "Identity.MagicLinkInvalid"
    status_code = 401


class StudentNotFound(DomainError):
    """No student roster record for the given id in the resolved academy."""

    code = "Identity.StudentNotFound"
    status_code = 404


class StudentAlreadyLinked(DomainError):
    """The student already has a login (`Student.student_user_id` is set).

    Enforces "one user per student per academy" (UIM12) — a second invite
    attempt is rejected rather than silently re-linking to a new user.
    """

    code = "Identity.StudentAlreadyLinked"
    status_code = 409


class UserAlreadyLinkedToStudent(DomainError):
    """This email/user is already another student's login (UIM12).

    The other half of "one user per student per academy". Without it, two
    siblings invited with the same family email would share one user, and
    `/student/*` would resolve to whichever student doc Mongo returned
    first — each sibling seeing the other's schedule and progress.
    """

    code = "Identity.UserAlreadyLinkedToStudent"
    status_code = 409


class UserOutsideAcademy(DomainError):
    """The email belongs to an existing user who is not a member of this academy.

    Refusing here stops an admin of academy A from attaching a stranger's
    existing account (a real person in academy B, with a password they
    already know) to one of A's students — which would hand that stranger
    an immediate, verified login into the student's data (UIM12 review P2).
    """

    code = "Identity.UserOutsideAcademy"
    status_code = 409


class MagicLinkExpired(DomainError):
    """The magic-link token was valid but has passed its TTL.

    Distinct from ``MagicLinkInvalid`` so the frontend can steer the parent to
    "sign in and use Forgot password" instead of showing a generic error. The
    consume surface maps this to 410 Gone.
    """

    code = "Identity.MagicLinkExpired"
    status_code = 410


class InvalidPublicPageSettings(DomainError):
    """A public-page settings update failed validation (unknown key, wrong
    type, unknown price period, a non-http(s) privacy link)."""

    code = "Identity.InvalidPublicPageSettings"
    status_code = 422
