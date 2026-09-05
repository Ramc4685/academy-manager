# External uptime monitoring and Fly alert rules

Account-side setup that no deploy can do. As of 2026-09-05 none of this
exists: if the Fly machine or the Cloudflare route is down, the only signal is
a parent texting the owner. Each section is a checklist of clicks; tick them
off in the PR that closes the audit item.

Targets:

| URL | Expect | What it proves |
|---|---|---|
| `https://api.academy.courtmastr.com/api/v2/healthz` | HTTP 200, body contains `"status":"ok"` | API up, Mongo reachable, scheduler and outbox dispatcher running. A 503 here already restarts the Fly machine; the monitor is for when nobody comes back. |
| `https://academy.courtmastr.com/` | HTTP 200 | Cloudflare Worker (`academy-next`) serving the Next.js app. |

Check both from outside the US too if the option is free; the academy's
parents are in Chicago, so a US region is the one that matters.

## Option A (recommended): Sentry Uptime

Free plan includes uptime monitors; alerts land in the same project as the
API errors, so the "New issue" alert rule created by `sentry_alerts.sh`
already emails the owner when a monitor fails. No new login, no new inbox.

1. Sentry -> `blno-badmintion` -> **Alerts** -> **Create Alert** -> **Uptime
   Monitor** (under "Crons & Uptime").
2. Project: `courtmastr-fastapi`. Environment: `prod`.
3. Monitor 1:
   - Name: `api healthz`
   - URL: `https://api.academy.courtmastr.com/api/v2/healthz`
   - Method: GET. Interval: 1 minute (drop to 5 if the free quota
     complains). Timeout: 10 s (Fly's own probe allows 5 s; leave headroom for
     the cold Cloudflare edge hop).
   - Expected status: 200. If the form offers a response-body assertion, add
     "body contains `"status":"ok"`"; if it does not (Sentry Uptime shipped
     with status-code checks only and body assertions may still be
     unavailable on the free plan), keep the status check and rely on the
     fact that `/api/v2/healthz` returns 503, not 200, whenever any wired
     component is broken.
   - Owner: the org owner (this is who gets the email).
4. Monitor 2:
   - Name: `web root`
   - URL: `https://academy.courtmastr.com/`
   - GET, 1 minute, 10 s timeout, expected status 200.
5. Recovery threshold 1, failure threshold 3 (three consecutive 1-minute
   failures = about 3 minutes to alert; Fly's health check will usually have
   restarted the machine before this fires, which is the point: it alerts on
   the outages a restart does not fix).
6. Confirm: the monitors appear under **Alerts -> Uptime** as "Up". A failed
   check opens an issue titled `Downtime detected for <name>`; verify the
   "New issue" rule emails you by pausing the API for a minute in staging or
   by pointing a throwaway third monitor at `https://api.academy.courtmastr.com/api/v2/nope`
   (returns 404), watching the email arrive, then deleting that monitor.
7. CLI check afterwards:

   ```bash
   sentry issue list blno-badmintion/courtmastr-fastapi -q 'is:unresolved issue.type:uptime_domain_failure'
   ```

