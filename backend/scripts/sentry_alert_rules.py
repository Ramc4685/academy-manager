"""Sentry issue-alert rules as code (roadmap D10).

The alert rules for the ``blno-badmintion`` Sentry org used to exist only in
the Sentry UI, so nobody could review them, and a deleted rule failed
silently. This module declares them in :data:`RULES` and reconciles each
project against that list through the Sentry REST API:

1. ``GET /api/0/projects/{org}/{project}/rules/``
2. match each desired rule by **name**
3. ``POST`` the rule when it is missing, ``PUT .../rules/{id}/`` when the
   managed fields differ, and do nothing when they are identical.

Rules that exist in Sentry but are not declared here are left alone and
listed as ``unmanaged``, so the script never deletes a rule someone added by
hand.

Usage::

    export SENTRY_AUTH_TOKEN=...     # scopes: project:read, project:write (alerts:write)
    backend/.venv/bin/python -m backend.scripts.sentry_alert_rules            # dry run (default)
    backend/.venv/bin/python -m backend.scripts.sentry_alert_rules --apply    # write changes

A dry run still reads current rules from Sentry and prints the plan and the
field-level diff, but it never writes. The token is read from the environment
only, never from argv, and never printed. See ``docs/runbooks/sentry-alerts.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

SENTRY_ORG = "blno-badmintion"
BACKEND_PROJECT = "courtmastr-fastapi"
FRONTEND_PROJECT = "courtmastr-frontend"
DEFAULT_BASE_URL = "https://sentry.io"
TOKEN_ENV = "SENTRY_AUTH_TOKEN"

# The backend tags events with ``settings.env`` ("prod"); the frontend with
# NEXT_PUBLIC_APP_ENV ("production"). Each project's rules filter on its own.
PRODUCTION_ENV: dict[str, str] = {
    BACKEND_PROJECT: "prod",
    FRONTEND_PROJECT: "production",
}

_FIRST_SEEN = "sentry.rules.conditions.first_seen_event.FirstSeenEventCondition"
_UNIQUE_USERS = "sentry.rules.conditions.event_frequency.EventUniqueUserFrequencyCondition"
_EVENT_FREQUENCY = "sentry.rules.conditions.event_frequency.EventFrequencyCondition"
_TAGGED_EVENT = "sentry.rules.filters.tagged_event.TaggedEventFilter"
_EMAIL_ACTION = "sentry.mail.actions.NotifyEmailAction"

# Email the issue owners, falling back to active members when no ownership
# rule matches (a small team: everybody is the fallback).
_NOTIFY_EMAIL: dict[str, Any] = {
    "id": _EMAIL_ACTION,
    "targetType": "IssueOwners",
    "fallthroughType": "ActiveMembers",
}

# Fields this script owns on a rule. Anything else Sentry returns (id,
# owner, createdBy, dateCreated, projects, status, ...) is ignored for diffing.
MANAGED_FIELDS: tuple[str, ...] = (
    "name",
    "environment",
    "actionMatch",
    "filterMatch",
    "frequency",
    "conditions",
    "filters",
    "actions",
)


@dataclass(frozen=True)
class AlertRule:
    """One declared issue-alert rule for one project."""

    project: str
    name: str
    conditions: tuple[Mapping[str, Any], ...]
    filters: tuple[Mapping[str, Any], ...] = ()
    actions: tuple[Mapping[str, Any], ...] = (_NOTIFY_EMAIL,)
    action_match: str = "all"
    filter_match: str = "all"
    frequency_minutes: int = 60
    environment: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "environment": self.environment,
            "actionMatch": self.action_match,
            "filterMatch": self.filter_match,
            "frequency": self.frequency_minutes,
            "conditions": [dict(c) for c in self.conditions],
            "filters": [dict(f) for f in self.filters],
            "actions": [dict(a) for a in self.actions],
        }


def _rules_for(project: str) -> list[AlertRule]:
    env = PRODUCTION_ENV[project]
    return [
        AlertRule(
            project=project,
            name="[managed] New issue in production",
            environment=env,
            conditions=({"id": _FIRST_SEEN},),
            frequency_minutes=5,
        ),
        AlertRule(
            project=project,
            name="[managed] Issue affecting 5+ users in 1h",
            environment=env,
            conditions=(
                {"id": _UNIQUE_USERS, "value": 5, "interval": "1h", "comparisonType": "count"},
            ),
            frequency_minutes=60,
        ),
        AlertRule(
            project=project,
            name="[managed] Error spike on /billing routes",
            environment=env,
            conditions=(
                {"id": _EVENT_FREQUENCY, "value": 10, "interval": "1h", "comparisonType": "count"},
            ),
            filters=(
                {"id": _TAGGED_EVENT, "key": "transaction", "match": "co", "value": "/billing"},
            ),
            frequency_minutes=30,
        ),
    ]


RULES: tuple[AlertRule, ...] = tuple(
    rule for project in (BACKEND_PROJECT, FRONTEND_PROJECT) for rule in _rules_for(project)
)


# ---------------------------------------------------------------------------
# Diffing
# ---------------------------------------------------------------------------


def _normalize_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only the keys we set, stringified the way Sentry echoes them.

    Sentry adds display-only keys (``name``, ``label``) to each condition and
    may return numeric values as strings, so compare on our own keys only.
    """
    return {
        k: (str(v) if v is not None else None)
        for k, v in item.items()
        if k not in {"name", "label"}
    }


