"""Per-academy invoice prefix (Settings overhaul Phase 1 PR 2).

Invoice numbers used to default to a hardcoded ``BLNO`` prefix, so every new
academy would have issued BLNO-numbered invoices. The prefix is now stored per
academy, set by the platform, derived from the academy slug at creation, and
locked once the academy has a numbered invoice.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.invoice_numbering import (
    mint_invoice_number,
)
from backend.v2.contexts.billing.application.use_cases.invoice_prefix import (
    AssignInvoicePrefix,
    GetInvoicePrefix,
    SetInvoicePrefix,
    SetInvoicePrefixCommand,
)
from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry
from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
from backend.v2.contexts.billing.domain.errors import (
    InvalidInvoicePrefix,
    InvoicePrefixAcademyNotFound,
    InvoicePrefixLocked,
    InvoicePrefixTaken,
)
from backend.v2.contexts.billing.domain.invoice_prefix import (
    derive_invoice_prefix,
    invoice_prefix_candidates,
    is_valid_invoice_prefix,
    normalize_invoice_prefix,
)
from backend.v2.shared.tenancy import current_academy_id

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)

# ---------------------------------------------------------------------------
# Domain rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["BLNO", "ACE", "AB", "A1", "SHUTTL", "Z9Z9Z9"])
def test_valid_prefixes(value: str) -> None:
    assert is_valid_invoice_prefix(value)
    assert normalize_invoice_prefix(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "A",  # too short
        "TOOLONG",  # 7 characters
        "1ACE",  # leading digit reads as part of the date: 1ACE-2026-09-0001
        "AC-E",
        "AC E",
        "ÅCE",
        "BL_NO",
    ],
)
def test_invalid_prefixes_are_rejected(value: str) -> None:
    assert not is_valid_invoice_prefix(value)
    with pytest.raises(InvalidInvoicePrefix):
        normalize_invoice_prefix(value)


def test_normalize_trims_and_uppercases() -> None:
    assert normalize_invoice_prefix("  ace ") == "ACE"


@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        ("blno-badminton", "BLNO"),
        ("blno", "BLNO"),
        ("ace", "ACE"),
        ("ace-badminton-club", "ACE"),
        ("shuttle-stars", "SHUTTL"),  # first word, capped at 6
        ("a-team", "ATEAM"),  # first word too short: use the whole slug
        ("99-smashers", "SMASHE"),  # never starts with a digit
        ("x", "ACAD"),  # nothing usable
    ],
)
def test_derive_from_slug(slug: str, expected: str) -> None:
    assert derive_invoice_prefix(slug, taken=set()) == expected
    assert is_valid_invoice_prefix(expected)


def test_derive_skips_taken_prefixes_deterministically() -> None:
    assert derive_invoice_prefix("ace", taken={"ACE"}) == "ACE2"
    assert derive_invoice_prefix("ace", taken={"ACE", "ACE2"}) == "ACE3"
    assert derive_invoice_prefix("shuttle-stars", taken={"SHUTTL"}) == "SHUTT2"


def test_every_candidate_is_valid_and_unique() -> None:
    candidates = list(invoice_prefix_candidates("shuttle-stars"))
    assert len(candidates) == len(set(candidates)) > 50
    assert all(is_valid_invoice_prefix(c) for c in candidates)


# ---------------------------------------------------------------------------
# Fakes that mirror the real store: ONE billing_settings collection shared by
# every academy, with the global unique index on the prefix.
# ---------------------------------------------------------------------------


class _SharedSettingsStore:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}


class _SettingsRepo:
    """Tenant-scoped view over the shared store, like MongoBillingSettingsRepository."""

    def __init__(self, store: _SharedSettingsStore) -> None:
        self.store = store

    async def get(self) -> BillingSettings:
        academy_id = current_academy_id()
        return BillingSettings(academy_id=academy_id, **self.store.docs.get(academy_id, {}))

    async def upsert(self, settings: BillingSettings) -> None:  # pragma: no cover - unused
        raise AssertionError("the prefix must never go through the tenant settings write")

    async def set_application_fee_bps(self, fee_bps: int) -> None:  # pragma: no cover
        raise AssertionError("unexpected")

    async def set_invoice_number_prefix(self, prefix: str) -> None:
        academy_id = current_academy_id()
        for other_id, doc in self.store.docs.items():
            if other_id != academy_id and doc.get("invoice_number_prefix") == prefix:
                raise InvoicePrefixTaken("prefix taken", invoice_prefix=prefix)
        self.store.docs.setdefault(academy_id, {})["invoice_number_prefix"] = prefix


class _Audit:
    def __init__(self) -> None:
        self.entries: list[BillingAuditEntry] = []

    async def append(self, entry: BillingAuditEntry) -> None:
        self.entries.append(entry)


class _World:
    def __init__(self, academies: set[str], numbered: set[str] | None = None) -> None:
        self.store = _SharedSettingsStore()
        self.repo = _SettingsRepo(self.store)
        self.audit = _Audit()
        self.academies = academies
        self.numbered = numbered or set()

    async def academy_exists(self, academy_id: str) -> bool:
        return academy_id in self.academies

    async def has_numbered_invoice(self, academy_id: str) -> bool:
        return academy_id in self.numbered

    async def prefix_taken(self, prefix: str, academy_id: str) -> bool:
        return any(
            other != academy_id and doc.get("invoice_number_prefix") == prefix
            for other, doc in self.store.docs.items()
        )

    def setter(self) -> SetInvoicePrefix:
        return SetInvoicePrefix(
            settings=self.repo,
            audit=self.audit,
            academy_exists=self.academy_exists,
            has_numbered_invoice=self.has_numbered_invoice,
            prefix_taken=self.prefix_taken,
            clock=lambda: NOW,
        )

    def getter(self) -> GetInvoicePrefix:
        return GetInvoicePrefix(
            settings=self.repo,
            academy_exists=self.academy_exists,
            has_numbered_invoice=self.has_numbered_invoice,
        )


def _cmd(academy_id: str, prefix: str, reason: str | None = "go-live") -> SetInvoicePrefixCommand:
    return SetInvoicePrefixCommand(
        academy_id=academy_id, invoice_prefix=prefix, actor_id="platform-admin", reason=reason
    )


# ---------------------------------------------------------------------------
# Platform read / write
# ---------------------------------------------------------------------------


async def test_get_reports_prefix_and_lock() -> None:
    world = _World({"acad-a", "acad-b"}, numbered={"acad-a"})
    world.store.docs["acad-a"] = {"invoice_number_prefix": "BLNO"}

    a = await world.getter().execute("acad-a")
    b = await world.getter().execute("acad-b")

    assert (a.invoice_prefix, a.locked) == ("BLNO", True)
    assert (b.invoice_prefix, b.locked) == (None, False)


async def test_get_unknown_academy_is_404() -> None:
    with pytest.raises(InvoicePrefixAcademyNotFound):
        await _World(set()).getter().execute("nope")


async def test_set_writes_normalized_prefix_and_audits() -> None:
    world = _World({"acad-b"})

    result = await world.setter().execute(_cmd("acad-b", " ace "))

    assert result.invoice_prefix == "ACE"
    assert world.store.docs["acad-b"]["invoice_number_prefix"] == "ACE"
    [entry] = world.audit.entries
    assert entry.action == "invoice_prefix_changed"
    assert entry.academy_id == "acad-b"
    assert entry.actor_id == "platform-admin"
    assert entry.reason == "go-live"
    assert entry.before == {"invoice_number_prefix": None}
    assert entry.after == {"invoice_number_prefix": "ACE"}


async def test_set_same_value_is_a_no_op_without_audit() -> None:
    world = _World({"acad-b"})
    world.store.docs["acad-b"] = {"invoice_number_prefix": "ACE"}

    result = await world.setter().execute(_cmd("acad-b", "ACE"))

    assert result.invoice_prefix == "ACE"
    assert world.audit.entries == []


async def test_set_refuses_once_the_academy_has_a_numbered_invoice() -> None:
    world = _World({"acad-a"}, numbered={"acad-a"})
    world.store.docs["acad-a"] = {"invoice_number_prefix": "BLNO"}

    with pytest.raises(InvoicePrefixLocked):
        await world.setter().execute(_cmd("acad-a", "BLN2"))

    assert world.store.docs["acad-a"]["invoice_number_prefix"] == "BLNO"
    assert world.audit.entries == []


async def test_set_refuses_a_prefix_another_academy_holds() -> None:
    world = _World({"acad-a", "acad-b"})
    world.store.docs["acad-a"] = {"invoice_number_prefix": "BLNO"}

    with pytest.raises(InvoicePrefixTaken):
        await world.setter().execute(_cmd("acad-b", "blno"))

    assert "invoice_number_prefix" not in world.store.docs.get("acad-b", {})
    assert world.audit.entries == []


async def test_set_rejects_invalid_prefix_before_any_write() -> None:
    world = _World({"acad-b"})

    with pytest.raises(InvalidInvoicePrefix):
        await world.setter().execute(_cmd("acad-b", "BL-NO"))

    assert world.store.docs == {}
    assert world.audit.entries == []


async def test_set_unknown_academy_is_404() -> None:
    with pytest.raises(InvoicePrefixAcademyNotFound):
        await _World(set()).setter().execute(_cmd("nope", "ACE"))


# ---------------------------------------------------------------------------
# Assignment at academy creation
# ---------------------------------------------------------------------------


async def test_assign_derives_from_slug_and_dedupes_across_academies() -> None:
    world = _World({"acad-a", "acad-b", "acad-c"})
    assign = AssignInvoicePrefix(settings=world.repo)

    assert await assign.execute(academy_id="acad-a", slug="ace-badminton") == "ACE"
    assert await assign.execute(academy_id="acad-b", slug="ace-sports") == "ACE2"
    assert await assign.execute(academy_id="acad-c", slug="blno") == "BLNO"
    assert {d["invoice_number_prefix"] for d in world.store.docs.values()} == {
        "ACE",
        "ACE2",
        "BLNO",
    }


async def test_assign_is_idempotent_and_keeps_an_existing_prefix() -> None:
    world = _World({"acad-a"})
    world.store.docs["acad-a"] = {"invoice_number_prefix": "BLNO"}
    assign = AssignInvoicePrefix(settings=world.repo)

    assert await assign.execute(academy_id="acad-a", slug="something-else") == "BLNO"
    assert world.store.docs["acad-a"]["invoice_number_prefix"] == "BLNO"


# ---------------------------------------------------------------------------
# Minting reads the academy's prefix; no BLNO fallback
# ---------------------------------------------------------------------------


class _Counters:
    def __init__(self) -> None:
        self.seq: dict[str, int] = {}

    async def next_value(self, *, scope: str) -> int:
        self.seq[scope] = self.seq.get(scope, 0) + 1
        return self.seq[scope]


class _FixedSettings:
    def __init__(self, academy_id: str, prefix: str | None) -> None:
        self._settings = BillingSettings(academy_id=academy_id, invoice_number_prefix=prefix)

    async def get(self) -> BillingSettings:
        return self._settings


async def test_blno_invoice_numbers_are_byte_identical() -> None:
    counters = _Counters()
    counters.seq["invoice:acad_blno_badminton:202609"] = 41

    number = await mint_invoice_number(
        billing_counters=counters,
        billing_settings=_FixedSettings("acad_blno_badminton", "BLNO"),
        academy_id="acad_blno_badminton",
        period="2026-09",
    )

    assert number == "BLNO-2026-09-0042"


async def test_second_academy_mints_its_own_prefix() -> None:
    number = await mint_invoice_number(
        billing_counters=_Counters(),
        billing_settings=_FixedSettings("acad-ace", "ACE"),
        academy_id="acad-ace",
        period="2026-10",
    )

    assert number == "ACE-2026-10-0001"


async def test_missing_prefix_mints_nothing_burns_no_counter_and_logs_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    counters = _Counters()

    with caplog.at_level(logging.ERROR):
        number = await mint_invoice_number(
            billing_counters=counters,
            billing_settings=_FixedSettings("acad-new", None),
            academy_id="acad-new",
            period="2026-10",
        )

    assert number is None
    assert counters.seq == {}
    assert any(
        r.levelno == logging.ERROR and "invoice_prefix_not_configured" in r.getMessage()
        for r in caplog.records
    )
