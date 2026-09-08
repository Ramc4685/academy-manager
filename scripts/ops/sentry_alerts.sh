#!/usr/bin/env bash
# Idempotent Sentry alert rules for blno-badmintion/courtmastr-fastapi.
#
# Creates, if absent BY NAME, three issue alert rules and one metric alert.
# Existing rules with the same name are left untouched (including the
# pre-existing "Send a notification for high priority issues" rule), so the
# script can be re-run after adding a rule or rotating the CLI token.
#
# Dry-run by default: prints every payload it would send. Pass --apply to
# actually POST. Needs the `sentry` CLI (sentry auth login) and `jq`.
#
#   scripts/ops/sentry_alerts.sh            # show payloads, change nothing
#   scripts/ops/sentry_alerts.sh --apply    # create the missing rules
#
# Environment:
#   SENTRY_ORG       default blno-badmintion
#   SENTRY_PROJECT   default courtmastr-fastapi
#   ALERT_EMAIL      optional. Sentry has no "email this raw address" action;
#                    issue alerts route to IssueOwners with fallthrough
#                    AllMembers, i.e. the Sentry account email of every org
#                    member (today: the single owner). ALERT_EMAIL is only
#                    used to pick WHICH org member the metric alert targets
#                    (metric alerts need a concrete user or team). Unset =>
#                    the first member with role owner.
#
# API notes. Both endpoints are the classic alert APIs, chosen because
# GET projects/<org>/<proj>/rules/ is exactly what the existing rule came
# back as (so the shapes below round-trip):
#   POST projects/{org}/{project}/rules/        issue alerts
#   POST organizations/{org}/alert-rules/       metric alerts
# Sentry is migrating issue alerts to organizations/{org}/workflows/ (the
# `sentry alert issues create` subcommand targets that); if the rules
# endpoint ever 404s, port the payloads to that shape (types become
# first_seen_event / regression_event / event_frequency_count).

set -euo pipefail

ORG="${SENTRY_ORG:-blno-badmintion}"
PROJECT="${SENTRY_PROJECT:-courtmastr-fastapi}"
ALERT_EMAIL="${ALERT_EMAIL:-}"
APPLY=0

usage() {
  sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'
}

for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

for tool in sentry jq; do
  command -v "$tool" >/dev/null 2>&1 || { echo "missing: $tool" >&2; exit 1; }
done

log() { printf '%s\n' "$*" >&2; }

# ---------------------------------------------------------------------------
# Current state (GETs are safe in dry-run).
# ---------------------------------------------------------------------------
issue_rules_json="$(sentry api "projects/${ORG}/${PROJECT}/rules/" --json)"
metric_rules_json="$(sentry api "organizations/${ORG}/alert-rules/" --json)"

for payload in "$issue_rules_json" "$metric_rules_json"; do
  status="$(jq -r '.status' <<<"$payload")"
  if [[ "$status" != "200" ]]; then
    log "Sentry API returned $status listing existing rules; is 'sentry auth status' ok?"
    exit 1
  fi
done

existing_issue_names="$(jq -r '.body[].name' <<<"$issue_rules_json")"
existing_metric_names="$(jq -r '.body[].name' <<<"$metric_rules_json")"

has_line() { # has_line <haystack-lines> <needle>
  grep -Fxq -- "$2" <<<"$1"
}

# Metric alerts cannot use IssueOwners; resolve a concrete user id.
resolve_metric_target_user_id() {
  local members
  members="$(sentry api "organizations/${ORG}/members/" --json)"
  if [[ -n "$ALERT_EMAIL" ]]; then
    jq -r --arg m "$ALERT_EMAIL" '
      [.body[] | select(.email == $m and .user != null)][0].user.id // empty
    ' <<<"$members"
  else
    jq -r '
      ([.body[] | select(.role == "owner" and .user != null)][0]
        // [.body[] | select(.user != null)][0]).user.id // empty
    ' <<<"$members"
  fi
}

# ---------------------------------------------------------------------------
# Payloads.
# ---------------------------------------------------------------------------
# Shared email action for issue alerts. Route = every org member's Sentry
# account email once no issue owner matches (there are no ownership rules,
# so in practice it is always the fallthrough).
email_action='{
  "id": "sentry.mail.actions.NotifyEmailAction",
  "targetType": "IssueOwners",
  "fallthroughType": "AllMembers",
  "targetIdentifier": ""
}'

