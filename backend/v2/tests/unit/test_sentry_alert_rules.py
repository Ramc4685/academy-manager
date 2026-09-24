"""Unit tests for Sentry alert rules as code (roadmap D10).

HTTP is faked with an in-memory Sentry that mirrors the real endpoint's
semantics: rules are keyed by server-assigned id, listing echoes display-only
keys (``name``/``label``) on each condition and numeric values as strings.
No network access.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from backend.scripts import sentry_alert_rules as sar

REPO_ROOT = Path(__file__).resolve().parents[4]
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "sentry-alerts.md"
TOKEN = "sntrys_test_secret_value_1234"


class _Resp:
    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self._body = body
        self.text = json.dumps(body)

    def json(self) -> Any:
        return self._body


class _FakeSentry:
    """Stands in for ``requests.Session`` against the Sentry rules API."""

    def __init__(self, rules: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.rules: dict[str, list[dict[str, Any]]] = {
            k: [dict(r) for r in v] for k, v in (rules or {}).items()
        }
        self.calls: list[tuple[str, str]] = []
        self.headers_seen: list[dict[str, str]] = []
        self._next_id = 1000

    def _project(self, url: str) -> tuple[str, str | None]:
        tail = url.split("/api/0/projects/", 1)[1].strip("/").split("/")
        assert tail[0] == sar.SENTRY_ORG
        return tail[1], (tail[3] if len(tail) > 3 else None)

    @staticmethod
    def _echo(rule: dict[str, Any]) -> dict[str, Any]:
        out = dict(rule)
        for key in ("conditions", "filters", "actions"):
            out[key] = [
                {
                    **{k: (str(v) if isinstance(v, int) else v) for k, v in item.items()},
                    "name": "display text",
                }
                for item in rule.get(key, [])
            ]
        return out

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> _Resp:
        self.calls.append(("GET", url))
        self.headers_seen.append(headers)
        project, _ = self._project(url)
        return _Resp(200, [self._echo(r) for r in self.rules.get(project, [])])

    def post(
        self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: float
    ) -> _Resp:
        self.calls.append(("POST", url))
        project, _ = self._project(url)
        if any(r["name"] == json["name"] for r in self.rules.get(project, [])):
            return _Resp(400, {"name": ["duplicate"]})
        self._next_id += 1
        rule = {**json, "id": str(self._next_id)}
        self.rules.setdefault(project, []).append(rule)
        return _Resp(201, rule)

    def put(
        self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: float
    ) -> _Resp:
        self.calls.append(("PUT", url))
        project, rule_id = self._project(url)
        for idx, rule in enumerate(self.rules.get(project, [])):
            if rule["id"] == rule_id:
                self.rules[project][idx] = {**json, "id": rule_id}
                return _Resp(200, self.rules[project][idx])
        return _Resp(404, {"detail": "not found"})


def _run(
    fake: _FakeSentry, argv: list[str], environ: dict[str, str] | None = None
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = sar.main(
        argv,
        environ={sar.TOKEN_ENV: TOKEN} if environ is None else environ,
        client_factory=lambda tok, base: sar.SentryClient(token=tok, base_url=base, session=fake),
        out=out,
        err=err,
    )
    return code, out.getvalue(), err.getvalue()


def _all_declared() -> dict[str, list[dict[str, Any]]]:
    rules: dict[str, list[dict[str, Any]]] = {}
    for idx, rule in enumerate(sar.RULES):
        rules.setdefault(rule.project, []).append({**rule.payload(), "id": str(idx + 1)})
    return rules


def _writes(fake: _FakeSentry) -> list[tuple[str, str]]:
    return [c for c in fake.calls if c[0] != "GET"]


def test_declares_rules_for_both_projects() -> None:
    projects = {r.project for r in sar.RULES}
    assert projects == {"courtmastr-fastapi", "courtmastr-frontend"}
    names = {r.name for r in sar.RULES}
    assert len(names) == 3
    for rule in sar.RULES:
        assert rule.environment == sar.PRODUCTION_ENV[rule.project]
    billing = [r for r in sar.RULES if "billing" in r.name]
    assert all(f["value"] == "/billing" for r in billing for f in r.filters)


def test_dry_run_is_default_and_never_writes() -> None:
    fake = _FakeSentry()
    code, out, _ = _run(fake, [])
    assert code == 0
    assert _writes(fake) == []
    assert out.count("CREATE") == len(sar.RULES)
    assert "Dry run" in out


def test_apply_creates_missing_rules() -> None:
    fake = _FakeSentry()
    code, _, _ = _run(fake, ["--apply"])
    assert code == 0
    assert [c[0] for c in _writes(fake)] == ["POST"] * len(sar.RULES)
    for project in ("courtmastr-fastapi", "courtmastr-frontend"):
        assert len(fake.rules[project]) == 3


def test_apply_is_idempotent_noop_when_identical() -> None:
    fake = _FakeSentry(_all_declared())
    code, out, _ = _run(fake, ["--apply"])
    assert code == 0
    assert _writes(fake) == []
    assert out.count("NOOP") == len(sar.RULES)

    # A second full run after a create is also a no-op.
    fresh = _FakeSentry()
    _run(fresh, ["--apply"])
    fresh.calls.clear()
    _run(fresh, ["--apply"])
    assert _writes(fresh) == []


def test_apply_updates_changed_rule_by_id() -> None:
    rules = _all_declared()
    target = rules["courtmastr-fastapi"][1]
    target["conditions"] = [{**target["conditions"][0], "value": 50}]
    target["frequency"] = 1440
    fake = _FakeSentry(rules)

    code, out, _ = _run(fake, [])
    assert code == 0 and _writes(fake) == []
    assert "UPDATE courtmastr-fastapi" in out
    assert "frequency: 1440 -> 60" in out

    code, _, _ = _run(fake, ["--apply"])
    assert code == 0
    writes = _writes(fake)
    assert len(writes) == 1
    assert writes[0][0] == "PUT"
    assert writes[0][1].endswith(
        f"/projects/blno-badmintion/courtmastr-fastapi/rules/{target['id']}/"
    )
    fake.calls.clear()
    _run(fake, ["--apply"])
    assert _writes(fake) == []


def test_unmanaged_rules_are_left_alone() -> None:
    rules = _all_declared()
    rules["courtmastr-frontend"].append({"id": "77", "name": "Hand-made rule", "conditions": []})
    fake = _FakeSentry(rules)
    code, out, _ = _run(fake, ["--apply"])
    assert code == 0
    assert _writes(fake) == []
    assert "Hand-made rule (unmanaged" in out


def test_missing_token_exits_nonzero_with_clear_message() -> None:
    fake = _FakeSentry()
    code, _out, err = _run(fake, ["--apply"], environ={})
    assert code == 2
    assert "SENTRY_AUTH_TOKEN is not set" in err
    assert fake.calls == []


def test_token_is_never_printed_and_sent_as_bearer() -> None:
    fake = _FakeSentry()
    code, out, err = _run(fake, ["--apply"])
    assert code == 0
    assert TOKEN not in out and TOKEN not in err
    assert fake.headers_seen[0]["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in repr(sar.SentryClient(token=TOKEN, session=fake))


def test_api_error_exits_nonzero_without_leaking_token() -> None:
    class _Denied(_FakeSentry):
        def get(self, url: str, *, headers: dict[str, str], timeout: float) -> _Resp:
            return _Resp(403, {"detail": "You do not have permission"})

    code, out, err = _run(_Denied(), [])
    assert code == 1
    assert "HTTP 403" in err
    assert TOKEN not in out + err


def test_runbook_documents_script() -> None:
    text = RUNBOOK.read_text()
    assert "sentry_alert_rules" in text
    for rule in sar.RULES:
        assert rule.name in text
