# MT1 — Drain the composition root (billing math, reports, payouts, email adapters → contexts)

Status: IN PROGRESS — Phase A DONE (PR #TBD, 2026-07-27); Phases B–E TODO
Size: L · Depends on: none (Phase E benefits from C4 landing first) · Tracker: ../TRACKER.md

## Problem

`backend/v2/composition/admin.py` is 7,203 lines (grown from 6,679 at audit time). Per AGENTS.md DDD rules, composition modules should be pure wiring (instantiate infrastructure, inject into application use cases, return closures for interfaces). Instead this file contains real business logic — money math, KPI/report aggregation pipelines, payout calculation, and inline email adapters — outside every enforced boundary: import-linter contracts (`backend/pyproject.toml` `[tool.importlinter]`) cover `contexts.*.{domain,application,infrastructure}` and `interfaces`, but have **no contract mentioning `backend.v2.composition`**, and the structural tenancy test (`backend/v2/tests/test_no_raw_tenant_mongo_access.py`) blanket-exempts `composition/admin.py` via `APPROVED_COMPOSITION_EXCEPTIONS`.

## Current behavior (verified 2026-07-20; line numbers are current, shifted ~+23 from audit doc)

Inventory of non-wiring code in `backend/v2/composition/admin.py`:

- **Money math (pure functions, :718–1080):** `_month_bounds` :718, `_money_to_cents` :730, `_payment_discount_cents` :736, `_payment_received_cents` :743, `_payment_final_amount_cents` :755, `_payment_collected_cents` :773, `_payment_outstanding_cents` :785, `_invoice_status_for_admin` :795, `_invoice_amount_cents` :804, `_invoice_final_amount_cents` :812, `_invoice_paid_cents` :816, `_invoice_outstanding_cents` :822, `_invoice_provider_keys` :828, `_payment_provider_keys` :841, `_payment_revenue_net_cents` :856, `_invoice_to_admin_payment_row` :863, plus date/window helpers :914–1080 and `_cents_to_dollars` :2456, `_round_money_minor` :3297. All take plain dicts, no I/O — trivially movable.
- **Reports KPI/read-model pipelines (Mongo aggregation, :619–2996):** `_make_reports_kpis` :619, `_AdminEffectiveRevenueQuery` :1081, `_make_reports_dashboard` :1517, `_make_projected_income_report` :2025, `_make_refunds_report` :2162, `_make_revenue_by_category_report` :2274, `_make_deposit_slip_report` :2390, `_make_financial_report_csv` :2471, `_make_session_economics_report` :2654, `_allocate_report_amount` :2946, `_make_list_enrollment_events` :2970. Each is a factory taking raw `AsyncIOMotorDatabase` and running raw pipelines on tenant-owned collections (payments, enrollments, attendance, waivers…).
- **Payout logic (:2997–3315):** `_MongoPayableOccurrenceQuery` :2997, `_MongoCoachRateRepository` :3128, `_ConnectedAccountGatewayReader` :3162, `_ConnectedAccountGatewayDisabler` :3180, `_FinancePayoutCalculator` :3205, `_MonthlyCoachOccurrenceReaderAdapter` :3243 (raw aggregation deciding "paying coach" and clock-derived completion — business rules), `_occurrence_session_id` :3291, `_effective_occurrence_status` :3301.
- **Inline email adapters:** `_LoginInviteEmailAdapter` :465, `_InvoiceEmailAdapter` :497, a dunning-email adapter with HTML bodies inline :~530–617, and `_AddCardReminderEmailAdapter` :4674 (defined *inside* `compose_admin` :3316). These compose subjects/HTML bodies — communications-domain behavior.
- Target contexts exist and are conventional: `backend/v2/contexts/billing/{application,domain,infrastructure}`, `contexts/finance/...`, `contexts/communications/{application,infrastructure}` (existing send ports: `resend_send_port.py`, `stub_send_port.py`). Tenancy base: `backend/v2/shared/tenancy/repository.py` (`TenantScopedRepository`, injects `academy_id` from ContextVar; `_find_many_in_collection` helper exists for cross-collection reads).
- Import-linter: `root_packages = ["backend"]`, contracts are `type = "forbidden"` lists (see `backend/pyproject.toml` Rules 1–4b). Nothing constrains what may import `composition` or what `composition` may contain.

## Proposed change

Extract each cluster into its owning context, leaving `compose_admin` as pure wiring (imports + instantiation + closure assembly). Finish by adding an import-linter contract that freezes the new shape. Each phase is an independent PR; order matters only where noted.

## Implementation steps (phased — each phase = one PR)

**Phase A — billing money math → `contexts/billing/application` (S).**
1. Create `backend/v2/contexts/billing/application/admin_money.py` (or split `payment_amounts.py` / `invoice_amounts.py`). Move the pure functions listed above (:718–1080 block, `_cents_to_dollars`, `_round_money_minor`) verbatim; make them public (drop leading underscore) with the same signatures.
2. In `composition/admin.py`, delete the bodies and import from the new module (temporary aliases `_money_to_cents = money_to_cents` keep the diff mechanical; remove aliases in the same PR by search-replace of call sites).
3. Add focused unit tests in `backend/v2/tests/contexts/billing/` for the tricky ones (`_invoice_outstanding_cents` status handling, `_payment_final_amount_cents`, `_invoice_to_admin_payment_row`). These are the money-path semantics the audit called out — pin them before anything else moves.

**Phase B — reports KPI pipelines → a billing read-model module (M).**
1. Create `backend/v2/contexts/billing/infrastructure/admin_reports_read_model.py` with classes extending `TenantScopedRepository` (one class per report family is fine: `AdminKpiReadModel`, `AdminReportsDashboardReadModel`, `AdminFinancialReportsReadModel`, `SessionEconomicsReadModel`). Aggregations must inject `academy_id` via `current_academy_id()` in every `$match` (several factories already do — preserve exactly; the guarded functions listed in `test_hardened_admin_composition_paths_use_request_tenant_not_default` must keep using `current_academy_id`).
2. Move the `_make_reports_*` factory bodies into methods; the composition closure becomes `read_model = AdminKpiReadModel(db); get_reports_kpis = read_model.get_kpis`.
3. Do this in 2–3 PRs if reviews get large (KPIs+dashboard, then the five financial reports, then session-economics+enrollment-events). Behavior-preserving: contract tests in `backend/v2/tests` that exercise real composition closures must pass unchanged.
4. Since `contexts/*/infrastructure` is exempt in `test_no_raw_tenant_mongo_access.py`, the move alone doesn't tighten enforcement — MT4 does. But it removes the pipelines from the `APPROVED_COMPOSITION_EXCEPTIONS` blast radius.

**Phase C — payout logic → `contexts/finance` (M).**
1. Move `_MongoPayableOccurrenceQuery`, `_MongoCoachRateRepository`, `_ConnectedAccountGatewayReader/Disabler`, `_MonthlyCoachOccurrenceReaderAdapter` (+ `_occurrence_session_id`, `_effective_occurrence_status`, `_optional_str`) into `contexts/finance/infrastructure/` (extend `TenantScopedRepository` where they filter by `academy_id` — note `_MonthlyCoachOccurrenceReaderAdapter.coaches_with_occurrences` takes explicit `academy_id` kwarg; keep that signature, it is the MT4-approved pattern).
2. Move `_FinancePayoutCalculator` into `contexts/finance/application/` — it wraps a compute use case and re-shapes lines; it's application logic, not wiring. Hoist the local `@dataclass _Row` and `from dataclasses import dataclass` inside the method to module level.
3. Wire in `compose_admin` by import + instantiation only.

**Phase D — inline email adapters → `contexts/communications/infrastructure` (S).**
1. Move `_LoginInviteEmailAdapter` :465, `_InvoiceEmailAdapter` :497, the dunning adapter :~530, and `_AddCardReminderEmailAdapter` :4674 (un-nest it from `compose_admin`) into e.g. `contexts/communications/infrastructure/transactional_email_adapters.py`, alongside `resend_send_port.py`.
2. These adapters bridge other contexts' ports (identity `InviteEmailPort`, billing dunning) to communications' `EmailSendPort` — check import direction doesn't violate Rules 1–3 (`infrastructure` may import other contexts' `application` ports per current contracts; if a cross-context domain import appears, define the port protocol locally instead).
3. Subject/HTML body templates move with them; add a unit test asserting HTML-escaping of user-supplied fields (audit "Not re-verified" item on Resend HTML escaping — cheap to close here).