issue_rule() { # issue_rule <name> <conditions-json-array> <frequency-minutes>
  jq -n \
    --arg name "$1" \
    --argjson conditions "$2" \
    --argjson frequency "$3" \
    --argjson action "$email_action" \
    '{
      name: $name,
      actionMatch: "any",
      filterMatch: "any",
      frequency: $frequency,
      conditions: $conditions,
      filters: [],
      actions: [$action]
    }'
}

new_issue_payload="$(issue_rule "New issue" \
  '[{"id": "sentry.rules.conditions.first_seen_event.FirstSeenEventCondition"}]' 30)"

regression_payload="$(issue_rule "Regression" \
  '[{"id": "sentry.rules.conditions.regression_event.RegressionEventCondition"}]' 30)"

# >= 10 events of one issue inside a 1-hour window; re-notify at most hourly.
high_frequency_payload="$(issue_rule "High frequency" \
  '[{
    "id": "sentry.rules.conditions.event_frequency.EventFrequencyCondition",
    "value": 10,
    "interval": "1h",
    "comparisonType": "count"
  }]' 60)"

# Metric alert: count() of error events across the project > 5 in 5 minutes.
# thresholdType 0 = "above". resolveThreshold null = auto-resolve when the
# window drops back under the critical threshold. The trigger action shape
# (type/targetType/targetIdentifier with a user id) is the documented one for
# organizations/{org}/alert-rules/; if Sentry rejects it, the CLI's
# `sentry alert metrics create --dry-run` example uses
# {"id":"sentry.mail.actions.NotifyEmailAction","targetType":"Member",...}
# and is the fallback to try.
metric_rule() { # metric_rule <target-user-id>
  jq -n \
    --arg project "$PROJECT" \
    --arg user "$1" \
    '{
      name: "Error rate spike",
      aggregate: "count()",
      query: "",
      dataset: "events",
      eventTypes: ["error"],
      queryType: 0,
      timeWindow: 5,
      thresholdType: 0,
      resolveThreshold: null,
      comparisonDelta: null,
      environment: null,
      projects: [$project],
      triggers: [
        {
          label: "critical",
          alertThreshold: 5,
          actions: [
            {type: "email", targetType: "user", targetIdentifier: $user}
          ]
        }
      ]
    }'
}

# ---------------------------------------------------------------------------
# Apply (or print).
# ---------------------------------------------------------------------------
post_json() { # post_json <endpoint> <payload>
  if [[ "$APPLY" == "1" ]]; then
    sentry api -X POST "$1" --input - --json <<<"$2" | jq '{status, id: .body.id, name: .body.name}'
  else
    log "  DRY RUN: would POST $1"
    jq . <<<"$2"
  fi
}

ensure_issue_rule() { # ensure_issue_rule <name> <payload>
  local name="$1" payload="$2"
  if has_line "$existing_issue_names" "$name"; then
    log "issue alert '$name': exists, skipping"
    return
  fi
  log "issue alert '$name': creating"
  post_json "projects/${ORG}/${PROJECT}/rules/" "$payload"
}

ensure_metric_rule() { # ensure_metric_rule <name>
  local name="$1" user_id
  if has_line "$existing_metric_names" "$name"; then
    log "metric alert '$name': exists, skipping"
    return
  fi
  user_id="$(resolve_metric_target_user_id)"
  if [[ -z "$user_id" ]]; then
    log "metric alert '$name': could not resolve a member user id (ALERT_EMAIL='${ALERT_EMAIL:-<unset>}'); skipping"
    return
  fi
  log "metric alert '$name': creating (email target user id $user_id)"
  post_json "organizations/${ORG}/alert-rules/" "$(metric_rule "$user_id")"
}

log "Sentry alert rules for ${ORG}/${PROJECT} ($([[ "$APPLY" == "1" ]] && echo APPLY || echo 'dry run; pass --apply to create'))"
log "existing issue alerts:  $(tr '\n' ',' <<<"$existing_issue_names" | sed 's/,$//; s/^$/(none)/')"
log "existing metric alerts: $(tr '\n' ',' <<<"$existing_metric_names" | sed 's/,$//; s/^$/(none)/')"

ensure_issue_rule "New issue" "$new_issue_payload"
ensure_issue_rule "Regression" "$regression_payload"
ensure_issue_rule "High frequency" "$high_frequency_payload"
ensure_metric_rule "Error rate spike"

log "done. Verify with: sentry alert issues list ${ORG}/${PROJECT}; sentry alert metrics list ${ORG}"
