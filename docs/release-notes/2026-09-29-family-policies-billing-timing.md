# Family policies: Waivers embed, drop-outcome move, welcome-email default (Settings overhaul Phase 3 PR 10)

PR: #1006

## What changed

Full lane, mockup sections "2 Billing rules" and "5 Family policies":

- **Settings tab renamed:** `Self-service` -> `Family policies` (key
  `self-service` -> `family-policies`). `?panel=self-service` still works —
  `RETIRED_SETTINGS_PANELS` maps it to `family-policies`. `/admin/settings/self-service`
  (the old bookmark redirect page) redirects to `?panel=family-policies`.
- **Family policies is now separate cards**, per the mockup: "Absences &
  makeups" (now also carrying the welcome-email default, below), "Holds"
  (`DeparturePolicyPanel`, unchanged, owner-gated as today), "What parents can
  do in the app" (#1003, unchanged), "Registration & waivers" (the embedded
  waiver management UI, see below), and a link card "Cancellation fee &
  notice — now in Billing rules".
- **"When a cancellation takes effect" (`cancellation_effective_timing`)
  moved to Billing rules**, owner-only and audited through the existing
  `UpdateBillingRules` / `billing_audit_log` path — the same pattern PR #1002
  used for the cancellation fee. `PUT /admin/self-service/policy` refuses a
  **changed** value with a 422 naming the field and pointing at Billing
  rules; an unchanged value in a full resubmit still passes.
- **"Default when staff drop a student" (`drop_default_outcome`) also moved
  to Billing rules**, same pattern. It already existed as a setting — the
  Holds card's `EnrollmentDeparturePolicy`, edited via the whole-object
  `PUT /admin/enrollment/departure-policy` with no audit trail. Now:
  - `UpdateEnrollmentDeparturePolicyCommand` (the Holds write) has every
    field optional and applies only what's sent, so it can be a genuine
    partial write instead of a whole-object one
    (`backend/v2/contexts/enrollment/application/use_cases/departure_policies.py`).
  - The Holds route (`departure_policy_routes.py`) no longer writes
    `drop_default_outcome` — it still *accepts* the field (an old client
    keeps working) but a **changed** value 422s pointing at Billing rules,
    exactly like the self-service cancellation-terms pattern; unchanged
    passes through untouched.
  - Billing rules' "Leaving and pausing" card gets a new row, "Default when
    staff drop a student", written through `UpdateBillingRules` and audited
    in `billing_audit_log`
    (`backend/v2/contexts/billing/application/use_cases/billing_rules.py`,
    `backend/v2/composition/billing_rules.py` — a new
    `_DropDefaultOutcomeAdapter` wraps the same partial
    `UpdateEnrollmentDeparturePolicy` use case, writing only this field).
  - The Holds card's own "Default Drop outcome" select is removed from
    `departure-policy-panel.tsx`; `drop_default_outcome` still round-trips
    through the form state so a Holds save doesn't drop it, it's just no
    longer editable there.
- **Waivers move into Family policies.** The waiver template
  list/editor/publish UI is extracted, unchanged, from
  `app/(admin)/admin/waivers/page.tsx` into
  `components/admin/waivers/waivers-management.tsx` (`WaiversManagement`),
  reused by both the new "Registration & waivers" card and (still) the
  waiver detail/signature sub-routes' "Open" links. `/admin/waivers` itself
  now redirects (client-side) to `?panel=family-policies`. `/admin/waivers/
  [waiverId]` and `/admin/waivers/signatures/[signatureId]` are untouched
  and still work. The sidebar's standalone "Waivers" nav item
  (`components/admin/screen-meta.ts`) is removed — its `metaForPath` entry
  stays, for the sub-routes' title/breadcrumb. The dashboard attention item
  and the setup-checklist "Waiver" step now link straight at
  `/admin/settings?panel=family-policies` instead of the (now-redirecting)
  `/admin/waivers`.
- **Welcome-email absence & makeup policy gets an academy-level default.**
  It was previously per-class only (`Session.absence_policy`, used verbatim
  in `render_welcome_email`). `ParentSelfServicePolicy` gains
  `welcome_email_absence_policy_default` (default `""`, admin-editable,
  not owner-gated — same tier as the existing self-service text fields), and
  `render_welcome_email` falls back to it only when the class's own field is
  empty: `session.absence_policy or academy_absence_policy_default`. The
  class value always wins. `EnrollmentWelcomeEmailAdapter` reads the policy
  defensively (a store hiccup skips only the fallback text, never blocks
  sending); wired in `composition/roster_notifications.py` via a plain
  `GetSelfServicePolicy` over the same Mongo store Family policies writes.
  Editable from the "Absences & makeups" card.
