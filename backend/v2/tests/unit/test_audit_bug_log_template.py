"""Static checks for the production-scale local audit bug log template."""

from __future__ import annotations

from pathlib import Path

BUG_LOG = (
    Path(__file__).resolve().parents[4]
    / "docs"
    / "qa"
    / "2026-06-28-production-scale-local-bug-log.md"
)


def test_bug_log_template_contains_required_reproduction_evidence_fields() -> None:
    text = BUG_LOG.read_text()

    required_fields = [
        "Bug ID",
        "Status",
        "Persona",
        "Route",
        "Workflow",
        "Seeded Account",
        "Reproduction Steps",
        "Expected Result",
        "Actual Result",
        "Evidence",
        "Screenshot",
        "Trace",
        "Video",
        "Backend Log Excerpt",
        "Root Cause",
        "Shared Cause Review",
        "Fix",
        "Regression Test",
        "Rerun Result",
        "BUG-CANDIDATE",
        "summarize_local_auth_audit.py",
    ]

    for field in required_fields:
        assert field in text


def test_bug_log_tracks_promoted_findings_and_verified_rerun_state() -> None:
    text = BUG_LOG.read_text()

    assert "Known bugs: 4" in text
    assert "verified in full local real-user rerun" in text
    for bug_id in ("BUG-001", "BUG-002", "BUG-003", "BUG-004"):
        assert f"### {bug_id}:" in text
    assert text.count("Status: verified") == 4
    assert text.count("72 passed") >= 4
