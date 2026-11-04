# Cancellations stay in their own academy; multi-academy mode is safe to switch on later

PR: #988

## What changed

- **Cancellations no longer run in the wrong academy.** The admin "cancel class" and "cancel enrollment" actions stamped the academy the server started with (BLNO in production) onto the cancellation event. The follow-up work, which offers the freed seat to the waitlist and closes stale level-up recommendations, then ran in BLNO instead of the academy that cancelled. For a second academy, its waitlist would never move, and BLNO rows sharing the same ids could be offered a seat. The cancellation now carries the academy of the request.
- **Approving a fixed-length pause** wrote the scheduled "resume on" row under the boot academy. The second academy's family would never have been resumed. It now lands in the approving academy.
- The same boot-time academy id was also used as a label in creating classes, joining a waitlist, recording expenses, class types, messages and coach attendance. All of these now read the request's academy. Storage was already correct for these; only the label was wrong.
- **A safety net in the repository layer.** When an update body carries an `academy_id`, it is now overwritten with the academy in scope, the same way inserts already were.
- **Guards for switching on multi-academy mode:**
  - Production refuses to start with `multi_academy` but no SaaS mode. That combination would sign every BLNO user out.
  - Production SaaS mode requires the platform base domain and the proxy shared secret.
  - In SaaS mode, the API trusts the forwarded host only from the frontend proxy (checked by the shared secret). A direct caller can no longer pick an academy by sending its own `X-Forwarded-Host`.
- **New pre-flight script** `backend/scripts/multi_academy_preflight.py`. It is read-only by default. Its opt-in membership backfill only inserts missing rows: it never overrides a suspended or removed membership under any of the user's ids, skips disabled accounts, copies academy roles only, and holds owner/admin/billing grants for manual review. The new runbook [`docs/runbooks/enable-multi-academy.md`](../runbooks/enable-multi-academy.md) gives the pre-flight checks and the exact switch-on steps. The switch itself is left to the owner.
- Tests:
  - Real-Mongo two-tenant tests that cancel and approve a pause in academy B while booted as A, then prove A is untouched.
  - A BLNO regression test for single-academy mode.
  - Settings, resolver and pre-flight tests.

## Deploy notes

- No migration and no setting change. Production stays `single_academy`; nothing in `backend/fly.toml` changes.
- BLNO is unaffected. In single-academy mode the request academy is BLNO, so every stamp and follow-up is the same as before (pinned by `test_blno_regression_single_academy_cancellation_is_unchanged`).

## Risk / rollback

- Low. The riskiest piece is the repository re-stamp. It only changes a write that would otherwise have stored a different academy's id than the one in scope, which is always a bug. The full backend suite passes.
- Rollback: revert this PR. There is no data to undo.
