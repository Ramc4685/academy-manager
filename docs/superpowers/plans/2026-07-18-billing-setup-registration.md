# Billing Setup — Registration & Charge Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or executing-plans. Follow the **v2-persona-slice** skill for backend DDD/route conventions. Steps use checkbox (`- [ ]`) tracking.

**Goal:** Ship an admin "Billing Setup" page that shows each paying parent's Stripe registration status (no account / account-no-card / card-on-file), plus outstanding balance & autopay, and offers the right per-row action (invite / add-card reminder / charge now / enable autopay).

**Architecture:** A new billing-context read use case assembles per-parent rows by joining `parent_billing_customers`, an identity port (has-login-account), an enrollment port (student roster), and the billing ledger (outstanding balance). New admin routes expose the list + 3 action endpoints, delegating to existing use cases (`SendLoginInvite`, `ChargeInvoiceViaAutopay`, autopay enrollment transition) plus one thin add-card-reminder use case. New frontend admin page renders it.

**Tech Stack:** Python 3.12 / FastAPI / Motor (Mongo) / pydantic v2 backend; Next.js / React / TypeScript frontend. Design spec: `docs/superpowers/specs/2026-07-18-billing-setup-registration-design.md`.

## Global Constraints

- Everything tenant-scoped: resolve `academy_id` via existing admin deps; never read/write cross-tenant.
- Billing context must NOT import identity/enrollment contexts directly — cross-context signals go through Protocol ports wired in composition (`backend/v2/composition/admin.py`). Enforced by import-linter.
- "Registered" (green) == parent has a primary saved payment method on `parent_billing_customers` (display fields from migration 0144). No raw PAN read.
- Follow existing admin route patterns: `APIRouter(tags=[...])`, `Depends(get_admin_use_cases)`, response models in `interfaces/admin/views.py`, register in `interfaces/admin/router.py`.
- No new Mongo migration — fields exist via 0129/0142/0144.

---

### Task 1: Billing-context read model + ports

**Files:**
- Create: `backend/v2/contexts/billing/application/use_cases/billing_setup_registration.py`
- Test: `backend/v2/tests/unit/test_billing_setup_registration.py`

**Interfaces produced:**
- `RegistrationState = Literal["no_account", "account_no_card", "card_on_file"]`
- `BillingSetupRow(BaseModel, frozen)`: `parent_id: str`, `parent_name: str`, `parent_email: str | None`, `students: list[BillingSetupStudent]`, `registration_state: RegistrationState`, `card_label: str | None`, `card_last4: str | None`, `autopay_active: bool`, `outstanding_balance_cents: int`, `last_invited_at: datetime | None`
- `BillingSetupStudent(BaseModel, frozen)`: `student_id: str`, `full_name: str`
- `BillingSetupSummary(BaseModel, frozen)`: `families_total: int`, `families_registered: int`, `families_no_card: int`, `outstanding_total_cents: int`
- `BillingSetupPage(BaseModel, frozen)`: `rows: list[BillingSetupRow]`, `summary: BillingSetupSummary`, `next_cursor: str | None`
- Ports (Protocols defined in this module or `application/ports.py`):
  - `LoginAccountDirectory.login_account_parent_ids(academy_id) -> set[str]` (batch)
  - `ParentStudentRoster.students_for_parents(parent_ids, *, academy_id) -> dict[str, list[BillingSetupStudent]]`
  - Reuse existing `ParentStripeCustomerRepository` (billing) for customers/cards/autopay; reuse ledger repo for outstanding balances (add a batch method if none exists: `outstanding_by_parent(academy_id) -> dict[str, int]`).
- Use case `ListBillingSetup.execute(*, academy_id, status_filter: RegistrationState | Literal["all"] = "all", q: str | None = None, cursor: str | None = None, limit: int = 50) -> BillingSetupPage`

**Status derivation (pure, unit-tested):**
- card present (primary `payment_method_label`/`last4` or primary autopay method) → `card_on_file`
- else has login account → `account_no_card`
- else → `no_account`
- `autopay_active` = `autopay_enrollment_status == "active"`

- [ ] **Step 1:** Write failing unit tests for status derivation covering all three states + autopay_active true/false + outstanding sum, using fake in-memory ports/repos. Name states explicitly.
- [ ] **Step 2:** Run `pytest backend/v2/tests/unit/test_billing_setup_registration.py -v` → FAIL.
- [ ] **Step 3:** Implement the models, ports, and `ListBillingSetup` (batch-load customers, login-account set, rosters, balances; derive state; apply status_filter + name `q`; cursor pagination matching admin directory convention).
- [ ] **Step 4:** Run tests → PASS.
- [ ] **Step 5:** Commit `feat(billing): billing-setup registration read model + ports`.

### Task 2: Add-card reminder use case

**Files:**
- Create: `backend/v2/contexts/billing/application/use_cases/send_add_card_reminder.py` (or place in identity if the invite-email port lives there — follow where `SendLoginInvite` composes email). Prefer billing since it needs the card-setup checkout link.
- Test: `backend/v2/tests/unit/test_send_add_card_reminder.py`

**Interfaces produced:**
- `SendAddCardReminder.execute(*, academy_id, parent_id) -> InviteEmailOutcome` — builds the existing parent autopay/card-setup checkout link (reuse `StartSubscriptionCheckout` / autopay setup entry) and sends via the existing invite/email port. Idempotent; returns outcome with `failed_reason` on failure.

