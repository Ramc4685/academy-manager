"""Build ``wa.me`` click-to-chat deep links for admin-initiated reminders.

A reminder email lands in a parent's inbox and is easy to miss. A ``wa.me`` link
gives admins a second, higher-signal channel without the WhatsApp Business API:
the link opens WhatsApp with the message pre-filled in that parent's chat, and
the admin presses send. Nothing is sent automatically, so there is no
per-conversation cost, no Meta template approval, and no automated-sending
terms violation.

Everything here is pure so the reminder copy and the phone-normalisation rules
stay unit-testable and identical wherever a link is built.
"""

from __future__ import annotations

from urllib.parse import quote

# wa.me rejects '+', spaces and punctuation -- it wants bare international
# digits (country code first). Numbers are stored as free text, so anything we
# cannot confidently resolve to an international number yields no link at all
# rather than a link to the wrong person.
_MIN_INTERNATIONAL_DIGITS = 8
_NATIONAL_DIGITS = 10


def normalize_wa_number(raw: str | None, *, default_country_code: str = "1") -> str | None:
    """Return ``raw`` as bare international digits, or ``None`` if ambiguous.

    ``default_country_code`` is applied only to a bare national number (10
    digits, no country code and no international prefix). An explicit ``+`` or
    ``00`` prefix always wins over the default.
    """
    text = (raw or "").strip()
    if not text:
        return None

    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None

    # Explicitly international: trust the number as written.
    if text.startswith("+") or digits.startswith("00"):
        international = digits[2:] if digits.startswith("00") else digits
        return international if len(international) >= _MIN_INTERNATIONAL_DIGITS else None

    # A leading trunk '0' (UK "07911...", AU, FR, IN landline) is a positive
    # signal the number is NOT from the default country -- no country uses a
    # trunk prefix on its own international number. Applying the default here
    # would silently produce a real number belonging to a stranger, so refuse.
    if digits.startswith("0"):
        return None

    if len(digits) == _NATIONAL_DIGITS:
        return f"{default_country_code}{digits}"

    # Already carries the default country code (e.g. US "15550100100").
    if digits.startswith(default_country_code) and (
        len(digits) == len(default_country_code) + _NATIONAL_DIGITS
    ):
        return digits

    # Too short to dial, or a length we cannot attribute to a country code
    # without guessing. Guessing here would message a stranger.
    return None


def dues_reminder_text(
    *,
    display_name: str | None,
    total_due_cents: int,
    pending_count: int,
    currency: str,
    pay_url: str | None,
    academy_name: str | None = None,
) -> str:
    """Plain-text twin of the dues reminder email body.

    Mirrors ``DuesReminderEmailAdapter.send_reminder`` so a parent gets the same
    facts and the same call to action on either channel.
    """
    name = (display_name or "").strip() or "there"
    amount = f"{currency.upper()} {total_due_cents / 100:.2f}"
    invoice_word = "invoice" if pending_count == 1 else "invoices"
    sender = (academy_name or "").strip()

    intro = (
        f"This is a payment reminder from {sender}." if sender else "This is a payment reminder."
    )
    call_to_action = (
        f"You can pay here: {pay_url}" if pay_url else "Please log in to the parent portal to pay."
    )
    return "\n\n".join(
        [
            f"Hi {name},",
            f"{intro} You have {pending_count} open {invoice_word} totaling {amount}.",
            call_to_action,
        ]
    )


def whatsapp_deep_link(
    *,
    phone: str | None,
    message: str,
    default_country_code: str = "1",
) -> str | None:
    """Return a ``wa.me`` link that opens a pre-filled chat, or ``None``.

    ``None`` means the stored phone could not be resolved to an international
    number; callers should render no link rather than a broken one.
    """
    number = normalize_wa_number(phone, default_country_code=default_country_code)
    if not number:
        return None
    return f"https://wa.me/{number}?text={quote(message)}"