Sentry Uptime is region-fixed (Sentry's own checkers, US-based for US orgs);
that is acceptable here.

## Option B: Better Stack (Uptime, free tier)

Use if Sentry's free uptime quota is exhausted or a body-keyword assertion is
required. Free tier: 10 monitors, 3-minute interval, email + push alerts.

1. Sign up at betterstack.com with the owner's email; create team
   `courtmastr`.
2. **Uptime -> Monitors -> Create monitor**:
   - Monitor 1: URL `https://api.academy.courtmastr.com/api/v2/healthz`,
     "Alert us when: URL doesn't contain a keyword", keyword `"status":"ok"`
     (with the quotes), request method GET, check frequency 3 min, request
     timeout 10 s, regions: North America only, confirmation period 30 s.
   - Monitor 2: URL `https://academy.courtmastr.com/`, "URL becomes
     unavailable" (status check only), same schedule.
3. **Alerting**: default escalation policy -> email + mobile push to the
   owner; leave call/SMS off (paid).
4. Optional heartbeat: **Heartbeats -> Create**, period 26 hours, grace 2
   hours, named `ops digest`. Add the heartbeat URL to the Fly app as
   `V2_OPS_DIGEST_HEARTBEAT_URL` only if that setting is ever built; today
   the Sentry Crons allowlist (`V2_SENTRY_CRON_JOBS`) is the dead-man switch,
   so skip this unless leaving Sentry entirely.
5. Verify with the same 404-URL trick as above, then delete the test monitor.

## Fly Grafana alert rules (fly-metrics.net)

Fly's hosted Grafana has the app's Prometheus metrics for free; alert rules
are configured in Grafana itself and email through a Grafana contact point.
Open `https://fly-metrics.net` (sign in with the Fly account), then:

1. **Alerting -> Contact points -> New**: name `owner-email`, integration
   Email, address = the owner's email. Test it. If the "New contact point"
   button is missing, alerting is disabled on this managed Grafana; fall back
   to Sentry metric alerts (the `Error rate spike` rule from
   `sentry_alerts.sh` covers 5xx via error events) and skip this section.
2. **Alerting -> Notification policies**: set the default policy's contact
   point to `owner-email`, group wait 1m, group interval 5m, repeat 4h.
3. **Alerting -> Alert rules -> New alert rule**, data source `Prometheus`
   (the org's default), folder `courtmastr`, evaluation group `api` every 1m.
   Create these three. Metric names below are Fly's documented app/instance
   series; if one does not autocomplete in the query editor, use the
   **Explore** page to search for the neighbouring name (Fly has renamed a
   few of them) and adjust.

   | Rule | Query (PromQL) | Condition | For |
   |---|---|---|---|
   | `api 5xx rate > 1%` | `sum(rate(fly_app_http_responses_count{app="courtmastr-academy-api", status=~"5.."}[5m])) / sum(rate(fly_app_http_responses_count{app="courtmastr-academy-api"}[5m]))` | `IS ABOVE 0.01` | 5m |
   | `api memory > 85%` | `1 - (fly_instance_memory_mem_available{app="courtmastr-academy-api"} / fly_instance_memory_mem_total{app="courtmastr-academy-api"})` | `IS ABOVE 0.85` | 5m |
   | `api machine restarts` | `changes(fly_instance_up{app="courtmastr-academy-api"}[15m])` | `IS ABOVE 0` | 0m (fire immediately) |

   Notes:
   - The 5xx query divides by total responses; with the academy's traffic
     (a few hundred requests an hour off-peak) one bad request in a quiet
     5-minute window can exceed 1%. If it flaps, add
     `and sum(rate(fly_app_http_responses_count{app="courtmastr-academy-api"}[5m])) > 0.05`
     (at least ~15 requests in the window) to the condition.
   - `fly_instance_up` resets when a machine restarts; `changes()` over 15m
     counts those resets. If the series is absent in Explore, the
     alternative is `resets(fly_instance_net_recv_bytes_total{app="courtmastr-academy-api"}[15m]) > 0`
     (counters reset on restart too). Either way the alert fires once per
     restart and self-resolves after 15 minutes, which is what you want:
     the Fly health check restarts silently, and this is the only place a
     restart loop becomes visible.
   - Memory: the machine is a shared-cpu-1x with 1 GB (see `[[vm]]` in
     `backend/fly.toml`); 85% = about 870 MB, which leaves room for one large
     report export or a migration before the OOM killer restarts it.
4. Set **No data** handling to `OK` (not `Alerting`) on all three, otherwise
   a metrics-pipeline hiccup on Fly's side pages you at 3 a.m.
5. Save, then **Alerting -> Alert rules** should list three rules in state
   `Normal`. Trigger the memory rule deliberately by lowering its threshold
   to 0.10 for one evaluation, confirm the email, and set it back.

## What this does not cover

- Cloudflare-side outages of the Worker are only seen by the web-root
  monitor; Cloudflare's own status page is the diagnostic.
- Mongo Atlas alerts (connection spikes, disk) are configured in Atlas, not
  here; the healthz Mongo ping catches "unreachable" but not "slow".
- Stripe webhook delivery failures are alerted by Stripe's own dashboard
  emails and surfaced in the daily ops digest as quarantined events.