- [ ] **Step 1:** Failing test: given a parent with a customer but no card, execute sends one email with the card-setup link; on email-port failure returns `ok=False`.
- [ ] **Step 2:** Run test → FAIL.
- [ ] **Step 3:** Implement, reusing the existing checkout-link builder and email port (no new Stripe flow).
- [ ] **Step 4:** Tests → PASS.
- [ ] **Step 5:** Commit `feat(billing): add-card reminder use case`.

### Task 3: Composition wiring

**Files:**
- Modify: `backend/v2/composition/admin.py` — wire `ListBillingSetup`, `SendAddCardReminder`, and the identity/enrollment port adapters (implement the Protocols using existing identity user repo + enrollment roster reads). Expose on `AdminUseCases`.
- Modify: `backend/v2/interfaces/admin/deps.py` — add the new callables to `AdminUseCases`.

- [ ] **Step 1:** Add port adapter classes (identity has-account, enrollment roster) in composition, constructed from existing repos.
- [ ] **Step 2:** Wire the two use cases into `AdminUseCases`; keep `import-linter` green (billing imports only its own ports).
- [ ] **Step 3:** Run `pytest backend/v2/tests/ -k "composition or admin" -q` and the import-linter check → PASS.
- [ ] **Step 4:** Commit `feat(billing): wire billing-setup use cases in admin composition`.

### Task 4: Admin routes

**Files:**
- Create: `backend/v2/interfaces/admin/billing_setup_routes.py`
- Modify: `backend/v2/interfaces/admin/router.py` (import + `include_router`)
- Modify: `backend/v2/interfaces/admin/views.py` (response/request models mirroring the read model)
- Test: `backend/v2/tests/interface/test_admin_billing_setup.py`

**Endpoints** (all `Depends(get_admin_use_cases)`, tenant-scoped):
- `GET /admin/billing/setup?status=&q=&cursor=&limit=` → `BillingSetupPage` view (+ summary)
- `POST /admin/billing/setup/{parent_id}/invite` → context-aware: no account → `SendLoginInvite`; account-no-card → `SendAddCardReminder`. Returns outcome + refreshed `last_invited_at`.
- `POST /admin/billing/setup/{parent_id}/charge` → `ChargeInvoiceViaAutopay` on outstanding balance. Guard: 400 if no card or zero balance. Return `ChargeResult` view.
- `POST /admin/billing/setup/{parent_id}/autopay/enable` → autopay enrollment transition to active. Guard: 400 if no card.

- [ ] **Step 1:** Write failing interface tests: list returns rows+summary; charge-no-card→400; charge-zero-balance→400; invite dispatches login-invite when no account and add-card-reminder when account-no-card; autopay-enable-no-card→400. Reuse `tests/interface/test_admin_billing.py` harness/factories.
- [ ] **Step 2:** Run `pytest backend/v2/tests/interface/test_admin_billing_setup.py -v` → FAIL.
- [ ] **Step 3:** Implement routes + views; register router.
- [ ] **Step 4:** Tests → PASS. Also run full `pytest backend/v2/tests/interface/test_admin_billing.py -q` to confirm no regression.
- [ ] **Step 5:** Commit `feat(billing): Billing Setup admin endpoints`.

### Task 5: Frontend — API client + page

**Files:**
- Modify/Create: `frontend/lib/api/...` admin client — add `getBillingSetup`, `billingSetupInvite`, `billingSetupCharge`, `billingSetupEnableAutopay` (follow existing admin API client patterns, e.g. `frontend/lib/api/admin.ts`).
- Create: admin page component + route under the existing admin app dir (mirror an existing billing admin page, e.g. the billing health / payments page location).
- Add nav entry alongside existing billing admin pages.

**UI (per spec):** summary header; rows grouped by parent with student chips; columns status badge / card `Brand ···· 4242` / autopay badge / outstanding balance / actions; filters All / Not invited / No card / Chargeable + name search; actions adapt to state (invite label reflects sub-case; Charge now only when card+balance>0; Enable autopay only when card & not active); "Invited {date}" with resend.

- [ ] **Step 1:** Add API client functions with types matching the backend views.
- [ ] **Step 2:** Build the page (loading/empty/error states), wire filters + actions with optimistic toasts surfacing decline/failure reasons.
- [ ] **Step 3:** Add nav entry + route.
- [ ] **Step 4:** Typecheck/lint (`pnpm -C frontend lint` / tsc) → PASS. Verify in preview (admin Billing Setup page renders, filters work, an action fires against a stub).
- [ ] **Step 5:** Commit `feat(billing): Billing Setup admin page`.

### Task 6: Verify + PR

- [ ] Run backend suite for touched areas: `pytest backend/v2/tests/unit/test_billing_setup_registration.py backend/v2/tests/unit/test_send_add_card_reminder.py backend/v2/tests/interface/test_admin_billing_setup.py backend/v2/tests/interface/test_admin_billing.py -q`.
- [ ] Frontend typecheck/lint green.
- [ ] `graphify update .`
- [ ] Push branch, open PR against `main` with summary + test plan.

## Self-Review

- **Spec coverage:** status model → Task 1; add-card reminder → Task 2; ports/boundaries → Tasks 1+3; endpoints → Task 4; page/UI → Task 5; error handling (decline reasons, guards) → Tasks 4+5; tests → each task; rollout (no migration) → header/constraints. ✅
- **Placeholders:** none (test intent + signatures specified; executor fills code following named patterns).
- **Type consistency:** `BillingSetupRow`/`BillingSetupStudent`/`BillingSetupSummary`/`BillingSetupPage`, `RegistrationState`, `ListBillingSetup.execute(...)`, `SendAddCardReminder.execute(...)` used consistently across tasks.
