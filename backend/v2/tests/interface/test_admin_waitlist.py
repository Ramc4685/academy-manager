"""Admin waitlist BFF — happy + wrong-persona 404."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry
from backend.v2.interfaces.admin.waitlist_routes import _normalize_waitlist_entries


def _add(seed, waitlist_id: str, joined_at: datetime, status: str = "waiting"):
    seed["waitlist"].entries[waitlist_id] = WaitlistEntry(
        waitlist_id=waitlist_id,
        academy_id="acad",
        session_id="sess-1",
        student_id=f"st-{waitlist_id}",
        parent_id=f"p-{waitlist_id}",
        joined_at=joined_at,
        status=status,  # type: ignore[arg-type]
    )


def test_list_waitlist_returns_entries(admin_client):
    _add(admin_client.seed, "w1", datetime(2026, 5, 16, 8, 0, tzinfo=UTC))
    _add(admin_client.seed, "w2", datetime(2026, 5, 16, 9, 0, tzinfo=UTC))
    r = admin_client.get("/api/v2/admin/sessions/sess-1/waitlist")
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {e["waitlist_id"] for e in body["entries"]}
    assert ids == {"w1", "w2"}


def test_list_global_waitlist_groups_waiting_entries(admin_client):
    _add(admin_client.seed, "w1", datetime(2026, 5, 16, 8, 0, tzinfo=UTC))
    _add(admin_client.seed, "w2", datetime(2026, 5, 16, 9, 0, tzinfo=UTC))

    r = admin_client.get("/api/v2/admin/waitlist")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_waitlisted"] == 2
    assert body["sessions"][0]["session_id"] == "sess-1"
    assert [entry["waitlist_id"] for entry in body["sessions"][0]["entries"]] == [
        "w1",
        "w2",
    ]


def test_normalize_waitlist_recomputes_positions_after_filtering():
    joined_at = datetime(2026, 5, 16, 8, 0, tzinfo=UTC)

    rows = _normalize_waitlist_entries(
        [
            {
                "waitlist_id": "promoted",
                "session_id": "sess-1",
                "student_id": "st-promoted",
                "parent_id": "p-promoted",
                "joined_at": joined_at,
                "status": "promoted",
                "position": 1,
            },
            {
                "waitlist_id": "waiting",
                "session_id": "sess-1",
                "student_id": "st-waiting",
                "parent_id": "p-waiting",
                "joined_at": joined_at,
                "status": "waiting",
                "position": 2,
            },
        ]
    )

    assert [row.waitlist_id for row in rows] == ["waiting"]
    assert [row.position for row in rows] == [1]


def test_normalize_waitlist_carries_the_parent_name():
    """#860: the waitlist row printed a raw ``parent_id``. The read now joins
    the parent's name, so the entry DTO has to carry it through — an unknown
    field would be silently dropped by Pydantic and the UI would be back to
    the id."""
    rows = _normalize_waitlist_entries(
        [
            {
                "waitlist_id": "w1",
                "session_id": "sess-1",
                "student_id": "st-1",
                "parent_id": "68b0f2c1a0b1c2d3e4f50011",
                "parent_name": "Amit Rao",
                "joined_at": datetime(2026, 5, 16, 8, 0, tzinfo=UTC),
                "status": "waiting",
            }
        ]
    )

    assert [row.parent_name for row in rows] == ["Amit Rao"]


def test_list_waitlist_wrong_persona_404(coach_on_admin_client):
    r = coach_on_admin_client.get("/api/v2/admin/sessions/sess-1/waitlist")
    assert r.status_code == 404


def test_promote_picks_oldest_fifo(admin_client):
    older = datetime(2026, 5, 16, 8, 0, tzinfo=UTC)
    newer = datetime(2026, 5, 16, 9, 0, tzinfo=UTC)
    _add(admin_client.seed, "older", older)
    _add(admin_client.seed, "newer", newer)
    r = admin_client.post("/api/v2/admin/sessions/sess-1/waitlist/promote")
    assert r.status_code == 200, r.text
    assert r.json()["promoted_waitlist_id"] == "older"
    # #828: FIFO still picks the same entry — it is now OFFERED the seat for
    # three days rather than seated on the spot.
    assert admin_client.seed["waitlist"].entries["older"].status == "offered"
    assert admin_client.seed["waitlist"].entries["older"].offer_expires_at is not None


def test_promote_holds_the_seat_for_the_oldest_entry_without_enrolling(admin_client):
    """#828: "Promote" now opens a three-day offer. Nobody joins the roster
    until the family confirms — which is the whole point: the old behaviour
    enrolled (and invoiced) families who had long since moved on."""
    _add(admin_client.seed, "older", datetime(2026, 5, 16, 8, 0, tzinfo=UTC))
    _add(admin_client.seed, "newer", datetime(2026, 5, 16, 9, 0, tzinfo=UTC))

    r = admin_client.post("/api/v2/admin/sessions/sess-1/waitlist/promote")

    assert r.status_code == 200, r.text
    assert list(admin_client.seed["enrollments"].rows.values()) == []

    roster = admin_client.get("/api/v2/admin/sessions/sess-1/enrollments").json()
    assert roster["enrollments"] == []

    assert admin_client.seed["waitlist"].entries["older"].status == "offered"
    assert admin_client.seed["waitlist"].entries["newer"].status == "waiting"


def test_promote_resumes_existing_paused_enrollment_without_duplicate(admin_client):
    admin_client.seed["enrollments"].rows["enr-paused"] = Enrollment(
        enrollment_id="enr-paused",
        academy_id="acad",
        session_id="sess-1",
        student_id="st-older",
        status="paused",
    )
    _add(admin_client.seed, "older", datetime(2026, 5, 16, 8, 0, tzinfo=UTC))

    r = admin_client.post("/api/v2/admin/sessions/sess-1/waitlist/promote")

    assert r.status_code == 200, r.text
    enrollments = list(admin_client.seed["enrollments"].rows.values())
    assert len(enrollments) == 1
    assert enrollments[0].enrollment_id == "enr-paused"
    assert enrollments[0].status == "active"


def test_promote_empty_waitlist_returns_null(admin_client):
    r = admin_client.post("/api/v2/admin/sessions/sess-1/waitlist/promote")
    assert r.status_code == 200
    assert r.json()["promoted_waitlist_id"] is None


def test_skip_marks_status(admin_client):
    _add(admin_client.seed, "w1", datetime(2026, 5, 16, 8, 0, tzinfo=UTC))
    r = admin_client.post("/api/v2/admin/waitlist/w1/skip")
    assert r.status_code == 204
    assert admin_client.seed["waitlist"].entries["w1"].status == "skipped"


def test_remove_marks_status(admin_client):
    _add(admin_client.seed, "w1", datetime(2026, 5, 16, 8, 0, tzinfo=UTC))
    r = admin_client.delete("/api/v2/admin/waitlist/w1")
    assert r.status_code == 204
    assert admin_client.seed["waitlist"].entries["w1"].status == "removed"


def test_promote_wrong_persona_404(parent_on_admin_client):
    r = parent_on_admin_client.post("/api/v2/admin/sessions/sess-1/waitlist/promote")
    assert r.status_code == 404


# --- X2: offered rows are visible, and withdrawing one frees its seat -------


def _offer(seed, waitlist_id: str, expires_at: datetime) -> None:
    _add(seed, waitlist_id, datetime(2026, 5, 16, 7, 0, tzinfo=UTC), status="offered")
    seed["waitlist"].entries[waitlist_id] = (
        seed["waitlist"].entries[waitlist_id].model_copy(update={"offer_expires_at": expires_at})
    )


def test_offered_rows_are_listed_with_their_deadline_and_no_position(admin_client):
    """X2: the normalizer kept only `waiting`, so a seat held for a family
    vanished from every admin view."""
    expires = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)
    _offer(admin_client.seed, "offered-1", expires)
    _add(admin_client.seed, "w1", datetime(2026, 5, 16, 8, 0, tzinfo=UTC))

    body = admin_client.get("/api/v2/admin/sessions/sess-1/waitlist").json()

    rows = {e["waitlist_id"]: e for e in body["entries"]}
    assert rows["offered-1"]["status"] == "offered"
    assert rows["offered-1"]["position"] == 0
    assert rows["offered-1"]["offer_expires_at"].startswith("2026-05-19T12:00")
    assert rows["w1"]["position"] == 1

    glob = admin_client.get("/api/v2/admin/waitlist").json()
    assert glob["total_waitlisted"] == 1
    assert glob["total_offered"] == 1
    assert glob["sessions"][0]["offered_count"] == 1


def test_remove_on_an_offer_releases_its_seat_and_offers_it_onward(admin_client):
    seed = admin_client.seed
    seed["sessions"].reserved["sess-1"] = seed["sessions"].sessions["sess-1"].capacity
    _offer(seed, "offered-1", datetime(2026, 5, 19, 12, 0, tzinfo=UTC))
    _add(seed, "next", datetime(2026, 5, 16, 9, 0, tzinfo=UTC))
    held = seed["sessions"].reserved["sess-1"]

    r = admin_client.delete("/api/v2/admin/waitlist/offered-1")

    assert r.status_code == 204, r.text
    assert seed["waitlist"].entries["offered-1"].status == "removed"
    # Released and immediately re-held for the next family: net zero, and
    # the next family now has the offer.
    assert seed["sessions"].reserved["sess-1"] == held
    assert seed["waitlist"].entries["next"].status == "offered"


def test_skip_on_a_waiting_row_is_still_a_plain_status_write(admin_client):
    seed = admin_client.seed
    _add(seed, "w1", datetime(2026, 5, 16, 8, 0, tzinfo=UTC))
    before = dict(seed["sessions"].reserved)

    assert admin_client.post("/api/v2/admin/waitlist/w1/skip").status_code == 204
    assert seed["waitlist"].entries["w1"].status == "skipped"
    assert seed["sessions"].reserved == before


def test_a_seatless_offer_is_flagged_for_staff(admin_client):
    """X2: an offer made while the class was full of holds holds no seat; the
    row says so, because confirming it will reclaim a held family's seat."""
    _offer(admin_client.seed, "seatless", datetime(2026, 5, 19, 12, 0, tzinfo=UTC))
    entries = admin_client.seed["waitlist"].entries
    entries["seatless"] = entries["seatless"].model_copy(update={"offer_holds_seat": False})

    [row] = admin_client.get("/api/v2/admin/sessions/sess-1/waitlist").json()["entries"]

    assert row["offer_holds_seat"] is False
