"""Static checks for the local SaaS staging helper's scale command."""

from __future__ import annotations

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "dev" / "saas_staging.sh"


def test_saas_staging_exposes_blno_scale_command() -> None:
    text = SCRIPT.read_text()

    assert "scripts/dev/saas_staging.sh scale" in text
    assert "scripts/dev/saas_staging.sh scale --apply" in text
    assert "SCALE_SCRIPT=" in text
    assert "cmd_scale()" in text
    assert "scale)       cmd_scale" in text
    assert "--cleanup" in text


def test_saas_staging_exposes_scale_safety_command() -> None:
    text = SCRIPT.read_text()

    assert "scripts/dev/saas_staging.sh scale-safety" in text
    assert "SCALE_SAFETY_SCRIPT=" in text
    assert "cmd_scale_safety()" in text
    assert "scale-safety) cmd_scale_safety" in text


def test_saas_staging_scale_command_is_dry_run_unless_apply_is_passed() -> None:
    text = SCRIPT.read_text()

    assert '"${VENV_PYTHON}" "${SCALE_SCRIPT}" "$@"' in text
    assert '"${VENV_PYTHON}" "${SCALE_SCRIPT}" --apply "$@"' not in text


def test_saas_staging_host_helpers_use_compose_mongo_url() -> None:
    text = SCRIPT.read_text()

    assert "compose_mongo_url()" in text
    assert (
        'SAAS_STAGING_MONGO_URL="$(compose_mongo_url)" "${VENV_PYTHON}" "${SEED_SCRIPT}" "$@"'
        in text
    )
    assert (
        'SAAS_STAGING_MONGO_URL="$(compose_mongo_url)" "${VENV_PYTHON}" "${BLNO_SEED_SCRIPT}" "$@"'
        in text
    )
    assert 'MONGO_URL="$(compose_mongo_url)" "${VENV_PYTHON}" "${SCALE_SCRIPT}" "$@"' in text
    assert (
        'MONGO_URL="$(compose_mongo_url)" "${VENV_PYTHON}" "${LOCAL_AUTH_ENV_SCRIPT}" "$@"' in text
    )
    assert (
        'MONGO_URL="$(compose_mongo_url)" "${VENV_PYTHON}" "${LOCAL_AUTH_READINESS_SCRIPT}" "$@"'
        in text
    )
    assert (
        "printf '    Mongo:                 %s/academy_manager_saas_staging\\n' \"$(compose_mongo_url)\""
        in text
    )


def test_saas_staging_exposes_local_auth_env_command() -> None:
    text = SCRIPT.read_text()

    assert "scripts/dev/saas_staging.sh local-auth-env" in text
    assert "LOCAL_AUTH_ENV_SCRIPT=" in text
    assert "cmd_local_auth_env()" in text
    assert "local-auth-env) cmd_local_auth_env" in text


def test_saas_staging_exposes_audit_readiness_command() -> None:
    text = SCRIPT.read_text()

    assert "scripts/dev/saas_staging.sh audit-readiness" in text
    assert "LOCAL_AUTH_READINESS_SCRIPT=" in text
    assert "cmd_audit_readiness()" in text
    assert "audit-readiness) cmd_audit_readiness" in text


def test_saas_staging_exposes_audit_static_gaps_command() -> None:
    text = SCRIPT.read_text()

    assert "scripts/dev/saas_staging.sh audit-static-gaps" in text
    assert "LOCAL_AUTH_STATIC_GAPS_SCRIPT=" in text
    assert "cmd_audit_static_gaps()" in text
    assert "audit-static-gaps) cmd_audit_static_gaps" in text


def test_saas_staging_exposes_audit_acceptance_command() -> None:
    text = SCRIPT.read_text()

    assert "scripts/dev/saas_staging.sh audit-acceptance" in text
    assert "LOCAL_AUTH_ACCEPTANCE_SCRIPT=" in text
    assert "cmd_audit_acceptance()" in text
    assert "audit-acceptance) cmd_audit_acceptance" in text


def test_saas_staging_exposes_audit_control_evidence_command() -> None:
    text = SCRIPT.read_text()

    assert "scripts/dev/saas_staging.sh audit-control-evidence" in text
    assert "LOCAL_AUTH_CONTROL_EVIDENCE_SCRIPT=" in text
    assert "cmd_audit_control_evidence()" in text
    assert "audit-control-evidence) cmd_audit_control_evidence" in text


def test_saas_staging_exposes_audit_gate_command() -> None:
    text = SCRIPT.read_text()

    assert "scripts/dev/saas_staging.sh audit-gate" in text
    assert "LOCAL_AUTH_GATE_SCRIPT=" in text
    assert "cmd_audit_gate()" in text
    assert "audit-gate) cmd_audit_gate" in text


def test_saas_staging_exposes_audit_artifacts_command() -> None:
    text = SCRIPT.read_text()

    assert "scripts/dev/saas_staging.sh audit-artifacts" in text
    assert "LOCAL_AUTH_ARTIFACTS_SCRIPT=" in text
    assert "cmd_audit_artifacts()" in text
    assert "audit-artifacts) cmd_audit_artifacts" in text