def _normalize(rule: Mapping[str, Any], desired: Mapping[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in MANAGED_FIELDS:
        value = rule.get(key)
        if key in {"conditions", "filters", "actions"}:
            items = list(value or [])
            wanted_keys: list[set[str]] = []
            if desired is not None:
                wanted_keys = [set(i) for i in desired.get(key) or []]
            normalized = []
            for idx, item in enumerate(items):
                keep = wanted_keys[idx] if idx < len(wanted_keys) else set(item)
                normalized.append(_normalize_item({k: v for k, v in item.items() if k in keep}))
            out[key] = sorted(normalized, key=lambda i: json.dumps(i, sort_keys=True))
        elif key == "frequency":
            out[key] = int(value) if value is not None else None
        else:
            out[key] = value
    return out


def diff_rule(current: Mapping[str, Any], desired: Mapping[str, Any]) -> dict[str, tuple[Any, Any]]:
    """Return ``{field: (current, desired)}`` for every managed field that differs."""
    cur = _normalize(current, desired)
    want = _normalize(desired, desired)
    return {k: (cur[k], want[k]) for k in MANAGED_FIELDS if cur[k] != want[k]}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class SentryApiError(RuntimeError):
    pass


@dataclass
class SentryClient:
    """Minimal Sentry REST client. ``session`` is a ``requests.Session``-like."""

    token: str = field(repr=False)
    base_url: str = DEFAULT_BASE_URL
    org: str = SENTRY_ORG
    session: Any = None
    timeout: float = 20.0

    def __post_init__(self) -> None:
        if self.session is None:
            import requests

            self.session = requests.Session()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def _url(self, project: str, rule_id: str | None = None) -> str:
        base = f"{self.base_url.rstrip('/')}/api/0/projects/{self.org}/{project}/rules/"
        return f"{base}{rule_id}/" if rule_id else base

    def _check(self, resp: Any, what: str) -> Any:
        if not 200 <= int(resp.status_code) < 300:
            # Never echo request headers: they carry the token.
            raise SentryApiError(f"{what} failed: HTTP {resp.status_code}: {str(resp.text)[:300]}")
        return resp.json()

    def list_rules(self, project: str) -> list[dict[str, Any]]:
        resp = self.session.get(self._url(project), headers=self._headers(), timeout=self.timeout)
        data = self._check(resp, f"list rules for {project}")
        return list(data or [])

    def create_rule(self, project: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        resp = self.session.post(
            self._url(project), headers=self._headers(), json=dict(payload), timeout=self.timeout
        )
        return dict(self._check(resp, f"create rule {payload.get('name')!r} in {project}"))

    def update_rule(self, project: str, rule_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        resp = self.session.put(
            self._url(project, rule_id),
            headers=self._headers(),
            json=dict(payload),
            timeout=self.timeout,
        )
        return dict(self._check(resp, f"update rule {payload.get('name')!r} in {project}"))


# ---------------------------------------------------------------------------
# Plan / apply
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlannedChange:
    action: str  # "create" | "update" | "noop"
    project: str
    name: str
    rule_id: str | None
    payload: dict[str, Any]
    diff: dict[str, tuple[Any, Any]]


def plan(
    client: SentryClient, rules: Sequence[AlertRule] = RULES
) -> tuple[list[PlannedChange], list[str]]:
    """Compare declared rules with Sentry. Returns (changes, unmanaged rule labels)."""
    changes: list[PlannedChange] = []
    unmanaged: list[str] = []
    by_project: dict[str, list[AlertRule]] = {}
    for rule in rules:
        by_project.setdefault(rule.project, []).append(rule)
    for project, project_rules in by_project.items():
        existing = client.list_rules(project)
        by_name: dict[str, dict[str, Any]] = {}
        for item in existing:
            by_name.setdefault(str(item.get("name")), item)
        declared = {r.name for r in project_rules}
        unmanaged.extend(f"{project}: {n}" for n in sorted(by_name) if n not in declared)
        for rule in project_rules:
            payload = rule.payload()
            current = by_name.get(rule.name)
            if current is None:
                changes.append(PlannedChange("create", project, rule.name, None, payload, {}))
                continue
            delta = diff_rule(current, payload)
            action = "update" if delta else "noop"
            changes.append(
                PlannedChange(action, project, rule.name, str(current.get("id")), payload, delta)
            )
    return changes, unmanaged


def apply(client: SentryClient, changes: Sequence[PlannedChange]) -> None:
    for change in changes:
        if change.action == "create":
            client.create_rule(change.project, change.payload)
        elif change.action == "update" and change.rule_id:
            client.update_rule(change.project, change.rule_id, change.payload)


def render(changes: Sequence[PlannedChange], unmanaged: Sequence[str]) -> str:
    lines: list[str] = []
    for c in changes:
        lines.append(f"{c.action.upper():6} {c.project}: {c.name}")
        if c.action == "create":
            lines.append("         " + json.dumps(c.payload, sort_keys=True))
        for key, (before, after) in c.diff.items():
            lines.append(
                f"         {key}: {json.dumps(before, sort_keys=True)} -> {json.dumps(after, sort_keys=True)}"
            )
    for label in unmanaged:
        lines.append(f"SKIP   {label} (unmanaged, left untouched)")
    return "\n".join(lines)


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    client_factory: Callable[[str, str], SentryClient] | None = None,
    out: Any = None,
    err: Any = None,
) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    env = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(
        description="Reconcile Sentry issue-alert rules with the declared list."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true", default=True, help="print the diff only (default)"
    )
    mode.add_argument("--apply", action="store_true", help="write creates/updates to Sentry")
    parser.add_argument("--base-url", default=env.get("SENTRY_URL") or DEFAULT_BASE_URL)
    args = parser.parse_args(argv)

    token = (env.get(TOKEN_ENV) or "").strip()
    if not token:
        print(
            f"error: {TOKEN_ENV} is not set. Export a Sentry auth token with project:read "
            "and project:write (alerts:write) scopes; it is read from the environment only.",
            file=err,
        )
        return 2

    factory = client_factory or (lambda tok, base: SentryClient(token=tok, base_url=base))
    client = factory(token, args.base_url)
    try:
        changes, unmanaged = plan(client)
        print(render(changes, unmanaged), file=out)
        pending = [c for c in changes if c.action != "noop"]
        if not args.apply:
            print(
                f"\nDry run: {len(pending)} change(s) pending. Re-run with --apply to write.",
                file=out,
            )
            return 0
        apply(client, pending)
        print(f"\nApplied {len(pending)} change(s).", file=out)
        return 0
    except SentryApiError as exc:
        print(f"error: {exc}", file=err)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
