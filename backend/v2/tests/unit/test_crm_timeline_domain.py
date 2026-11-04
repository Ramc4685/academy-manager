"""The unified family timeline's pure rules (People CRM spec §5): order, dedupe
by enrollment inside ten minutes (never money), the cap, cursor paging and the
front-desk money redaction (#553)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.crm.domain.timeline import (
    AUDIT_ACTION_ALLOWLIST,
    TimelineCursor,
    TimelineEntry,
    as_utc,
    dedupe_entries,
    merge_timeline,
    paginate,
    redact_money,
)

T0 = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)


def _e(entry_id: str, minutes: int, kind: str = "lifecycle", **kw: object) -> TimelineEntry:
    return TimelineEntry(
        entry_id=entry_id,
        at=T0 + timedelta(minutes=minutes),
        kind=kind,  # type: ignore[arg-type]
        code=kw.pop("code", f"code-{entry_id}"),  # type: ignore[arg-type]
        summary=kw.pop("summary", f"summary {entry_id}"),  # type: ignore[arg-type]
        source="test",
        **kw,  # type: ignore[arg-type]
    )


def test_naive_times_are_utc() -> None:
    assert as_utc(datetime(2026, 9, 1, 15, 0)) == T0


def test_merge_sorts_newest_first_with_id_tiebreak_and_drops_repeated_ids() -> None:
    merged = merge_timeline(
        [
            [_e("b", 5), _e("a", 5), _e("old", -60)],
            [_e("new", 90), _e("a", 5)],
        ]
    )
    assert [e.entry_id for e in merged] == ["new", "a", "b", "old"]


def test_merge_caps_the_feed() -> None:
    merged = merge_timeline([[_e(f"e{i:03d}", i * 20) for i in range(250)]], cap=200)
    assert len(merged) == 200
    assert merged[0].entry_id == "e249"


def test_one_approved_pause_collapses_into_the_lifecycle_entry() -> None:
    request = _e("req", 0, "requests", code="request:pause_approved", enrollment_id="enr-1")
    event = _e("ev", 2, "lifecycle", code="enrollment:paused", enrollment_id="enr-1")
    audit = _e("aud", 9, "admin", code="audit:x", enrollment_id="enr-1")
    later = _e("later", 30, "lifecycle", code="enrollment:resumed", enrollment_id="enr-1")
    other = _e("other", 1, "lifecycle", code="enrollment:paused", enrollment_id="enr-2")
    out = {e.entry_id: e for e in dedupe_entries([request, event, audit, later, other])}
    assert set(out) == {"ev", "later", "other"}
    assert out["ev"].collapsed_codes == ("request:pause_approved", "audit:x")


def test_the_window_is_measured_from_the_first_entry_so_it_never_chains() -> None:
    chain = [_e(f"c{i}", i * 6, enrollment_id="enr-1") for i in range(4)]  # 0, 6, 12, 18
    kept = sorted(e.entry_id for e in dedupe_entries(chain))
    assert kept == ["c1", "c3"]  # the newest of each cluster is kept


def test_money_entries_never_collapse() -> None:
    pay = _e("pay", 1, "money", enrollment_id="enr-1", amount_cents=6000)
    ev = _e("ev", 0, "lifecycle", enrollment_id="enr-1")
    assert {e.entry_id for e in dedupe_entries([pay, ev])} == {"pay", "ev"}


def test_cursor_round_trips_and_rejects_garbage() -> None:
    cursor = TimelineCursor(at=T0, entry_id="audit:1|x")
    assert TimelineCursor.decode(cursor.encode()) == cursor
    for bad in ("", "!!!", "bm8tcGlwZQ", "MjAyNi0wOS0wMXw"):
        with pytest.raises(ValueError):
            TimelineCursor.decode(bad)


def test_pages_walk_the_feed_without_gaps_or_repeats() -> None:
    feed = merge_timeline([[_e(f"e{i}", i // 2) for i in range(7)]])
    seen: list[str] = []
    cursor = None
    for _ in range(5):
        page, cursor = paginate(feed, before=cursor, limit=3)
        seen.extend(e.entry_id for e in page)
        if cursor is None:
            break
    assert seen == [e.entry_id for e in feed]
    assert len(seen) == 7


def test_front_desk_sees_money_rows_without_amounts() -> None:
    payment = _e(
        "pay",
        0,
        "money",
        code="payment_received",
        summary="$60 received · Visa ••4242 · $10 refunded",
        amount_cents=6000,
        refunded_cents=1000,
    )
    redacted = redact_money(payment)
    assert redacted.summary == "Payment received · Visa ••4242"
    assert redacted.amount_cents is None and redacted.refunded_cents is None

    invoice = _e(
        "inv", 0, "money", code="invoice_generated", summary="Sep 2026 invoice generated · $70"
    )
    assert redact_money(invoice).summary == "Sep 2026 invoice generated"
    declined = _e(
        "dec", 0, "money", code="charge_failed", summary="Card declined · $70 · attempt 2"
    )
    assert redact_money(declined).summary == "Card declined · attempt 2"
    refund = _e(
        "ref",
        0,
        "admin",
        code="audit:refund_issued",
        summary="Refund issued · $5",
        amount_cents=500,
    )
    assert redact_money(refund).summary == "Refund issued"
    assert redact_money(refund).amount_cents is None

    plain = _e("life", 0, "lifecycle", summary="Kid Alpha paused")
    assert redact_money(plain) is plain


def test_the_audit_allowlist_never_shows_logins() -> None:
    assert "user_logged_in" not in AUDIT_ACTION_ALLOWLIST
    assert "student.parent_changed" in AUDIT_ACTION_ALLOWLIST
