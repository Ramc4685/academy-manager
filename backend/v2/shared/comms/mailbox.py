"""The inbox an email address delivers to, shared by the CRM inquiry throttle
and the prospect opt-out store so both treat aliases of one inbox as one."""

from __future__ import annotations

_GMAIL_DOMAINS: frozenset[str] = frozenset({"gmail.com", "googlemail.com"})


def canonical_mailbox(value: str | None) -> str | None:
    """Lower-cased, any ``+tag`` dropped on every domain, and for Gmail the dots
    dropped and googlemail.com read as gmail.com, so ``J.amie+x@GoogleMail.com``
    and ``jamie@gmail.com`` are one inbox. For caps and opt-outs only: never
    stored on a contact or shown, and never used as a send address."""
    email = " ".join((value or "").split()).lower()
    if not email or "@" not in email:
        return email or None
    local, _, domain = email.rpartition("@")
    local = local.split("+", 1)[0]
    if domain in _GMAIL_DOMAINS:
        local, domain = local.replace(".", ""), "gmail.com"
    return f"{local}@{domain}"
