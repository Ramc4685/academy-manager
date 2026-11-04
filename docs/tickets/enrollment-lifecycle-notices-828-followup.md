# #828 carve-out: the four remaining lifecycle notices are NOT shipped

Issue #828 ("Waitlist offer with 3-day confirmation window + remaining
lifecycle notices", itself carved out of #778) was written with two independent
halves:

1. **Waitlist offer / confirm / sweep** — a freed seat is HELD and offered for
   three days instead of being seated immediately.
2. **Remaining lifecycle notices** — four separate emails sent through the
   existing notifier ports.

Commit `56842990e` ships **half 1 only**. Half 2 is untouched: nothing in the
tree sends a last-class reminder, a pause-ending notice, a first-class notice
or a level-up notice, and no scheduler job exists for any of them. #828 must
not be closed by the waitlist work — it is only half satisfied.

## What half 2 still needs

Each of the four is its own piece of work, with its own trigger, its own
once-per-event key and (for three of them) its own scheduled job. That is why
it is carved out rather than bolted onto the waitlist change: the waitlist half
is already ~1,400 lines across 31 files, and none of these four share its
trigger.

| Notice | Trigger | Still missing |
| --- | --- | --- |
| "your last class is `<date>`" | a pending `cancel_at_period_end` action approaching its `run_at` | a reminder pass in `process_scheduled_cancellation_actions.py` (the worker today only runs the cancel itself, at period end — a reminder has to fire *before* `run_at`), a per-action "reminded" marker so the hourly tick sends once, and the notifier port + adapter |
| pause ending | `ProcessScheduledResumeActions` resuming a paused enrollment | notifier call on the resume path plus an ahead-of-time reminder pass, same shape as above |
| first class | an enrollment's first occurrence approaching | a new scheduled job and an occurrence query ("first occurrence per enrollment in the next N hours"); registration in `settings.sentry_cron_jobs` |
| level up | a skill-pathway level change | a cross-context handler — the enrollment context may not import the pathway context (`tests/structural/test_layering.py`), so this is an outbox event plus a `composition/` adapter |

## Rules any implementation inherits

Same contract as `RosterChangeNotifier` and `WaitlistOfferNotifier`
(`contexts/enrollment/application/ports.py`):

- **Best-effort, never fails the write.** Every call site invokes the port last
  and swallows what it raises.
- **Once per event.** Each of these fires from an hourly worker, so the
  "already sent" marker is part of the feature, not an afterthought.
- **Session timezone, with the zone printed** for any notice quoting a class
  time (#541/#604) — see the `composition/roster_notifications.py` docstring.

## Tracker

Split #828 in two before closing anything: keep #828 for the waitlist offer
window (shipped by `56842990e`) and open a follow-up issue carrying the table
above. `56842990e` deliberately carries no `Closes #828` trailer, so nothing
auto-closes the issue in the meantime.
