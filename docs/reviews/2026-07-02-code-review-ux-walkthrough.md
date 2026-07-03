# Code Review + UX Walkthrough — 2026-07-02

Scope: all functional code merged since `5235a9f3` (PRs #253–#270: billing P0 hardening, autopay/ACH stack, registration onboarding fix, error sanitization, audit gate) — ~170 files, +20.6k lines. Four parallel review agents covered billing backend, identity/coaching, frontend, and scripts/infra. UX walkthrough done in a live browser against the local stack (`blno.localhost:3001`, seeded BLNO data) as parent, coach, and admin.

---

## Part 1 — Code review findings

### Fixed already (no action)
- **Parent-role overwrite / onboarding lockout in `register_public_parent.py`** — the review flagged this as P0 on local main, but PR #270 (merged 2026-07-02, now pulled) fixes exactly this: upsert also fires for active memberships missing the `parent` role and unions roles instead of overwriting.

### P0 — fix before next release

1. **`scripts/dev/cleanup_stale_tuition_subscriptions.py:100-158` — destructive script with no production guard.**
   Runs a real `delete_many` against `--mongo-url` defaulting to `$MONGO_URL` and `--db-name` defaulting to `academy_manager` (the production naming convention). Every other destructive script in the repo refuses non-local Mongo hosts; this one doesn't. Run it in a shell where `MONGO_URL` points at prod (e.g. a Fly console) and it deletes live subscription docs.
   *Fix:* add the same `assert_local_mongo_url`-style guard, and stop defaulting the DB name.

2. **`frontend/app/(parent)/parent/payments/page.tsx:174-181` — checkout-status polling never terminates for ACH.**
   The `refetchInterval` stop-condition checks `active|past_due|cancelled`, but the endpoint actually returns `active|verification_required|verification_pending` (plus raw Stripe session states). An ACH setup that needs micro-deposit verification polls every 3 s forever while the parent sits on the page.
   *Fix:* stop on `verification_required`/`verification_pending` too, and add a hard attempt/time cap.

3. **`frontend/app/(parent)/parent/payments/page.tsx:203-285` — backend `detail` strings shown verbatim to parents.**
   All four mutation `onError` handlers interpolate `error.message` into the banner. **Confirmed live in the walkthrough:** clicking "Set up autopay" showed the parent `Autopay could not start. redirect url origin not allowed: 'http://blno.localhost:3001'`. The auth pages got a sanitizer (`lib/auth/auth-error.ts`) in this same change-set; payments did not.
   *Fix:* shared parent-facing error mapper with a generic fallback; never interpolate `detail` by default.

### P1

4. **`mongo_billing_ledger_repo.py:345-425` (`list_open_failed_attempts`, `list_unmatched_invoices`) — unbounded N+1.** One extra Mongo round-trip per open invoice, no limit, surfaced on admin endpoints. Thousands of open invoices ⇒ multi-second admin requests. *Fix:* single `$lookup` pipeline + pagination.

5. **`connect_onboarding.py:42-75` — platform Connect onboarding `refresh_url`/`return_url` passed to Stripe unvalidated**, unlike every parent checkout path which goes through `_validate_checkout_redirect_urls`. Limited blast radius (platform admin only) but breaks the allowlist convention. *Fix:* run both URLs through the same validator.

6. **`assert_local_mongo_url` bypassable via multi-host seed lists** (`scale_blno_staging.py:123`, duplicated in `export_local_auth_inventory_env.py:56`): `urlparse` only sees the first host of `mongodb://127.0.0.1,prod-host/...`; pymongo connects to all of them. *Fix:* reject comma netlocs; dedupe the guard into one shared module.

7. **Audit gate accepts stale Playwright reports** (`audit_inventory_gate.py:437`, `check_local_auth_audit_readiness.py:224`): no git-SHA/manifest-hash/mtime check, so a `CLEAN_PASS` can be reported for code that changed after the run. *Fix:* stamp report metadata with manifest hash + SHA and verify.

### P2 / opportunities

8. `backend/v2/main.py:359-361` — dunning scheduler job silently `continue`s when `process_dunning_retries` wiring is missing; log a warning so a refactor can't mute dunning invisibly.
9. `mongo_dunning_state_repo.py:110-205` — `claim_next_due` filters candidates in Python; push `next_attempt_at <= now` into the Mongo query before volume grows.
10. `admin/billing-health/page.tsx:76-93` — "Dunning Cases" red metric and the `healthy` flag count resolved/suppressed rows; filter to active states or the page trains admins to ignore red.
11. `admin/billing-health/page.tsx:149-156` — "Next / terminal" column shows a bare timestamp with no indication of which of the two it is; prefix with `Next:`/`Terminal:`.
12. `frontend/lib/api/parent.ts:107` — dead `subscription_status` field left on `ParentEnrollment`; exactly the stale-contract trap that caused finding #2. Remove or `@deprecated`.
13. New `app/error.tsx` / `global-error.tsx` / `not-found.tsx` have no `role="alert"`/`role="status"` — screen readers get no announcement when an error boundary swaps the page.
14. Brittle source-string tests (`test_scheduler_academies.py:56`, `test_saas_staging_scale_command.py`) assert substrings of source instead of behavior; they pass even when the behavior breaks.
15. Verified sound (explicitly checked, no action): webhook idempotency & double-payment guards in `handle_webhook_event.py`/`ledger.py`, redirect allowlist in `shared/security/redirect.py`, idempotency-store cache-hit fix, `compute_payout.py` UTC normalization, `auth-error.ts` sanitizer.

---

## Part 2 — UX walkthrough report

Method: real sign-ins as parent (`manojedward.btech@gmail.com`), coach (`gowtham@blno.academy`), admin (`ramchand4685@gmail.com`); exercised the main pages and the risky interactions (autopay setup, pause, attendance, teaching plan, reconciliation, dues).

### Parent

1. **Raw engineering error on the money page (top issue).** "Set up autopay" → `Autopay could not start. redirect url origin not allowed: 'http://blno.localhost:3001'`. A parent has no idea what to do with this; on the page where trust matters most. (Same root as code finding #3.)
2. **Session times contradict themselves.** The enrollment is titled "Thursday 6:00 PM – 6:45 PM Beginner…" but the occurrence rows on My Children render "Thu, Jul 2 · 11:00 PM – 11:45 PM" — occurrence times are formatted in the viewer's browser timezone while the title carries academy-local time. A parent in another timezone (or any UTC-ish device) sees two different times for the same class. Render occurrences in the academy timezone with an explicit tz label.
3. **"Pause" is ambiguous and mis-anchored.** The button sits in the *Autopay* card next to "Set up autopay", so it reads as "pause autopay" — but it opens a "Pause request" form that pauses the *enrollment*. Label it "Pause enrollment" and move it to the child/enrollment context. Also: the resume date defaults to today, which is never a valid pause.
4. **Payment history is unlabeled and duplicated.** Two identical "$60.00 · succeeded · 6/12/2026, 2:12:58 PM" rows with no invoice number, child, or period — parents can't tell what they paid for, and identical rows look like a double charge (verify whether it's a display duplicate or seeded data). Meanwhile the Invoices card says "No invoices yet" right above payments that clearly settled invoices — contradictory.
5. **Adding a second child re-runs full onboarding.** "+ Add" drops an existing, signed-in parent into step 1 "Your details" with *empty* first/last/phone fields they already provided. Pre-fill and skip to the child step.
6. **Silent validation.** On onboarding step 1, pressing Next with empty fields just moves focus — no error text. Add inline messages.
7. **Generic branding.** Header shows a letter avatar "A / Academy" while the dashboard body says "BLno Badminton Academy" (also note the stray capitalization "BLno" in seed data). Use the academy name/logo in the header.
8. Minor: dashboard "Next up" card shows literal labels "Class context" / "Current enrollment" — placeholder-ish copy; the Progress page lists the same six skills twice ("Recent skill updates" = all "Not started" with a meaningless Jun 12 date, then the numbered list again).

### Coach

9. **Dead-end primary buttons with developer copy (top issue).** On the Coach Day Hub, "I can't attend" returns *"Absence notices need a coach-scoped replacement request workflow before they can be sent here"* and "Message parents" returns *"Parent messaging needs the coach-scoped messaging service before it can be used here."* Two of the five actions on the coach's home screen are non-functional and explain themselves in architecture jargon. Hide them until the features exist (or show "Coming soon" copy a coach can parse).
10. **Home vs Today overlap.** `/coach/dashboard` ("Coach Day Hub") and `/coach/today` both show the same day's sessions with different date pickers and different action sets — coaches must learn which screen does what. Consider merging or clearly differentiating (planning vs. running a session).
11. **Skill-vocabulary sprawl.** From one session a coach sees "Skill updates", "Skill Progress", "Skills" (per student), "Prepare", and "Open skill updates" — five entry points with overlapping names. Consolidate naming.
12. **No bulk attendance.** 12 students = 12 taps of "Present"; typical class has most present. Add "Mark all present" then toggle exceptions. Also the Present/Absent state is color-only (no `aria-pressed`), invisible to screen readers.
13. **Grouped skill gaps are noise at cohort start.** Each skill lists all 11 student names, three times over. Truncate to counts + "view students".
14. **"Not placed in a level" with no action.** The teaching plan flags Shamshritha Shivanuri as unplaced but offers no way to place her or explanation of who can.
15. Good: attendance feedback is instant and visible; note-saving says "Save note — parent will see this" (excellent transparency); "✓ Practicing recorded" confirms teaching-plan taps.

### Admin

16. **"System healthy" next to "Last reconciliation run: never".** Billing Health claimed health before any reconciliation had ever run. Show "unknown/never run" state until there's data. (Related: code finding #10 — the healthy flag also miscounts resolved dunning rows.)
17. **Reconciliation notes truncated with no expansion.** The run's explanation ("Stripe returned no app-owned PaymentIntents. Checkout payments created before Pa…") is cut off and there's no way to read the rest — and it's the one field that explains a 0-scanned run.
18. **Empty "Stage" column in Dues follow-up.** All 19 rows have a blank Stage cell — dead column that makes admins wonder whether dunning is broken.
19. **"Revenue this month $0" without context.** On the 2nd of a month with 73 tracked payments and a $3k prior month, a big "$0" reads as breakage. Add prior-month comparison or "month-to-date" labeling.
20. **Timezone again:** reconciliation run showed "Jul 2, 7:28 PM" for an action taken at 2:28 PM local — same viewer-vs-academy timezone issue as the parent side.
21. Good: sidebar IA (Work/Money/Comms·Ops) is clear; "Needs your attention" with HIGH/MEDIUM priorities is a strong pattern; dues bulk-reminder selection copy explains the no-selection behavior.

### Cross-cutting recommendations (highest leverage first)
1. **One timezone policy** — render all schedule/payment timestamps in the academy's timezone with a tz suffix; this bit every persona.
2. **One error-message gate** — extend the `auth-error.ts` sanitizer pattern into a shared "user-facing message" mapper used by every mutation banner (parents saw raw backend internals today).
3. **Never ship dead buttons** — feature-flag "I can't attend" / "Message parents" out of the coach hub until backed by a real workflow.
4. **Label money rows** — payment history entries need invoice number + child + period; reconcile the "No invoices yet" card with visible payment history.
5. **Prefill known data** — existing parents adding a child should never retype their own name/phone.