- **Offline payments card:** unchanged, stays in Billing rules.

## Tests

- Backend:
  `backend/v2/tests/application/test_billing_rules.py` (drop-outcome row +
  write + no-op cases, alongside the existing cancellation-timing ones),
  `backend/v2/tests/interface/test_admin_billing_rules_routes.py` (GET row
  shape, owner-only PUT, audit),
  `backend/v2/tests/interface/test_admin_departure_policy_routes.py` (new
  file: Holds PUT no longer writes `drop_default_outcome`, an unchanged
  resubmit passes, a changed one 422s naming Billing rules, owner-only),
  `backend/v2/tests/interface/test_admin_self_service_policies.py` (updated
  default-policy shape),
  `backend/v2/tests/unit/test_enrollment_welcome_email.py` (class-wins,
  academy-default-fills-in, neither-set-means-no-block, adapter reads the
  policy store and survives its failure),
  `backend/v2/tests/interface/test_admin_dashboard_attention.py` (updated
  href). All green:
  `backend/.venv/bin/pytest -n 6 backend/v2/tests/application/test_billing_rules.py backend/v2/tests/interface/test_admin_billing_rules_routes.py backend/v2/tests/interface/test_admin_departure_policy_routes.py backend/v2/tests/interface/test_admin_self_service_policies.py backend/v2/tests/interface/test_admin_dashboard_attention.py backend/v2/tests/interface/test_admin_setup_checklist.py backend/v2/tests/unit/test_enrollment_welcome_email.py backend/v2/tests/application/test_self_service_policies.py backend/v2/tests/unit/test_invoice_email_payment_instructions.py backend/v2/tests/interface/test_admin_departure_delete_owner_gate.py backend/v2/tests/application/test_enrollment_holds.py` —
  177 passed.
- Backend mypy: `mypy -p backend.v2 | mypy-baseline filter --allow-unsynced`
  — 0 new violations.
- Frontend: `frontend/lib/billing-rules-form.node-test.mjs` (drop-outcome
  choice-row tests) and `frontend/lib/self-service-policy-form.node-test.mjs`
  (welcome-email default round-trip/diff tests) — 49 passed via
  `node --test`. `pnpm typecheck` and `pnpm eslint` on every changed file are
  clean.
- e2e (updated, not run here — no local dev server in this pass):
  `admin-shell.spec.ts` (Waivers nav item gone; dashboard attention href),
  `admin-waivers.spec.ts` and `saas-parent-waivers.spec.ts` (navigate to
  `?panel=family-policies` instead of `/admin/waivers`, with the sibling
  self-service-policy/departure-policy cards stubbed),
  `saas-launch-route-matrix.spec.ts` (waivers route matrix entry follows the
  redirect; added the `waivers/templates` stub),
  `admin-setup-checklist.spec.ts` and `a11y-axe.spec.ts` (fixture hrefs),
  `screen-meta.test.ts` (Waivers nav item removed).
  **Not done:** `admin-shell.spec.ts`'s generic `SETTINGS_PANELS` sweep
  still omits `family-policies` (pre-existing gap flagged by the reviewer,
  not newly caused here) — adding it needs stubbing four more endpoints for
  that one generic test and was judged not worth the added flake risk in
  this pass. No Playwright run and no screenshots were captured (no dev
  server in this environment).

## Deploy notes

- No migration. `drop_default_outcome` and
  `welcome_email_absence_policy_default` are read with `getattr`/Pydantic
  defaults, so no backfill: BLNO and every existing academy behave exactly
  as today until an owner or admin visits the new UI.
- `cancellation_effective_timing` already defaults to `"end_of_period"`
  (unchanged from the prior pass).
- An admin (non-owner) who still has `?panel=self-service` bookmarked, or
  `/admin/waivers`, lands on Family policies — same content, same
  permissions, just relocated.

## Risk / rollback

- Main risk: an old client that PUTs a *changed* `drop_default_outcome` to
  `/admin/enrollment/departure-policy` now gets a 422 instead of a 200 —
  intended per this spec, same shape as the cancellation-terms move.
- Second risk: the sidebar Waivers nav item is gone; anyone with it bookmarked
  or muscle-memoried still reaches the same UI via `/admin/waivers`'s
  redirect or Settings -> Family policies.
- Rollback: revert this PR. No data was moved or migrated, so nothing needs
  restoring.
