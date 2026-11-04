"""Per-academy invoice-number prefix rules (Settings overhaul Phase 1 PR 2).

An invoice number is ``{prefix}-{YYYY}-{MM}-{seq:04d}`` (``ledger.format_invoice_number``).
The prefix used to be a hardcoded ``BLNO`` default, so every new academy would
have issued BLNO-numbered invoices. It is now set per academy by the platform:
derived from the academy slug when the academy is created, editable by a
platform admin until the academy's first numbered invoice, and unique across
academies (a parent or accountant must be able to tell whose invoice it is).

Pure rules only. No infra imports.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterator

from backend.v2.contexts.billing.domain.errors import InvalidInvoicePrefix

INVOICE_PREFIX_MIN_LENGTH = 2
INVOICE_PREFIX_MAX_LENGTH = 6

#: Uppercase letters and digits, 2-6 characters, starting with a letter. The
#: leading letter keeps the prefix from reading as part of the date that
#: follows it (``2026-2026-09-0001``). BLNO's "BLNO" satisfies it.
_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,5}$")

#: Used only when a slug has nothing usable in it (e.g. "x" or "123").
FALLBACK_INVOICE_PREFIX = "ACAD"


def is_valid_invoice_prefix(value: object) -> bool:
    return isinstance(value, str) and bool(_PATTERN.match(value))


def normalize_invoice_prefix(raw: str) -> str:
    """Trim and uppercase ``raw``; raise ``InvalidInvoicePrefix`` if it breaks the rules."""
    value = (raw or "").strip().upper()
    if not is_valid_invoice_prefix(value):
        raise InvalidInvoicePrefix(
            "invoice prefix must be 2-6 uppercase letters or digits, starting with a letter",
            invoice_prefix=raw,
        )
    return value


def _base_from_slug(slug: str) -> str:
    words = [w for w in re.split(r"[^A-Z0-9]+", (slug or "").upper()) if w]
    # The first word ("ace" of "ace-badminton") is the academy's short name;
    # when it is too short to be a prefix, fall back to the whole slug.
    for candidate in (words[0] if words else "", "".join(words)):
        candidate = candidate.lstrip("0123456789")[:INVOICE_PREFIX_MAX_LENGTH]
        if len(candidate) >= INVOICE_PREFIX_MIN_LENGTH:
            return candidate
    return FALLBACK_INVOICE_PREFIX


def invoice_prefix_candidates(slug: str) -> Iterator[str]:
    """The prefixes to try for ``slug``, in order: ``ACE``, ``ACE2`` ... ``ACE99``.

    Deterministic, every one valid, no repeats. A numbered candidate trims the
    base so it still fits the length cap (``SHUTTL`` -> ``SHUTT2`` -> ``SHUT10``).
    """
    base = _base_from_slug(slug)
    seen = {base}
    yield base
    for n in range(2, 100):
        suffix = str(n)
        candidate = base[: INVOICE_PREFIX_MAX_LENGTH - len(suffix)] + suffix
        if candidate not in seen and is_valid_invoice_prefix(candidate):
            seen.add(candidate)
            yield candidate


def derive_invoice_prefix(slug: str, *, taken: Collection[str]) -> str:
    """The first candidate for ``slug`` that no other academy holds."""
    for candidate in invoice_prefix_candidates(slug):
        if candidate not in taken:
            return candidate
    raise InvalidInvoicePrefix("no free invoice prefix for slug", slug=slug)
