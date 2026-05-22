from __future__ import annotations

from pydantic import BaseModel


class ReportsKpiResponse(BaseModel):
    active_students: int
    attendance_rate_30d: float
    dues_collected_mtd_cents: int
    pending_waivers: int


def test_kpi_response_shape():
    r = ReportsKpiResponse(
        active_students=10,
        attendance_rate_30d=0.85,
        dues_collected_mtd_cents=120000,
        pending_waivers=3,
    )
    assert r.active_students == 10
    assert r.attendance_rate_30d == 0.85
    assert r.dues_collected_mtd_cents == 120000
    assert r.pending_waivers == 3


def test_kpi_response_defaults_to_zero_floats():
    r = ReportsKpiResponse(
        active_students=0,
        attendance_rate_30d=0.0,
        dues_collected_mtd_cents=0,
        pending_waivers=0,
    )
    assert r.attendance_rate_30d == 0.0
