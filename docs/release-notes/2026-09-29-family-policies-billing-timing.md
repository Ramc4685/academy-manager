# Family policies rename + cancellation timing to Billing rules (Settings overhaul Phase 3 PR 10, partial)

PR: #TBD

## What changed

This lane shipped the backend-safe, mechanically-scoped half of the spec. It
does **not** ship the waiver embed, the sidebar nav change, the welcome-email
fallback text, or the `drop_default_outcome` move — see "Not done" below.

- **Settings tab renamed:** `Self-service` -> `Family policies` (key
  `self-service` -> `family-policies`). `?panel=self-service` still works —
  `RETIRED_SETTINGS_PANELS` now maps it to `family-policies`, the same
  pattern used for `?panel=fees`. `/admin/settings/self-service` (the old
  bookmark redirect page) now redirects to `?panel=family-policies`.
- **"When a cancellation takes effect" (`cancellation_effective_timing`)
  moved to Billing rules**, owner-only and audited through the existing
  `UpdateBillingRules` / `billing_audit_log` path — the same pattern PR #1002
  used for the cancellation fee:
  - New enum-valued editable row in Billing rules' "Leaving and pausing"
    card, alongside the existing cancellation notice and late-cancellation
    fee (`backend/v2/contexts/billing/application/use_cases/billing_rules.py`,
    `backend/v2/composition/billing_rules.py`,
    `backend/v2/interfaces/admin/billing_rules_routes.py`).
  - `PUT /admin/self-service/policy` now refuses a **changed**
    `cancellation_effective_timing` with a 422 naming the field and pointing
    at Billing rules (`CANCELLATION_TERMS` in
    `backend/v2/interfaces/admin/self_service_policy_routes.py`); an unchanged
    value in a full resubmit still passes, so an old client is not broken.
  - The Family policies panel dropped the "Effective timing" select and now
    folds it into the existing one-line cancellation-terms summary
    (`cancellationTermsSummary` in `frontend/lib/self-service-policy-form.ts`),
    same as the fee and notice.
  - Billing rules panel gained a `<select>` rendering for choice-typed rows
    (`isChoiceRow` in `frontend/lib/billing-rules-form.ts` and
    `frontend/components/admin/settings/billing-rules-panel.tsx`) — the first
    editable row in that panel that isn't a number, so this is new plumbing,
    not just a new row.
- **Offline payments card:** unchanged, stays in Billing rules.
- The "Absences & makeups" and "What parents can do in the app" cards in
  Family policies are unchanged from Self-service today; they were not
  re-cut into separate cards per the mockup (see "Not done").

## Not done (out of scope for this pass — flagging rather than rushing)

- **Waiver embed (spec step 3).** Embedding the waiver template
  list/editor/publish UI from `frontend/app/(admin)/admin/waivers/page.tsx`
  into Family policies as a "Waivers" section, and removing "Waivers" from
  the admin sidebar, was not done. Doing the removal without the embed would
  strand admins with no way to reach waiver management, so the sidebar item
  (`backend`... `frontend/components/admin/screen-meta.ts` line ~105) was
  deliberately left in place. `/admin/waivers` and its sub-routes are
  untouched and still work.
- **Welcome-email policy text default (spec step 4).** Not investigated or
  built. Needs a read of the class welcome-email template's field first to
  confirm whether it's per-class-only today.
- **"Default when staff drop a student" -> Billing rules.** This setting
  already exists today as `drop_default_outcome` on
  `EnrollmentDeparturePolicy` (`backend/v2/contexts/enrollment/domain/departure_policy.py`),
  edited via the **whole-object** `PUT /admin/enrollment/departure-policy`
  (owner-only already). It was not moved into the Billing rules
  "Leaving & pausing" card in this pass: `UpdateBillingRules` writes each
  store as a *partial* diff (the pattern the other three fields there rely
  on), while the departure-policy route is a whole-object PUT covering three
  other fields (`max_hold_days`, `hold_reclaim_policy`,
  `delete_enrollment_requires_owner`) that stay on the "Holds" card per the
  spec. Folding one field out of a whole-object PUT into a partial-write
  pipeline needs its own adapter and its own test pass, not a drive-by edit.
  Flagged as a follow-up rather than rushed.
- **Card re-grouping per the mockup** ("2 Billing rules" / "5 Family
  policies" sections of the settings plan) beyond the one field move above —
  not done. The existing Self-service card layout (now under the Family
  policies tab) is unchanged.
- **Screenshots and e2e spec updates.** Not captured. A repo-wide grep found
  no e2e spec asserting the `Self-service` tab label, `panel=self-service`,
  or a `Waivers` nav item, so nothing needed updating for the changes that
  did ship — but no screenshots were taken (the ones this batch's UI rules
  ask for require a live dev server + Playwright pass not run here).

## Tests

- Backend: `backend/v2/tests/application/test_billing_rules.py` (new:
  `test_cancellation_timing_row_carries_the_stored_choice_and_options`,
  `test_cancellation_timing_write_lands_and_is_audited`, plus the existing
  `EDITABLE_RULE_KEYS`/write-model-parity test now covers the new field for
  free), `backend/v2/tests/interface/test_admin_billing_rules_routes.py`,
  `backend/v2/tests/interface/test_admin_self_service_policies.py` (new
  parametrize case: a changed `cancellation_effective_timing` 422s the same
  way the fee and notice do; the full-resubmit-unchanged case now also
  asserts it isn't written). All green:
  `backend/.venv/bin/pytest -n 6 backend/v2/tests/application/test_billing_rules.py backend/v2/tests/interface/test_admin_billing_rules_routes.py backend/v2/tests/interface/test_admin_self_service_policies.py` — 68 passed.
- Frontend: `frontend/lib/billing-rules-form.node-test.mjs` (new choice-row
  tests) and `frontend/lib/self-service-policy-form.node-test.mjs` (updated
  PR-5-style rejection test, new summary-sentence test) — 41 passed via
  `node --test`. `pnpm typecheck` and `pnpm eslint` on every changed file are
  clean.
- Backend mypy: no new violations
  (`mypy -p backend.v2 | mypy-baseline filter --allow-unsynced`).

## Deploy notes

- No migration.
- BLNO (and every existing academy): `cancellation_effective_timing` already
  defaults to `"end_of_period"` on the domain model
  (`backend/v2/contexts/enrollment/domain/self_service.py`) and is read at
  request time through the same `ParentSelfServicePolicy` document Billing
  rules now also reads from — no stored value changes, no new field is
  written until an owner edits it. Behaviour is unchanged unless an owner
  visits Billing rules and changes it there.
- An admin (non-owner) who still has `?panel=self-service` bookmarked lands
  on Family policies, same panel as before, just renamed.

## Risk / rollback

- Main risk: an old client (script, saved draft) that PUTs
  `cancellation_effective_timing` to `/admin/self-service/policy` with a
  value that differs from what's stored will now get a 422 instead of a 200,
  same as the existing behaviour for the fee and notice fields since #1002.
  This is the intended behaviour per this spec, not a regression.
- Rollback: revert this PR. No data was moved or migrated, so nothing needs
  restoring.