**Phase E — import-linter contract for composition (S; do last, ideally after C4 removes remaining raw reads).**
1. Add to `backend/pyproject.toml` (matching the existing style — `root_packages = ["backend"]`, dotted paths, `type = "forbidden"`):
   ```toml
   # Rule 5: Composition is pure wiring — it may not be imported by
   # contexts (wiring is the outermost layer), and nothing outside
   # interfaces/main may depend on it.
   [[tool.importlinter.contracts]]
   name = "composition-is-outermost"
   type = "forbidden"
   source_modules = [
       "backend.v2.contexts",
       "backend.v2.shared",
   ]
   forbidden_modules = ["backend.v2.composition"]
   ```
   (Import-linter cannot forbid "business logic in a module", only import direction — so pair the contract with a size tripwire: a small test asserting `composition/admin.py` line count stays under a ratchet value, e.g. `assert line_count < 2500`, lowered as phases land.)
2. Shrink `APPROVED_COMPOSITION_EXCEPTIONS` in `test_no_raw_tenant_mongo_access.py` as raw reads leave `composition/admin.py` (coordinate with MT4/C4 — don't remove entries other tracks still rely on).
3. Verify with `cd backend && lint-imports --config pyproject.toml` (same invocation as CI, `.github/workflows/production.yml:123`).

## Files to change

- `backend/v2/composition/admin.py` (shrinks each phase)
- New: `backend/v2/contexts/billing/application/admin_money.py`
- New: `backend/v2/contexts/billing/infrastructure/admin_reports_read_model.py` (or several)
- New: `backend/v2/contexts/finance/infrastructure/payout_read_models.py`, `contexts/finance/application/payout_calculator.py`
- New: `backend/v2/contexts/communications/infrastructure/transactional_email_adapters.py`
- `backend/pyproject.toml` (Phase E contract)
- `backend/v2/tests/test_no_raw_tenant_mongo_access.py` (Phase E exception shrink)
- New tests under `backend/v2/tests/contexts/{billing,finance,communications}/`

## Tests & verification

- Per phase: `cd backend && pytest v2/tests` (2,429 tests, all green today) and `ruff check v2`.
- `lint-imports --config pyproject.toml` after every phase (moves can silently create forbidden domain↔infrastructure imports).
- Contract tests over real composition closures (existing suite) are the behavior lock — no report/payout/email output may change.
- `graphify update .` after each phase per repo CLAUDE.md.

## Risks / rollback

- Line numbers drift constantly (file grew 500+ lines since the audit) — re-run `grep -n "^def \|^class " backend/v2/composition/admin.py` before starting any phase; do not trust the numbers above blindly.
- Phase B aggregations embed subtle tenant/window semantics; move verbatim, refactor later. Any behavior diff in financial reports is a defect.
- Cross-context port imports in Phase D may trip existing contracts — resolve by local protocol, never by widening a contract.
- Rollback: each phase is a self-contained PR; revert the PR. No data migrations involved.

## PR checklist

- [ ] Release note (per AGENTS.md `docs/release-notes/YYYY-MM-DD-<slug>.md`, written before push)
- [ ] TRACKER.md updated
- [ ] Plan Status flipped to DONE
