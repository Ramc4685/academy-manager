# Families Directory Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/admin/families` the single admin surface for parent identity, login, and billing, so `/admin/parents` and `/admin/users?role=parent` redirect there and `AdminUsersDirectory` drops parents entirely.

**Architecture:** The Families list stays backed by the existing `/admin/billing/setup` read model (`ListBillingSetup` in `backend/v2/contexts/billing/application/use_cases/billing_setup_registration.py`), extended with phone, a login-state facet, and search over phone/child name; its composition wiring moves out of `composition/admin.py` (at its 4318/4500-line cap) into `composition/families.py`, late-bound onto `AdminUseCases` the same way `stop_all_classes` already is in `main.py`. The Family detail page's `FamilyHeader` becomes the identity strip (login badge, mailto/tel, send/resend invite, send password reset, edit contact), fed by `MongoFamilyBillingReadModel.build` / `build_family_billing_view` in the billing context. `/admin/parents` and `/admin/users?role=parent` become redirects to `/admin/families`, and `AdminUsersDirectory` drops its `parent` role tab and `fixedRole="parent"` support.

**Tech Stack:** FastAPI/Pydantic (backend/v2), Next.js 16 + TanStack Query + Tailwind (frontend), Playwright e2e, pytest.

## Global Constraints

- No new `Family` model: 1 parent `User` + `Student.parent_id` rows, unchanged (spec §2).
- `/admin/parents` and `/admin/users?role=parent` redirect to `/admin/families` (spec §2, §7 step 3).
- `FamilyHeader` gains identity fields; no new panel is created (spec §2, §4).
- Roles are not editable on the family page — a parent who is also a coach is managed from Users (spec §4).
- `AdminUsersDirectory` drops the Parents pill and `fixedRole="parent"`; "Add parent" moves to the Families list (spec §2, §5).
- Nothing in this backend slice may add lines to `composition/admin.py` (4318 lines; budget 4500, enforced by `backend/v2/tests/structural/test_composition_is_wiring.py::test_admin_composition_stays_within_line_budget`) — new/moved wiring goes in `composition/families.py`.
- Any `app/` route behaviour change (a page that becomes a redirect) requires the same-commit update to `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` (backend tests `backend/v2/tests/unit/test_audit_inventory_manifest.py` and `test_inventory_manifest_summary.py`).
- v2 routes return 404, never 403, for wrong persona / other tenant. Every new route below uses `Depends(require_persona("admin"))`, and the family reader returns `None` → 404 for a parent outside the tenant. Task 3.7 adds the explicit tenant-scoping test spec §9 asks for.
- No migration in this plan. (If one were ever added: prod runs migrations by hand — `V2_RUN_MIGRATIONS_ON_BOOT` is false in production — so the release note would have to name each file.)
- **Cross-plan contracts this plan owes / does not owe** (build order for the four 2026-09-10 admin-UX plans is 1 → 2 → 4 → 3; this is plan 2):
  - The Families **list component's final path is `frontend/app/(admin)/admin/families/page.tsx`** and its row model is `BillingSetupRow` (`backend/v2/contexts/billing/application/use_cases/billing_setup_registration.py`), wired through `composition/families.py`. This plan modifies that page in place — it does **not** move, rename or split it — so any later plan (e.g. plan 3, `2026-09-10-birthdays-and-profile-nudges.md`, Task 11) should reference those exact paths.
  - **Owner decision 2026-09-10 — a "Needs attention" sort IS built here** (Task 12b). Spec §3's list gets a registration-state filter, a `login_state` filter, a name/email/phone/child search, AND a sort toggle whose "Needs attention" mode orders by: outstanding balance desc → never-invited → autopay failing → profile incomplete → name. Plan 3 extends the *profile incomplete* term by reading `profile_nudges`; it does not build the sort. Default sort stays alphabetical by name so the list is predictable for lookup.
  - **Owner decision 2026-09-10 — parents with no students still appear.** The list is a list of parent *users*, not a list of rosters. A parent invited but not yet enrolled, or whose only child's record was removed, must not vanish when the Users directory's Parents pill goes away (Task 12c). Their row shows "No students on file" and still offers invite/reset.
  - **"Move child to another family" is NOT built here.** Spec §6 lists it under "what this unblocks", and no task below implements it. Plan 4 (`2026-09-10-student-page-single-view.md`, Task 8) hard-gates its `ChangeParentPanel` removal on this action existing, so under the agreed order plan 4's Task 8 will correctly **skip** and `ChangeParentPanel` stays on the student page. If the owner wants it moved in this cycle, it needs its own slice — do not smuggle it into a task below.
- Commits end with the session's attribution trailer, currently
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. Use whatever the
  executing session's attribution instruction says; do not hardcode a stale model name.

## File structure

| File | Responsibility |
|---|---|
| `backend/v2/contexts/billing/application/ports.py` | Add `parent_phone` to `ParentRosterEntry`; add `ParentDirectoryFacts` model + `LoginAccountDirectory.parent_directory_facts` port method (phone + `login_invite_sent_at`) |
| `backend/v2/contexts/identity/infrastructure/mongo_user_repo.py` | New `list_parent_directory_facts(parent_ids, *, academy_id)` — bulk phone (from `users`) + `login_invite_sent_at` (from `academy_memberships`) |
| `backend/v2/contexts/billing/application/use_cases/billing_setup_registration.py` | Add `login_state` to `BillingSetupRow`; widen `q` search to phone + child name; add `login_state` filter param |
| `backend/v2/interfaces/admin/billing_setup_routes.py` | Add `login_state` query param + `parent_phone`/`login_state` DTO fields. The route keeps reading its use case off `AdminUseCases` (`use_cases.list_billing_setup`, guarded by `_required_callable`); only the *construction* of that object moves. |
| `backend/v2/composition/families.py` | Gains `_BillingSetupRosterAdapter` / `_BillingSetupLoginAccountAdapter` / `_BillingSetupCustomerAdapter` / `_BillingSetupAutopayAdapter` / `_BillingSetupBalanceAdapter` / `ListBillingSetup(...)` moved from `composition/admin.py`; also the `password_reset` + `contact_writer` wiring; `compose_admin_families` takes `list_admin_students` and `send_login_invite` and builds its own Mongo repos |
| `backend/v2/composition/admin.py` | Loses the ~225-line Billing Setup adapter block (lines 1775–1999) and the `ListBillingSetup(...)` call; keeps `_BillingSetupParentContactAdapter` / `_BillingSetupCardSetupLinkAdapter` (lines 2001–2030), which feed `send_add_card_reminder` and are unrelated |
| `backend/v2/interfaces/admin/deps.py` | `AdminUseCases.list_billing_setup` annotation widens to `ListBillingSetup \| None` (still no default — the dataclass has ~119 non-default fields after it) so `main.py` can late-bind it |
| `backend/v2/main.py` | Passes `list_admin_students` + `send_login_invite` into `compose_admin_families`; late-binds `app.state.admin.list_billing_setup = app.state.admin_families.list_billing_setup` after both are constructed (`AdminUseCases` is a plain `@dataclass`, not frozen — verified) |
| `backend/v2/contexts/billing/infrastructure/family_billing_read_model.py` | No change — `CustomerFacts` already carries `has_login_account` and `last_invited_at` (`family_billing.py` lines 192–193) |
| `backend/v2/contexts/billing/application/family_billing.py` | `build_family_billing_view` gains a `header.login` block; `family_actions` gains `send_password_reset` + `edit_contact` (new kwarg gets a default so existing callers/tests keep compiling) |
| `backend/v2/tests/unit/test_family_billing.py` | Existing `test_family_actions` assertions must be updated in the same commit — `edit_contact` is now always first in the returned list |
| `backend/v2/interfaces/admin/families_views.py` | `FamilyHeader` gains `login: FamilyLogin \| None = None`; `FamilyAction` gains `"send_password_reset"`, `"edit_contact"` |
| `backend/v2/interfaces/admin/families_routes.py` | New `POST /families/{parent_id}/password-reset` and `PATCH /families/{parent_id}/contact`; `AdminFamiliesServices` Protocol gains `password_reset` + `contact_writer`. Needs new imports: `from pydantic import BaseModel, Field` (the module imports neither today) |
| `frontend/lib/api/admin.ts` | `BillingSetupRow` gains `parent_phone`, `login_state`; `BillingSetupListParams` gains `login_state` |
| `frontend/lib/query/keys.ts` | `queryKeys.admin.billingSetup` must include `login_state` in the key — today it is `(params?: {status?, q?})` and would cache-collide across login filters |
| `frontend/lib/api/admin-families.ts` | `FamilyHeader` type gains `login`; `FamilyAction` union gains `"send_password_reset"` and `"edit_contact"`; add `sendFamilyPasswordReset`, `updateFamilyContact` calls |
| `frontend/app/(admin)/admin/families/page.tsx` | New column layout (Family / Contact / Login / Billing / Autopay / Outstanding / Actions), login-state filter, search placeholder update |
| `frontend/app/(admin)/admin/families/[parentId]/FamilyHeader.tsx` | mailto/tel links, login badge, "Send password reset", "Edit contact details" |
| `frontend/app/(admin)/admin/families/[parentId]/EditContactDialog.tsx` | New — name/phone edit dialog (email edit intentionally excluded, spec §4) |
| `frontend/app/(admin)/admin/families/[parentId]/page.tsx` | Wires the new header callbacks |
| `frontend/app/(admin)/admin/parents/page.tsx` | Redirect target changes to `/admin/families` |
| `frontend/app/(admin)/admin/users/page.tsx` | Redirects to `/admin/families` when `?role=parent` is present |
| `frontend/components/admin/AdminUsersDirectory.tsx` | Drops the "Parents" pill and `parent` from `CreatableRole`/`fixedRole` |
| `frontend/app/(admin)/admin/users/[userId]/page.tsx` | Parent pointer banner; `LoginInvitePanel` hidden for `role === "parent"` |
| `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` | No route added/removed, but `/admin/parents` (line 622) stops being a list and becomes a redirect — its `workflows` / `controls` / `states` / `risk_edges` / `acceptance` must be rewritten to the redirect shape already used by `/admin/billing-setup` (lines 228–250); `/admin/families` (line 252) gains the new Contact/Login columns, login filter and "Add parent" modal |
| `frontend/e2e/specs/admin-shell.spec.ts`, `saas-launch-route-matrix.spec.ts`, `admin-family-billing.spec.ts` | New/updated assertions for redirects, login badge, invite-from-header |
| `docs/release-notes/2026-09-10-families-directory-consolidation.md` | Release note (Task 12) |

---

### Task 1: Backend — phone + login_state + widened search on the Billing Setup roster

**Where phone and login-invite facts actually come from (verified this session — read this before writing code):**

- `ListAdminStudents.execute()` returns pages of `AdminStudentSummary`
  (`backend/v2/contexts/enrollment/application/use_cases/admin_directory.py` lines 31–52),
  which has `parent_name` and `parent_email` but **no `parent_phone`** — only the
  *detail* model `AdminStudentDetail` (line 131) carries `parent_phone`. So the roster
  adapter cannot get a phone from the student directory; a `getattr(student, "parent_phone", None)`
  would silently be `None` on every row and the spec §3 Contact column / phone search
  would never work.
- `login_invite_sent_at` is **not** on the `users` document either — `MongoUserRepository.record_login_invite`
  (line 732) writes it onto the **`academy_memberships`** doc, and
  `_to_admin_detail` (line ~727) reads it back from there. Spec §3's phrase "from the
  `users` document already read" is loose; the fact exists, on the membership row.
- `ParentBillingCustomerSnapshot.last_invited_at` maps to
  `parent_billing_customers.billing_setup_last_invited_at` — that is the **add-a-card**
  invite, a different event from the login invite. It must NOT be used to drive a
  "Login" column.

Therefore both facts come from one new bulk identity lookup, exposed through the
existing `LoginAccountDirectory` port (this is the port method the plan's file-structure
table promises).

**Files:**
- Modify: `backend/v2/contexts/billing/application/ports.py` (`ParentRosterEntry` at lines 71–75, `LoginAccountDirectory` at lines 90–95)
- Modify: `backend/v2/contexts/identity/infrastructure/mongo_user_repo.py` (new `list_parent_directory_facts`, next to `list_existing_user_ids` at line 282)
- Modify: `backend/v2/contexts/billing/application/use_cases/billing_setup_registration.py` (`BillingSetupRow` lines 46–62, `_registration_state` lines 82–87, `ListBillingSetup.execute` lines 108–231)
- Test: `backend/v2/tests/unit/test_billing_setup_registration.py` — **this file already exists** (327 lines). Do NOT create it and do NOT introduce new fake classes; append to it using its existing `FakeRoster` / `FakeLoginAccounts` / `FakeCustomers` / `FakeAutopay` / `FakeBalances` / `_make_use_case` helpers and its `ACADEMY_ID` constant.

**Interfaces:**
- Consumes: existing `ParentStudentRoster`, `LoginAccountDirectory` protocols (`ports.py`)
- Produces: `ParentDirectoryFacts` model in `ports.py`; `LoginAccountDirectory.parent_directory_facts(parent_ids, *, academy_id) -> dict[str, ParentDirectoryFacts]`; `BillingSetupRow.parent_phone: str | None`, `BillingSetupRow.login_state: Literal["never_invited", "invited", "active"]`; `ListBillingSetup.execute(..., login_state: Literal["all","never_invited","invited","active"] = "all")`; `q` now matches `parent_phone` and any `BillingSetupStudent.full_name`

Steps:

- [ ] 1.1 Read `backend/v2/tests/unit/test_billing_setup_registration.py` in full (327 lines) so the new tests reuse `_make_use_case` (line 105) and the `Fake*` classes verbatim. Read `_make_use_case`'s signature — the new tests must extend it, not replace it: add an optional `directory_facts: dict[str, ParentDirectoryFacts] | None = None` argument that `FakeLoginAccounts` returns from its new `parent_directory_facts` method. Then **append** these failing tests (they use `_make_use_case`, `FakeRoster` etc. from the file, so adjust the calls to that helper's real parameter names once you have read it):

```python
@pytest.mark.asyncio
async def test_search_matches_child_name() -> None:
    parents = [ParentRosterEntry(parent_id="p1", parent_name="Sharma Family")]
    students = {"p1": [BillingSetupStudent(student_id="s1", full_name="Aarav Sharma")]}
    use_case = _make_use_case(parents=parents, students=students)

    page = await use_case.execute(academy_id=ACADEMY_ID, q="aarav")

    assert [r.parent_id for r in page.rows] == ["p1"]


@pytest.mark.asyncio
async def test_search_matches_phone() -> None:
    parents = [
        ParentRosterEntry(parent_id="p1", parent_name="A"),
        ParentRosterEntry(parent_id="p2", parent_name="B"),
    ]
    facts = {
        "p1": ParentDirectoryFacts(parent_id="p1", phone="555-0101"),
        "p2": ParentDirectoryFacts(parent_id="p2", phone="555-0202"),
    }
    use_case = _make_use_case(parents=parents, directory_facts=facts)

    page = await use_case.execute(academy_id=ACADEMY_ID, q="0101")

    assert [r.parent_id for r in page.rows] == ["p1"]
    assert page.rows[0].parent_phone == "555-0101"


@pytest.mark.asyncio
async def test_login_state_active_when_has_account() -> None:
    parents = [ParentRosterEntry(parent_id="p1", parent_name="A")]
    use_case = _make_use_case(parents=parents, parent_ids_with_accounts={"p1"})

    page = await use_case.execute(academy_id=ACADEMY_ID)

    assert page.rows[0].login_state == "active"


@pytest.mark.asyncio
async def test_login_state_invited_uses_login_invite_not_billing_invite() -> None:
    """A billing "add your card" invite must NOT show as a login invite."""
    parents = [ParentRosterEntry(parent_id="p1", parent_name="A")]
    customers = [
        ParentBillingCustomerSnapshot(
            parent_id="p1", last_invited_at=datetime(2026, 1, 1, tzinfo=UTC)
        )
    ]
    use_case = _make_use_case(parents=parents, customers=customers)

    page = await use_case.execute(academy_id=ACADEMY_ID)

    assert page.rows[0].login_state == "never_invited"


@pytest.mark.asyncio
async def test_login_state_invited_when_login_invite_sent_but_no_account() -> None:
    parents = [ParentRosterEntry(parent_id="p1", parent_name="A")]
    facts = {
        "p1": ParentDirectoryFacts(
            parent_id="p1", login_invite_sent_at=datetime(2026, 1, 1, tzinfo=UTC)
        )
    }
    use_case = _make_use_case(parents=parents, directory_facts=facts)

    page = await use_case.execute(academy_id=ACADEMY_ID)

    assert page.rows[0].login_state == "invited"


@pytest.mark.asyncio
async def test_login_state_never_invited_by_default() -> None:
    parents = [ParentRosterEntry(parent_id="p1", parent_name="A")]
    use_case = _make_use_case(parents=parents)

    page = await use_case.execute(academy_id=ACADEMY_ID)

    assert page.rows[0].login_state == "never_invited"


@pytest.mark.asyncio
async def test_login_state_filter() -> None:
    parents = [
        ParentRosterEntry(parent_id="p1", parent_name="A"),
        ParentRosterEntry(parent_id="p2", parent_name="B"),
    ]
    use_case = _make_use_case(parents=parents, parent_ids_with_accounts={"p2"})

    page = await use_case.execute(academy_id=ACADEMY_ID, login_state="active")

    assert [r.parent_id for r in page.rows] == ["p2"]
```

  Add `ParentDirectoryFacts` to the file's existing `ports` import block and `from datetime import UTC, datetime` at the top.

- [ ] 1.2 Run it and confirm the new tests fail:
  `cd backend && .venv/bin/pytest v2/tests/unit/test_billing_setup_registration.py -q`
  Expected: `ImportError: cannot import name 'ParentDirectoryFacts'`. (Note: `ParentRosterEntry` is a plain pydantic v2 model with `extra` left at its default `"ignore"`, so passing an unknown kwarg would be silently dropped rather than raising — do not wait for a `TypeError`.) Confirm the **pre-existing 12 tests still pass**.

- [ ] 1.3 In `backend/v2/contexts/billing/application/ports.py`, add `parent_phone` to `ParentRosterEntry` (currently lines 71–75) and add the new facts model + port method:

```python
class ParentRosterEntry(BaseModel):
    model_config = {"frozen": True}

    parent_id: str
    parent_name: str
    parent_email: str | None = None
    parent_phone: str | None = None


class ParentDirectoryFacts(BaseModel):
    """Identity-directory facts the Families list shows next to billing state.

    ``login_invite_sent_at`` is the LOGIN invite (academy_memberships), which is
    a different event from ``ParentBillingCustomerSnapshot.last_invited_at``
    (the add-a-card billing invite).
    """

    model_config = {"frozen": True}

    parent_id: str
    phone: str | None = None
    login_invite_sent_at: datetime | None = None
```

  and extend the protocol (currently lines 90–95):

```python
class LoginAccountDirectory(Protocol):
    async def login_account_parent_ids(
        self, parent_ids: list[str], *, academy_id: str
    ) -> set[str]: ...

    async def has_login_account(self, parent_id: str, *, academy_id: str) -> bool: ...

    async def parent_directory_facts(
        self, parent_ids: list[str], *, academy_id: str
    ) -> dict[str, ParentDirectoryFacts]: ...
```

- [ ] 1.3b In `backend/v2/contexts/identity/infrastructure/mongo_user_repo.py`, add `list_parent_directory_facts` next to `list_existing_user_ids` (line 282). Read `list_existing_user_ids` first and reuse its exact alias `$or` shape (`user_id` / `auth_uid` / `firebase_uid` / `_id` as `ObjectId`) — a parent id can be any of those. Return, per input id, `{"phone": <users.phone>, "login_invite_sent_at": <academy_memberships.login_invite_sent_at>}`, joining `self._db["academy_memberships"]` on `{"academy_id": academy_id, "user_id": {"$in": aliases}, "status": "active"}` exactly as `record_login_invite` (line 732) and `_to_admin_detail` (line ~727) do. Return plain dicts or a small dataclass — the billing `ParentDirectoryFacts` model is built by the composition adapter, not here (identity must not import billing).

- [ ] 1.4 Run again — the import now resolves; the tests fail on `AttributeError: 'BillingSetupRow' object has no attribute 'login_state'` / `parent_phone` being `None`.

- [ ] 1.5 In `backend/v2/contexts/billing/application/use_cases/billing_setup_registration.py`, add the `LoginState` type and extend `BillingSetupRow` (currently lines 34, 46–62):

```python
RegistrationState = Literal["no_account", "account_no_card", "card_on_file"]
LoginState = Literal["never_invited", "invited", "active"]
```

  and add `ParentDirectoryFacts` to the existing `from ...ports import (...)` block (lines 23–31).

Add `parent_phone` and `login_state` to `BillingSetupRow`:

```python
class BillingSetupRow(BaseModel):
    model_config = {"frozen": True}

    parent_id: str
    parent_name: str
    parent_email: str | None = None
    parent_phone: str | None = None
    students: tuple[BillingSetupStudent, ...] = ()
    registration_state: RegistrationState
    login_state: LoginState = "never_invited"
    card_label: str | None = None
    card_last4: str | None = None
    autopay_active_count: int = 0
    autopay_eligible_count: int = 0
    outstanding_balance_cents: int = 0
    charge_invoice_id: str | None = None
    charge_amount_cents: int = 0
    charge_autopay_eligible: bool = False
    last_invited_at: datetime | None = None
```

Add a helper next to `_registration_state` (lines 82–87):

```python
def _login_state(*, has_login_account: bool, login_invite_sent_at: datetime | None) -> LoginState:
    if has_login_account:
        return "active"
    if login_invite_sent_at is not None:
        return "invited"
    return "never_invited"
```

- [ ] 1.6 In `execute`, thread the `login_state` filter parameter and pass `parent_phone`/`login_state` into each row. Change the signature (lines 108–117):

```python
    async def execute(
        self,
        *,
        academy_id: str,
        status_filter: RegistrationState | Literal["all"] = "all",
        login_state: LoginState | Literal["all"] = "all",
        q: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
        parent_id: str | None = None,
    ) -> BillingSetupPage:
```

Fetch the directory facts in BOTH branches of the `if parent_id is not None:` / `else:`
split (lines 118–151), right after `login_account_ids` is computed in each branch:

```python
            directory_facts = await self._login_accounts.parent_directory_facts(
                [parent_id], academy_id=academy_id
            )
```

```python
            directory_facts = await self._login_accounts.parent_directory_facts(
                parent_ids, academy_id=academy_id
            )
```

In the row-building loop (lines 159–201) compute `login_state_value` and pass both new
fields. **Leave every existing line in this loop in place** — `enrollments`, `balance`,
`active_count`, `eligible_count` and `charge_autopay_eligible` (lines 166–182) are
unchanged and are elided below only for brevity:

```python
        for parent in parents:
            customer = customers_by_parent.get(parent.parent_id)
            facts = directory_facts.get(parent.parent_id)
            has_card = bool(customer and (customer.card_label or customer.card_last4))
            has_login = parent.parent_id in login_account_ids
            state = _registration_state(has_card=has_card, has_login_account=has_login)
            login_state_value = _login_state(
                has_login_account=has_login,
                login_invite_sent_at=facts.login_invite_sent_at if facts else None,
            )
            # ... lines 166-182 unchanged: enrollments / balance / active_count /
            #     eligible_count / charge_autopay_eligible ...
            rows.append(
                BillingSetupRow(
                    parent_id=parent.parent_id,
                    parent_name=parent.parent_name,
                    parent_email=parent.parent_email,
                    # ParentRosterEntry.parent_phone stays None on the list path
                    # (AdminStudentSummary has no phone); the identity directory
                    # is the source of truth, with the roster as a fallback for
                    # the single-parent lookup.
                    parent_phone=(facts.phone if facts else None) or parent.parent_phone,
                    students=tuple(students_by_parent.get(parent.parent_id, [])),
                    registration_state=state,
                    login_state=login_state_value,
                    card_label=customer.card_label if customer else None,
                    card_last4=customer.card_last4 if customer else None,
                    autopay_active_count=active_count,
                    autopay_eligible_count=eligible_count,
                    outstanding_balance_cents=balance.outstanding_cents if balance else 0,
                    charge_invoice_id=balance.charge_invoice_id if balance else None,
                    charge_amount_cents=balance.charge_amount_cents if balance else 0,
                    charge_autopay_eligible=charge_autopay_eligible,
                    last_invited_at=customer.last_invited_at if customer else None,
                )
            )
```

Widen the search and add the login-state filter, replacing the existing `status_filter`/`q` block (currently lines 203–211). Note the existing test `test_name_search_matches_name_or_email_case_insensitively` must keep passing:

```python
        if status_filter != "all":
            rows = [r for r in rows if r.registration_state == status_filter]
        if login_state != "all":
            rows = [r for r in rows if r.login_state == login_state]
        if q:
            needle = q.strip().lower()
            rows = [
                r
                for r in rows
                if needle in r.parent_name.lower()
                or needle in (r.parent_email or "").lower()
                or needle in (r.parent_phone or "").lower()
                or any(needle in s.full_name.lower() for s in r.students)
            ]
```

- [ ] 1.7 Run `cd backend && .venv/bin/pytest v2/tests/unit/test_billing_setup_registration.py -q` — expect all 19 tests PASS (12 pre-existing + 7 new). Then run the identity repo's own suite to catch a broken `list_parent_directory_facts`: `cd backend && .venv/bin/pytest v2/tests -k "user_repo or admin_directory" -q`.

- [ ] 1.8 Commit:
  `git add backend/v2/contexts/billing/application/ports.py backend/v2/contexts/billing/application/use_cases/billing_setup_registration.py backend/v2/contexts/identity/infrastructure/mongo_user_repo.py backend/v2/tests/unit/test_billing_setup_registration.py`
  Message:
  ```
  feat(billing): add phone/login_state to Billing Setup roster

  Families list needs phone in search and a login-state facet (never
  invited / invited / active) distinct from card registration state.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

---

### Task 2: Backend — move Billing Setup composition wiring into `composition/families.py`

**Files:**
- Modify: `backend/v2/composition/families.py` (currently 66 lines)
- Modify: `backend/v2/composition/admin.py` — remove `_BillingSetupRosterAdapter`, `_BillingSetupLoginAccountAdapter`, `_BillingSetupCustomerAdapter`, `_BillingSetupAutopayAdapter`, `_BillingSetupBalanceAdapter` and `list_billing_setup = ListBillingSetup(...)` (lines 1775–1999, verified this session — they are **nested classes inside `compose_admin`** that close over the locals `db` and `users_r`). **Keep** `_BillingSetupParentContactAdapter` and `_BillingSetupCardSetupLinkAdapter` (lines 2001–2030): they feed `send_add_card_reminder`, not the list.
- Modify: `backend/v2/interfaces/admin/deps.py` — widen `AdminUseCases.list_billing_setup` (line 208)
- Modify: `backend/v2/main.py` (line 601, `app.state.admin_families = compose_admin_families(db)`)
- Test: `backend/v2/tests/interface/test_admin_billing_setup.py` — the regression gate for this move. Do not change its assertions; only make it pass through the new wiring path.

**Interfaces:**
- Consumes: `app.state.admin.list_admin_students` (already exposed on `AdminUseCases`, `composition/admin.py` line 4030 — verified; do **not** add a new kwarg for it)
- Produces: `AdminFamilies.list_billing_setup: ListBillingSetup` (new field on the `composition/families.py` dataclass); `app.state.admin.list_billing_setup` still resolves, now late-bound

**Correction to the original draft:** `users_r`, `parent_customers_repo`,
`student_billing_enrollment_repo` and `billing_ledger_repo` are **locals inside
`compose_admin`** and are not returned or exposed anywhere — grepping `main.py` for
them returns nothing. Do not try to thread them from `main.py`. `compose_admin_families`
already builds its own `MongoParentBillingCustomerRepository(db)`,
`MongoStudentBillingEnrollmentRepository(db)` and `MongoUserRepository(db)` (lines 55–62);
build the ledger repo there too. Only `list_admin_students` (and, in Task 4,
`send_login_invite`) have to come in from `main.py`, because they are use cases rather
than repos.

Steps:

- [ ] 2.1 Before editing, run the existing interface test to capture the current green baseline:
  `cd backend && .venv/bin/pytest v2/tests/interface/test_admin_billing_setup.py -q`
  Expected: PASS (establishes the regression baseline this task must not break).

- [ ] 2.2 Read `backend/v2/composition/admin.py` lines 1770–2035 fresh (line numbers may have drifted) and locate all five adapter classes plus the `list_billing_setup = ListBillingSetup(...)` call (line 1993). Note that they are nested inside `compose_admin` and reference the enclosing locals `db` (in `_BillingSetupRosterAdapter._direct_student_docs`) and `users_r` (in `_BillingSetupRosterAdapter.get_parent`) — moving them to module level in `families.py` means those become constructor arguments. Confirm the boundary: line 1999 is the closing `)` of `ListBillingSetup(...)`, and line 2001 starts `_BillingSetupParentContactAdapter`, which **stays**.

- [ ] 2.3 In `backend/v2/composition/families.py`, add the two adapter classes and change `AdminFamilies`/`compose_admin_families` to build and expose `list_billing_setup`:

```python
"""Composition for the admin Family billing page (``/admin/families/{parent_id}/…``)
and the Families list (``/admin/billing/setup``, spec 2026-09-10 §3).

Lives outside ``composition/admin.py`` because that module sits at its wiring
line budget. Pure wiring: every repository resolves the tenant from
``current_academy_id()`` at request time, so nothing tenant-specific is
captured here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.contexts.billing.application.ports import (
    BillingSetupStudent,
    ParentRosterEntry,
)
from backend.v2.contexts.billing.application.use_cases.billing_setup_registration import (
    ListBillingSetup,
)
from backend.v2.contexts.billing.application.use_cases.pause_family_autopay import (
    PauseFamilyAutopay,
)
from backend.v2.contexts.billing.infrastructure.family_billing_read_model import (
    MongoFamilyBillingReadModel,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_student_billing_enrollment_repo import (
    MongoStudentBillingEnrollmentRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.list_admin_students import (
    ListAdminStudents,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup


class _BillingSetupRosterAdapter:
    """Bridges enrollment's paginated admin student directory into the
    parent roster the Billing Setup page needs. Composition may bridge
    billing + enrollment; the billing context itself must not import
    enrollment directly (see ``billing_setup_registration.py``)."""

    def __init__(self, db: Any, users_r: MongoUserRepository, list_students: ListAdminStudents) -> None:
        self._db = db
        self._users_r = users_r
        self._list_students = list_students

    async def _all_students(self) -> list[Any]:
        students: list[Any] = []
        cursor: str | None = None
        for _ in range(1000):  # safety cap against a runaway pagination loop
            page = await self._list_students.execute(limit=200, cursor=cursor)
            students.extend(page.students)
            if not page.next_cursor:
                break
            cursor = page.next_cursor
        return students

    async def list_parents(self, *, academy_id: str) -> list[ParentRosterEntry]:
        # NOTE: AdminStudentSummary has no parent_phone (only AdminStudentDetail
        # does) — phone for the list comes from parent_directory_facts below,
        # not from here. Do not add a getattr() that is always None.
        seen: dict[str, ParentRosterEntry] = {}
        for student in await self._all_students():
            if student.parent_id not in seen:
                seen[student.parent_id] = ParentRosterEntry(
                    parent_id=student.parent_id,
                    parent_name=student.parent_name or student.parent_id,
                    parent_email=student.parent_email,
                )
        return list(seen.values())

    async def students_for_parents(
        self, parent_ids: list[str], *, academy_id: str
    ) -> dict[str, list[BillingSetupStudent]]:
        wanted = set(parent_ids)
        result: dict[str, list[BillingSetupStudent]] = {}
        for student in await self._all_students():
            if student.parent_id in wanted:
                result.setdefault(student.parent_id, []).append(
                    BillingSetupStudent(student_id=student.student_id, full_name=student.full_name)
                )
        return result

    async def _direct_student_docs(self, parent_id: str) -> list[dict[str, Any]]:
        from backend.v2.shared.tenancy import current_academy_id

        cursor = self._db["students"].find(
            {
                "academy_id": current_academy_id(),
                "$or": [{"parent_id": parent_id}, {"parent_user_id": parent_id}],
            }
        )
        return [doc async for doc in cursor]

    async def get_parent(self, parent_id: str, *, academy_id: str) -> ParentRosterEntry | None:
        docs = await self._direct_student_docs(parent_id)
        if not docs:
            return None
        user = await self._users_r.get_billing_setup_parent(parent_id, academy_id=academy_id)
        if user is None:
            user = await self._users_r.get_by_id(parent_id)
        first = docs[0]
        fallback_name = str(first.get("parent_name") or first.get("guardian_name") or parent_id)
        fallback_email = first.get("parent_email") or first.get("guardian_email")
        return ParentRosterEntry(
            parent_id=parent_id,
            parent_name=user.display_name if user else fallback_name,
            parent_email=str(user.email) if user else (str(fallback_email) if fallback_email else None),
            parent_phone=getattr(user, "phone", None) if user else None,
        )

    async def students_for_parent(
        self, parent_id: str, *, academy_id: str
    ) -> list[BillingSetupStudent]:
        rows: list[BillingSetupStudent] = []
        for doc in await self._direct_student_docs(parent_id):
            full_name = str(
                doc.get("full_name")
                or f"{doc.get('first_name', '')} {doc.get('last_name', '')}".strip()
                or doc.get("name")
                or "Student"
            )
            rows.append(
                BillingSetupStudent(student_id=str(doc.get("student_id") or doc["_id"]), full_name=full_name)
            )
        return rows


class _BillingSetupLoginAccountAdapter:
    def __init__(self, users: MongoUserRepository) -> None:
        self._users = users

    async def login_account_parent_ids(self, parent_ids: list[str], *, academy_id: str) -> set[str]:
        from backend.v2.shared.tenancy import current_academy_id

        return await self._users.list_existing_user_ids(parent_ids, academy_id=current_academy_id())

    async def has_login_account(self, parent_id: str, *, academy_id: str) -> bool:
        return parent_id in await self._users.list_existing_user_ids([parent_id], academy_id=academy_id)

    async def parent_directory_facts(
        self, parent_ids: list[str], *, academy_id: str
    ) -> dict[str, ParentDirectoryFacts]:
        """Phone + LOGIN-invite timestamp (Task 1.3b). Composition maps the
        identity repo's plain rows onto billing's port model so identity never
        imports billing."""
        from backend.v2.shared.tenancy import current_academy_id

        rows = await self._users.list_parent_directory_facts(
            parent_ids, academy_id=current_academy_id()
        )
        return {
            parent_id: ParentDirectoryFacts(
                parent_id=parent_id,
                phone=row.get("phone"),
                login_invite_sent_at=row.get("login_invite_sent_at"),
            )
            for parent_id, row in rows.items()
        }


@dataclass
class AdminFamilies:
    reader: MongoFamilyBillingReadModel
    pause_autopay: PauseFamilyAutopay
    list_billing_setup: ListBillingSetup
    password_reset: SendLoginInvite       # Task 4
    contact_writer: _FamilyContactWriter  # Task 5


def compose_admin_families(
    db: Any,
    *,
    list_admin_students: ListAdminStudents,
    send_login_invite: SendLoginInvite,  # Task 4 — already built by compose_admin
) -> AdminFamilies:
    users_r = MongoUserRepository(db)
    parent_customers_repo = MongoParentBillingCustomerRepository(db)
    student_billing_enrollment_repo = MongoStudentBillingEnrollmentRepository(db)
    billing_ledger_repo = MongoBillingLedgerRepository(db)
    audit = MongoBillingAuditLogRepository(db)
    reader = MongoFamilyBillingReadModel(
        db,
        academy_timezone=academy_timezone_lookup(db),
        connected_accounts=MongoConnectedAccountRepository(db),
        billing_settings=MongoBillingSettingsRepository(db),
        customers=parent_customers_repo,
        credits=MongoCreditLedgerRepository(db),
        users=users_r,
        audit=audit,
    )
    pause = PauseFamilyAutopay(
        enrollments=student_billing_enrollment_repo,
        audit=audit,
        idempotency=MongoIdempotencyStore(db),
    )
    list_billing_setup = ListBillingSetup(
        roster=_BillingSetupRosterAdapter(db, users_r, list_admin_students),
        login_accounts=_BillingSetupLoginAccountAdapter(users_r),
        customers=_BillingSetupCustomerAdapter(parent_customers_repo),
        autopay=_BillingSetupAutopayAdapter(student_billing_enrollment_repo),
        balances=_BillingSetupBalanceAdapter(billing_ledger_repo),
    )
    return AdminFamilies(
        reader=reader,
        pause_autopay=pause,
        list_billing_setup=list_billing_setup,
        password_reset=send_login_invite,
        contact_writer=_FamilyContactWriter(users_r),
    )
```

  Notes on the block above:
  - The `password_reset` / `contact_writer` fields and the `send_login_invite` parameter
    are added in Tasks 4 and 5; write them in now only if you are doing those tasks in
    the same pass, otherwise omit both and add them there. The dataclass must be a plain
    `@dataclass` (not `frozen`) so later tasks can attach to it if needed.
  - `_BillingSetupCustomerAdapter`, `_BillingSetupAutopayAdapter` and
    `_BillingSetupBalanceAdapter` are **copied verbatim** from `composition/admin.py`
    (lines 1891–1991) into `composition/families.py` as module-level classes. They are
    not left behind in `admin.py`.
  - Imports this file needs on top of what it already has:
    `ParentDirectoryFacts` and `ParentBalanceSnapshot` / `ParentBillingCustomerSnapshot` /
    `EnrollmentAutopaySnapshot` from `contexts.billing.application.ports`,
    `MongoBillingLedgerRepository` from
    `contexts.billing.infrastructure.mongo_billing_ledger_repo`, and (Task 4)
    `SendLoginInvite` from `contexts.identity.application.use_cases.send_login_invite`.
  - `compose_admin` builds `users_r` as `MongoUserRepository(db, default_academy_id=academy_id)`.
    `families.py` deliberately builds it without a default academy (as it already does
    today at line 58): every method the Billing Setup adapters call
    (`list_existing_user_ids`, `list_parent_directory_facts`, `get_billing_setup_parent`)
    takes `academy_id` explicitly, and `get_by_id` is un-scoped by design. Do not add a
    `default_academy_id` here — it would import a boot-time tenant into a per-request path.

- [ ] 2.4 In `backend/v2/composition/admin.py`, delete lines 1775–1999 (all five `_BillingSetup*` adapter classes named in 2.2 plus the `list_billing_setup = ListBillingSetup(...)` call). Then:
  - `grep -n "_BillingSetupRosterAdapter\|_BillingSetupLoginAccountAdapter\|_BillingSetupCustomerAdapter\|_BillingSetupAutopayAdapter\|_BillingSetupBalanceAdapter" backend/v2/composition/admin.py` → expect **no** hits.
  - Remove the now-unused `ListBillingSetup` import (line 119) and any `ParentRosterEntry` / `BillingSetupStudent` / `ParentBillingCustomerSnapshot` / `EnrollmentAutopaySnapshot` / `ParentBalanceSnapshot` imports that only those classes used — ruff (step 3.5) will name them.
  - At the `AdminUseCases(...)` construction site, change `list_billing_setup=list_billing_setup,` (line 4031) to `list_billing_setup=None,  # late-bound in main.py from admin_families`.
  - In `backend/v2/interfaces/admin/deps.py`, widen line 208 to `list_billing_setup: ListBillingSetup | None`. **Keep it a required field with no default**: `AdminUseCases` is `@dataclass` (not frozen — verified, so the late-bind assignment in `main.py` works), and ~119 non-default fields follow line 208, so giving it a default would raise `TypeError: non-default argument follows default argument` at import time. The route already tolerates `None` — `billing_setup_routes._required_callable` (line 41) turns it into a 503.

- [ ] 2.5 In `backend/v2/main.py`, replace `app.state.admin_families = compose_admin_families(db)` (line 601) with the call below and add the late-binding line immediately after. `app.state.admin.list_admin_students` is already exposed on `AdminUseCases` (`composition/admin.py` line 4030 — verified this session), so no new kwarg is needed in `admin.py`:

```python
    app.state.admin_families = compose_admin_families(
        db,
        list_admin_students=app.state.admin.list_admin_students,
        send_login_invite=app.state.admin.send_login_invite,  # Task 4 only
    )
    # Billing Setup list wiring lives in composition/families.py, not
    # composition/admin.py (spec 2026-09-10-families-directory-consolidation
    # §3) — late-bound the same way stop_all_classes is at line 596.
    app.state.admin.list_billing_setup = app.state.admin_families.list_billing_setup
```

  (`send_login_invite` is exposed on `AdminUseCases` at `composition/admin.py` line 4204 — verified. Drop that kwarg if you are landing Task 2 before Task 4.) Line 601 already sits after `app.state.admin` is built at line 547, so the ordering is safe.

- [ ] 2.6 Run the full billing-setup route test plus a backend boot smoke check:
  `cd backend && .venv/bin/pytest v2/tests/interface/test_admin_billing_setup.py v2/tests/unit/test_billing_setup_registration.py -q`
  Expected: all PASS (same assertions as the step-2.1 baseline, now backed by the moved wiring).
  Also run `cd backend && .venv/bin/python -c "import backend.v2.main"` to catch import-order/circular-import errors from the move (does not start the server, only imports the module).

- [ ] 2.7 Run import-linter with the same invocation CI uses (`.github/workflows/production.yml` line 146):
  `cd backend && .venv/bin/lint-imports --config pyproject.toml`
  Expected: PASS, 0 violations across all contracts in `backend/pyproject.toml` lines 71–190. `composition/*` is the layer allowed to bridge billing↔enrollment↔identity (that is exactly why the roster adapter lives there and `billing_setup_registration.py` uses Protocol ports) — but the *new* identity method added in Task 1.3b must not import anything from `contexts.billing`, which is why it returns plain rows and `families.py` maps them into `ParentDirectoryFacts`.

- [ ] 2.7b Run the composition line-budget ratchet, which is the whole reason for this task:
  `cd backend && .venv/bin/pytest v2/tests/structural/test_composition_is_wiring.py -q`
  Expected: PASS, and `wc -l backend/v2/composition/admin.py` should now report ~4093 (was 4318).

- [ ] 2.8 Commit:
  `git add backend/v2/composition/families.py backend/v2/composition/admin.py backend/v2/main.py backend/v2/interfaces/admin/deps.py`
  Message:
  ```
  refactor(billing): move Billing Setup roster wiring to composition/families.py

  composition/admin.py is at its line-budget cap; the families list's
  roster/login adapters belong beside the rest of the family-page wiring
  per spec 2026-09-10-families-directory-consolidation §3. Late-bound
  onto AdminUseCases the same way stop_all_classes already is.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

---

### Task 3: Backend — `login_state` query param + response fields on `/admin/billing/setup`

**Files:**
- Modify: `backend/v2/interfaces/admin/billing_setup_routes.py` (`BillingSetupRowDto` lines 52–66, `_to_response` lines 82–113, `list_billing_setup` route lines 116–133)
- Test: `backend/v2/tests/interface/test_admin_billing_setup.py`

**Interfaces:**
- Produces: `GET /admin/billing/setup?login_state=never_invited|invited|active|all` (default `all`); response rows gain `parent_phone`, `login_state`

Steps:

- [ ] 3.1 Read `backend/v2/tests/interface/test_admin_billing_setup.py` in full to match its existing fixture/style, then add a failing test asserting the new query param and response fields (adapt the fixture helper names to match what the file already uses — do not guess a different testing pattern than what's already there):

```python
def test_login_state_filter_and_phone_field(client, seed_family_with_login):
    resp = client.get("/admin/billing/setup", params={"login_state": "active"})
    assert resp.status_code == 200
    body = resp.json()
    assert all(row["login_state"] == "active" for row in body["rows"])
    assert "parent_phone" in body["rows"][0]
```

  (Use whatever fixture the file already provides for "a parent with a login account" — if none exists, add a minimal one following the file's existing seeding pattern.)

- [ ] 3.2 Run: `cd backend && .venv/bin/pytest v2/tests/interface/test_admin_billing_setup.py -q` — expect the new test to fail with a 422 (unknown query param rejected) or a `KeyError`/`AssertionError` on `login_state` missing from the response.

- [ ] 3.3 In `billing_setup_routes.py`, add `parent_phone` and `login_state` to `BillingSetupRowDto` (lines 52–66):

```python
class BillingSetupRowDto(BaseModel):
    parent_id: str
    parent_name: str
    parent_email: str | None = None
    parent_phone: str | None = None
    students: list[BillingSetupStudentDto]
    registration_state: RegistrationState
    login_state: Literal["never_invited", "invited", "active"] = "never_invited"
    card_label: str | None = None
    card_last4: str | None = None
    autopay_active_count: int
    autopay_eligible_count: int
    outstanding_balance_cents: int
    charge_invoice_id: str | None = None
    charge_amount_cents: int = 0
    charge_autopay_eligible: bool = False
    last_invited_at: datetime | None = None
```

  Update `_to_response` (lines 82–113) to pass through `parent_phone=row.parent_phone, login_state=row.login_state,`.

  Update `list_billing_setup` (lines 116–133) to accept and pass through the new param:

```python
@router.get("/billing/setup", response_model=BillingSetupPageResponse)
async def list_billing_setup(
    status: Literal["all", "no_account", "account_no_card", "card_on_file"] = "all",
    login_state: Literal["all", "never_invited", "invited", "active"] = "all",
    q: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> BillingSetupPageResponse:
    list_use_case = _required_callable(use_cases.list_billing_setup, "Billing Setup")
    page = await list_use_case.execute(  # type: ignore[attr-defined]
        academy_id=claims.academy_id,
        status_filter=status,
        login_state=login_state,
        q=q,
        cursor=cursor,
        limit=limit,
    )
    return _to_response(page)
```

- [ ] 3.4 Run `cd backend && .venv/bin/pytest v2/tests/interface/test_admin_billing_setup.py -q` — expect PASS.

- [ ] 3.5 Add the tenant-scoping test spec §9 asks for ("a parent outside the tenant is absent, never 403") to `test_admin_billing_setup.py`, following whatever multi-tenant seeding helper the file already uses (grep it for `academy_id` first — if the file only seeds one academy, seed a second parent under a different `academy_id` using the same helper):

```python
def test_parent_in_another_academy_is_absent_not_forbidden(client, seed_two_academies):
    resp = client.get("/admin/billing/setup")
    assert resp.status_code == 200
    ids = {row["parent_id"] for row in resp.json()["rows"]}
    assert "parent-other-academy" not in ids
```

  Also assert the 404-not-403 persona rule holds for a non-admin caller on this route
  (`require_persona("admin")`), matching how the file's existing persona test does it —
  do not add a new pattern.

- [ ] 3.6 Run ruff: `cd backend && .venv/bin/ruff check v2/interfaces/admin/billing_setup_routes.py v2/contexts/billing/application/use_cases/billing_setup_registration.py v2/contexts/billing/application/ports.py v2/contexts/identity/infrastructure/mongo_user_repo.py v2/composition/families.py v2/composition/admin.py` — expect no errors (this is also where dangling imports left by the Task 2.4 deletion surface).

- [ ] 3.7 Commit:
  `git add backend/v2/interfaces/admin/billing_setup_routes.py backend/v2/tests/interface/test_admin_billing_setup.py`
  Message:
  ```
  feat(billing): expose login_state filter + phone on Billing Setup list

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

---

### Task 4: Backend — Family detail header gets a login badge + password-reset + edit-contact actions

**Files:**
- Modify: `backend/v2/interfaces/admin/families_views.py` (`FamilyAction` line 16, add `FamilyLogin` model, `FamilyHeader` line 68–76)
- Modify: `backend/v2/contexts/billing/application/family_billing.py` (`family_actions` lines 305–321, `build_family_billing_view` lines 726–821, `CustomerFacts.last_invited_at`/`has_login_account` at lines 192–193)
- No change needed in `backend/v2/contexts/billing/infrastructure/family_billing_read_model.py` — `CustomerFacts` already carries `has_login_account`; the header block is assembled in `family_billing.py`, not there.
- Modify: `backend/v2/interfaces/admin/families_routes.py` — new `POST /families/{parent_id}/password-reset` route. The module currently imports neither `BaseModel` nor `Field`; add `from pydantic import BaseModel, Field`.
- Modify: `backend/v2/tests/unit/test_family_billing.py` — `test_family_actions` (lines 190–199) asserts exact list equality on four `family_actions(...)` calls and **will fail** once `edit_contact` is prepended. Update those four expected lists in this same commit.
- Test: `backend/v2/tests/interface/test_admin_families_routes.py`

**OPEN QUESTION (owner):** spec §4 lists "Send / resend invite" and "Send password reset"
as two distinct header actions, but the codebase has exactly one use case,
`SendLoginInvite` (`backend/v2/contexts/identity/application/use_cases/send_login_invite.py`
line 116), and what it sends *is* a Firebase password-reset link
(`PasswordResetLinkPort.generate_password_reset_link`, line 29). There is no separate
password-reset use case. So either (a) the two buttons are the same call with different
copy — in which case "Send password reset" should just be the label shown when the parent
already has an account, and `POST /families/{parent_id}/password-reset` is redundant with
the existing invite route; or (b) a genuinely distinct reset flow (different email
template / no membership stamp) has to be built. The plan below implements (a): the new
route delegates to `SendLoginInvite`. Confirm with the owner before shipping the second
button, and drop the extra route if (a) is accepted.

**Interfaces:**
- Produces: `AdminFamilyBillingView.header.login: {state: "never_invited"|"invited"|"active", last_invited_at: str|null}`; `FamilyAction` gains `"send_password_reset"`, `"edit_contact"`; `POST /families/{parent_id}/password-reset -> {ok: bool}`

Steps:

- [ ] 4.1 Read `backend/v2/tests/interface/test_admin_families_routes.py` in full to match its fixture/mocking style (it already overrides `get_admin_families` per the earlier grep at line 160 — reuse that pattern), then add a failing test:

```python
def test_family_header_includes_login_state(client, family_services_stub):
    resp = client.get("/families/p1/billing")
    assert resp.status_code == 200
    body = resp.json()
    assert body["header"]["login"]["state"] in {"never_invited", "invited", "active"}
    assert "send_password_reset" in body["actions"] or "edit_contact" in body["actions"]
```

  (Adapt to the file's actual stub-builder function name — do not invent a fixture name that doesn't exist; grep the file for its stub factory first.)

- [ ] 4.2 Run `cd backend && .venv/bin/pytest v2/tests/interface/test_admin_families_routes.py -q` — expect `KeyError: 'login'`.

- [ ] 4.3 In `families_views.py`, add `FamilyLogin` and wire it into `FamilyHeader`, and extend `FamilyAction`:

```python
FamilyAction = Literal[
    "send_invite", "autopay_on", "autopay_off", "send_invoice", "record_payment",
    "send_password_reset", "edit_contact",
]
...
class FamilyLogin(_View):
    state: Literal["never_invited", "invited", "active"]
    last_invited_at: str | None = None


class FamilyHeader(_View):
    balance_cents: int
    open_invoice_count: int
    available_credit_cents: int
    last_payment: FamilyLastPayment | None = None
    autopay: FamilyAutopay
    registration: FamilyRegistration
    # Optional with a default on purpose: `_View` is extra="ignore" and the
    # existing route/stub tests validate hand-built header dicts. A required
    # field here would fail every one of them.
    login: FamilyLogin | None = None
    enrollment_counts: FamilyEnrollmentCounts
```

  (Pydantic allows a defaulted field before non-defaulted ones, unlike a dataclass, so
  the position above is fine — but keep `login` adjacent to `registration` for readability.)

- [ ] 4.4 In `family_billing.py`, compute login state inside `build_family_billing_view` right after the existing `registration` block (lines 760–765) and add it to the returned `header` dict (line 792–796 area):

```python
    if facts.customer.has_login_account:
        login_state = "active"
    elif facts.customer.last_invited_at is not None:
        login_state = "invited"
    else:
        login_state = "never_invited"
```

  and inside the `"header": {...}` dict, alongside `"registration": {...}`:

```python
            "login": {
                "state": login_state,
                "last_invited_at": _iso(facts.customer.last_invited_at),
            },
```

  Update `family_actions` (lines 305–321) to add the two new actions — `send_password_reset` whenever the parent has a login account, `edit_contact` unconditionally (every parent's contact is editable). **`has_login_account` must have a default**: `backend/v2/tests/unit/test_family_billing.py` calls this function positionally-by-keyword without it in four places, and a required kwarg would turn those into `TypeError` instead of a readable assertion diff:

```python
def family_actions(
    *,
    state: str,
    has_card: bool | None,
    invoices: Sequence[InvoiceFacts],
    has_login_account: bool = False,
) -> list[str]:
    actions: list[str] = ["edit_contact"]
    if not has_card:
        actions.append("send_invite")
    if has_login_account:
        actions.append("send_password_reset")
    if state in {"off", "partial"}:
        actions.append("autopay_on")
    if state in {"on", "partial"}:
        actions.append("autopay_off")
    open_invoices = [i for i in invoices if i.status in CHARGEABLE_INVOICE_STATUSES]
    if open_invoices:
        actions.append("send_invoice")
    if any(i.balance_due_cents > 0 for i in open_invoices):
        actions.append("record_payment")
    return actions
```

  The call site is `build_family_billing_view`'s returned dict at line 817:
  `"actions": family_actions(state=state, has_card=facts.customer.has_card, invoices=facts.invoices)`.
  Add `has_login_account=facts.customer.has_login_account` to it.

- [ ] 4.4b Update `backend/v2/tests/unit/test_family_billing.py::test_family_actions` (lines 190–199). All four expected lists now start with `"edit_contact"`, e.g. `family_actions(state="off", has_card=True, invoices=[])` becomes `["edit_contact", "autopay_on"]` and `family_actions(state="needs_consent", has_card=False, invoices=[])` becomes `["edit_contact", "send_invite"]`. Add one new assertion for `has_login_account=True` producing `send_password_reset`. Run `cd backend && .venv/bin/pytest v2/tests/unit/test_family_billing.py -q` — expect PASS.

- [ ] 4.5 Add the password-reset route in `families_routes.py`. **Verified this session:** the only existing password-reset path is `SendLoginInvite` (`backend/v2/contexts/identity/application/use_cases/send_login_invite.py` line 116), signature `async def execute(self, user_id: str, *, academy_id: str) -> LoginInviteResult` — exactly the Protocol below. It is already constructed in `compose_admin` (line 1750) and exposed on `AdminUseCases` as `send_login_invite` (line 4204), so **do not construct a second one**; pass the existing instance into `compose_admin_families` (Task 2.5). See the OPEN QUESTION above before shipping the separate button. Wire it through `AdminFamiliesServices`:

```python
class FamilyPasswordResetSender(Protocol):
    async def execute(self, user_id: str, *, academy_id: str) -> object: ...


class AdminFamiliesServices(Protocol):
    reader: FamilyBillingReader
    pause_autopay: FamilyAutopayPauser
    password_reset: FamilyPasswordResetSender
```

```python
class PasswordResetResponse(BaseModel):
    ok: bool


@router.post("/families/{parent_id}/password-reset", response_model=PasswordResetResponse)
async def send_family_password_reset(
    parent_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminFamiliesServices = Depends(get_admin_families),
) -> PasswordResetResponse:
    """Send/resend a password-reset link to a parent with a login account."""
    try:
        result = await services.password_reset.execute(parent_id, academy_id=_academy_id(claims))
    except Exception:
        logger.exception("family password reset failed for parent %s", parent_id)
        return PasswordResetResponse(ok=False)
    return PasswordResetResponse(ok=bool(getattr(result, "ok", True)))
```

  Read `LoginInviteResult` (`send_login_invite.py` line 93) before writing the last line
  and map its real success field rather than the `getattr` above. Do not leave a bare
  `except Exception:` that swallows the error silently — log it, or the route becomes a
  black hole the way `#638`'s attendance bug was.

  Wire `password_reset` in `composition/families.py`'s `AdminFamilies` dataclass and
  `compose_admin_families` by **passing through** the already-built
  `app.state.admin.send_login_invite` (Task 2.5), not by constructing a second
  `SendLoginInvite` — a second instance would need the Firebase link adapter, the email
  sender, the academy repo and the portal-URL lookup re-wired, which is exactly the
  wiring `composition/admin.py` has no room for.

- [ ] 4.6 Run `cd backend && .venv/bin/pytest v2/tests/interface/test_admin_families_routes.py -q` — expect PASS. Also re-run Task 2's baseline test to confirm the composition change didn't regress it: `cd backend && .venv/bin/pytest v2/tests/interface/test_admin_billing_setup.py -q`.

- [ ] 4.7 Commit:
  `git add backend/v2/interfaces/admin/families_views.py backend/v2/contexts/billing/application/family_billing.py backend/v2/interfaces/admin/families_routes.py backend/v2/composition/families.py backend/v2/tests/interface/test_admin_families_routes.py`
  Message:
  ```
  feat(billing): family header login badge + password-reset + edit-contact actions

  FamilyHeader becomes the identity-and-status strip per spec
  2026-09-10-families-directory-consolidation §4.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

---

### Task 5: Backend — "Edit contact details" (name/phone) write path

**Files:**
- Modify: `backend/v2/interfaces/admin/families_routes.py` — new `PATCH /families/{parent_id}/contact` route
- Modify: `backend/v2/composition/families.py` — wire the writer
- Test: `backend/v2/tests/interface/test_admin_families_routes.py`

**Interfaces:**
- Produces: `PATCH /families/{parent_id}/contact {display_name?, phone?} -> AdminFamilyBillingView.parent`
- Consumes: existing `UpdateAdminUser`/`MongoUserRepository.update_admin_user` write path (reuse — do not duplicate; grep `grep -n "def update_admin_user" backend/v2/contexts/identity/infrastructure/mongo_user_repo.py` for its exact signature before wiring, since it currently also accepts `email`/`status`, which this route must never send — email edit stays the existing admin-only path per spec §4)

Steps:

- [ ] 5.1 Verified this session: `MongoUserRepository.update_admin_user(self, user_id: str, command: UpdateAdminUserCommand, *, academy_id: str) -> AdminUserDetail | None` (line 835), and `UpdateAdminUserCommand` (`backend/v2/contexts/identity/application/use_cases/admin_directory.py` lines 46–56) has `email`, `display_name`, `phone`, `status`, `actor_id: str = Field(min_length=1)`, `reason: str = Field(min_length=1, max_length=500)`. Re-read both before wiring. The adapter must leave `email` and `status` as `None` (spec §4 keeps email edit on the existing admin-only path with its warning) — `update_admin_user` only touches Firebase when `command.email is not None`, so a `None` here is what keeps a contact edit from clearing `email_verified` (see `#436` comment at line 851).

- [ ] 5.2 Add a failing test in `test_admin_families_routes.py`:

```python
def test_edit_contact_updates_name_and_phone(client, family_services_stub):
    resp = client.patch(
        "/families/p1/contact",
        json={"display_name": "New Name", "phone": "555-0100", "reason": "Parent asked"},
    )
    assert resp.status_code == 200
    assert resp.json()["parent"]["name"] == "New Name"
```

- [ ] 5.3 Run: `cd backend && .venv/bin/pytest v2/tests/interface/test_admin_families_routes.py -q` — expect 404 (route doesn't exist).

- [ ] 5.4 Add the route to `families_routes.py`:

```python
class EditFamilyContactRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    reason: str = Field(min_length=1, max_length=500)


class ContactWriter(Protocol):
    async def update_contact(
        self, parent_id: str, *, display_name: str | None, phone: str | None,
        actor_id: str, reason: str, academy_id: str,
    ) -> None: ...


class AdminFamiliesServices(Protocol):
    reader: FamilyBillingReader
    pause_autopay: FamilyAutopayPauser
    password_reset: FamilyPasswordResetSender
    contact_writer: ContactWriter


@router.patch("/families/{parent_id}/contact", response_model=AdminFamilyBillingView)
async def edit_family_contact(
    parent_id: str,
    body: EditFamilyContactRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminFamiliesServices = Depends(get_admin_families),
) -> AdminFamilyBillingView:
    if body.display_name is None and body.phone is None:
        raise HTTPException(status_code=400, detail="nothing_to_update")
    await services.contact_writer.update_contact(
        parent_id,
        display_name=body.display_name,
        phone=body.phone,
        actor_id=claims.user_id,
        reason=body.reason,
        academy_id=_academy_id(claims),
    )
    view = await services.reader.build(parent_id)
    if view is None:
        raise HTTPException(status_code=404, detail="family not found")
    if "owner" not in claims.roles:
        view = strip_owner_actions(view)
    return AdminFamilyBillingView.model_validate(view)
```

  `families_routes.py` already imports `HTTPException` and `strip_owner_actions`; add
  `from pydantic import BaseModel, Field` (Task 4 note) if not already added.

  Wire `contact_writer` in `composition/families.py` as a module-level `_FamilyContactWriter`
  over `MongoUserRepository.update_admin_user`:

```python
class _FamilyContactWriter:
    def __init__(self, users: MongoUserRepository) -> None:
        self._users = users

    async def update_contact(
        self,
        parent_id: str,
        *,
        display_name: str | None,
        phone: str | None,
        actor_id: str,
        reason: str,
        academy_id: str,
    ) -> None:
        updated = await self._users.update_admin_user(
            parent_id,
            UpdateAdminUserCommand(
                display_name=display_name,
                phone=phone,
                actor_id=actor_id,
                reason=reason,
            ),
            academy_id=academy_id,
        )
        if updated is None:
            # 404-not-403: a parent outside this tenant simply does not exist.
            raise FamilyContactTargetMissing(parent_id)
```

  Define `FamilyContactTargetMissing` next to it and map it to a 404 in the route (an
  unmapped `None` would let the route fall through to `reader.build`, which would return
  a stale view and report success for a write that never happened).

- [ ] 5.5 Run `cd backend && .venv/bin/pytest v2/tests/interface/test_admin_families_routes.py -q` — expect PASS.

- [ ] 5.6 Commit:
  `git add backend/v2/interfaces/admin/families_routes.py backend/v2/composition/families.py backend/v2/tests/interface/test_admin_families_routes.py`
  Message:
  ```
  feat(billing): family header edit-contact write path (name/phone only)

  Email edit intentionally stays on the existing admin-only path per
  spec 2026-09-10-families-directory-consolidation §4.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

---

### Task 6: Frontend — API client types for the new fields

**Files:**
- Modify: `frontend/lib/api/admin.ts` (`BillingSetupRow` line 2227, `BillingSetupListParams` line 2257, `fetchBillingSetup` line 2264). **Line numbers are pre-plan-1**: `2026-09-10-departure-actions-from-student-page.md` Task 6 adds `notify_family?: boolean;` to `WithdrawEnrollmentRequest` (~line 227) in this same file first, shifting everything below by a line. Locate the symbols by name.
- Modify: `frontend/lib/query/keys.ts` (`queryKeys.admin.billingSetup`, lines 120–122)
- Modify: `frontend/lib/api/admin-families.ts` (`FamilyAction` union line 11, `FamilyHeader` interface line 50; add `sendFamilyPasswordReset`, `updateFamilyContact`)
- Test: none (pure types + thin fetch wrappers — covered by the frontend tests in Tasks 7–8 that consume them)

**Interfaces:**
- Produces: `BillingSetupRow.parent_phone`, `BillingSetupRow.login_state`; `BillingSetupListParams.login_state`; `queryKeys.admin.billingSetup` keyed on `login_state`; `FamilyAction` gains `"send_password_reset" | "edit_contact"`; `sendFamilyPasswordReset(parentId): Promise<{ok:boolean}>`; `updateFamilyContact(parentId, {display_name?, phone?, reason}): Promise<AdminFamilyBillingView>`

Steps:

- [ ] 6.1 Read `frontend/lib/api/admin-families.ts` in full to match its existing `apiFetch` call conventions (mirror `pauseFamilyAutopay`'s shape exactly).

- [ ] 6.2 In `frontend/lib/api/admin.ts`, extend `BillingSetupRow` (lines 2227–2242):

```typescript
export type BillingSetupLoginState = "never_invited" | "invited" | "active";

export interface BillingSetupRow {
  parent_id: string;
  parent_name: string;
  parent_email: string | null;
  parent_phone: string | null;
  students: BillingSetupStudent[];
  registration_state: BillingSetupRegistrationState;
  login_state: BillingSetupLoginState;
  card_label: string | null;
  card_last4: string | null;
  autopay_active_count: number;
  autopay_eligible_count: number;
  outstanding_balance_cents: number;
  charge_invoice_id: string | null;
  charge_amount_cents: number;
  charge_autopay_eligible: boolean;
  last_invited_at: string | null;
}
```

  Extend `BillingSetupListParams` (line 2257) with `login_state?: "all" | BillingSetupLoginState;` and update `fetchBillingSetup` (line 2264) to append it: `if (params.login_state) search.set("login_state", params.login_state);`.

- [ ] 6.2b **Extend the query key** in `frontend/lib/query/keys.ts` (lines 120–122). Today it is:

```typescript
    billingSetup: (params?: { status?: string; q?: string }) =>
      [...queryKeys.admin.billingSetupAll(), params?.status ?? "all", params?.q ?? ""] as const,
```

  `login_state` is not part of the key, so `/admin/families` would serve the cached
  "all logins" page when the login filter changes — the filter would look broken and,
  worse, silently show the wrong rows. Change it to:

```typescript
    billingSetup: (params?: { status?: string; q?: string; login_state?: string }) =>
      [
        ...queryKeys.admin.billingSetupAll(),
        params?.status ?? "all",
        params?.q ?? "",
        params?.login_state ?? "all",
      ] as const,
```

  Then `grep -rn "queryKeys.admin.billingSetup" frontend` and confirm every caller still
  typechecks (the extra field is optional, so existing callers are unaffected).

- [ ] 6.3 In `frontend/lib/api/admin-families.ts`, add the two new calls (mirror `pauseFamilyAutopay`'s existing pattern exactly, found by reading the file per step 6.1):

```typescript
export function sendFamilyPasswordReset(parentId: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(
    `/families/${encodeURIComponent(parentId)}/password-reset`,
    { method: "POST" },
  );
}

export interface UpdateFamilyContactRequest {
  display_name?: string;
  phone?: string;
  reason: string;
}

export function updateFamilyContact(
  parentId: string,
  payload: UpdateFamilyContactRequest,
): Promise<AdminFamilyBillingView> {
  return apiFetch<AdminFamilyBillingView>(
    `/families/${encodeURIComponent(parentId)}/contact`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
}
```

  Add to the `FamilyHeader` interface (line 50, mirrors `families_views.py`'s `FamilyHeader`):
  `login: { state: "never_invited" | "invited" | "active"; last_invited_at: string | null } | null;`
  (nullable to match the backend model's `FamilyLogin | None = None`, so
  `FamilyHeader.login` is narrowed at the call site rather than assumed present).

- [ ] 6.3b **Extend the `FamilyAction` union** in `frontend/lib/api/admin-families.ts` (lines 11–16):

```typescript
export type FamilyAction =
  | "send_invite"
  | "autopay_on"
  | "autopay_off"
  | "send_invoice"
  | "record_payment"
  | "send_password_reset"
  | "edit_contact";
```

  Without this, Task 8.4's `actions.includes("send_password_reset")` is a hard
  typecheck error (`"send_password_reset" is not assignable to parameter of type FamilyAction`).

- [ ] 6.4 Run `cd frontend && pnpm typecheck` — expect PASS (no consumers reference the new fields yet, so this only validates the type edits themselves compile).

- [ ] 6.5 Commit:
  `git add frontend/lib/api/admin.ts frontend/lib/api/admin-families.ts frontend/lib/query/keys.ts`
  Message:
  ```
  feat(frontend): API client types for family login state, password reset, contact edit

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

---

### Task 7: Frontend — Families list: new columns, contact, login filter

**Files:**
- Modify: `frontend/app/(admin)/admin/families/page.tsx` (full rewrite of the table structure, lines 90–231)
- Test: `frontend/e2e/specs/admin-family-billing.spec.ts` (read it first to match existing `data-testid` conventions before adding assertions)

**Interfaces:**
- Consumes: `fetchBillingSetup` (Task 6), `inviteBillingSetupParent` (existing, `frontend/lib/api/admin.ts` line 2285)
- Produces: no new exports — page component only

Steps:

- [ ] 7.1 Read `frontend/e2e/specs/admin-family-billing.spec.ts` in full to see what `data-testid`s it already asserts on the list page (`admin-families`, `family-link-<id>` from `page.tsx` line 192) so the rewrite doesn't break them.

- [ ] 7.2 Rewrite the `FILTERS` array and add a login-state filter row, and replace the table's `<thead>`/`<tbody>` to match spec §3's column order (Family / Contact / Login / Billing / Autopay / Outstanding / Actions). Replace `page.tsx` lines 47–52 and 145–231.

  Three things the original draft missed — do them or the build breaks:
  1. Renaming `FILTERS` → `REGISTRATION_FILTERS` also requires updating the `FILTERS.map(...)`
     JSX at **line ~117**, which is *outside* the 145–231 replacement range.
  2. Dropping the "Card" and "Invited" columns leaves `formatDate` (lines 35–40) unused —
     `pnpm lint` will fail on it. Delete `formatDate` too.
  3. Add `login_state: loginState` to the `params` memo (line 68) *and* rely on the
     Task 6.2b query-key change; without both, the filter is a no-op.

```typescript
const REGISTRATION_FILTERS: { value: "all" | BillingSetupRegistrationState; label: string }[] = [
  { value: "all", label: "All billing" },
  { value: "no_account", label: "Not invited" },
  { value: "account_no_card", label: "No card" },
  { value: "card_on_file", label: "Chargeable" },
];

const LOGIN_FILTERS: { value: "all" | BillingSetupLoginState; label: string }[] = [
  { value: "all", label: "All login" },
  { value: "never_invited", label: "Never invited" },
  { value: "invited", label: "Invited" },
  { value: "active", label: "Active" },
];

function loginChip(state: BillingSetupLoginState): { variant: ChipVariant; label: string } {
  if (state === "active") return { variant: "paid", label: "ACTIVE" };
  if (state === "invited") return { variant: "pending", label: "INVITED" };
  return { variant: "nocharge", label: "NEVER INVITED" };
}
```

  Update the `useState`/`useMemo` block to track both filters:

```typescript
  const [status, setStatus] = useState<"all" | BillingSetupRegistrationState>("all");
  const [loginState, setLoginState] = useState<"all" | BillingSetupLoginState>("all");
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQ(q.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [q]);

  const params = useMemo(
    () => ({ status, login_state: loginState, q: debouncedQ || undefined }),
    [status, loginState, debouncedQ],
  );
```

  Update the search input placeholder (line 129–134 area): `placeholder="Search name, email, phone, or child…"`.

  Add the login-state filter pill row next to the existing one (after the `FILTERS.map` block):

```jsx
        <div className="flex gap-1 rounded-md border border-slate-200 bg-white p-1">
          {LOGIN_FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => setLoginState(f.value)}
              className={`rounded px-3 py-1.5 text-sm font-medium ${
                loginState === f.value ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
              }`}
              data-testid={`family-login-filter-${f.value}`}
            >
              {f.label}
            </button>
          ))}
        </div>
```

  Replace the `<thead>` (lines 147–157):

```jsx
                <tr className="border-b border-slate-200 text-xs uppercase text-slate-500">
                  <th className="px-4 py-3">Family</th>
                  <th className="px-4 py-3">Contact</th>
                  <th className="px-4 py-3">Login</th>
                  <th className="px-4 py-3">Billing</th>
                  <th className="px-4 py-3">Autopay</th>
                  <th className="px-4 py-3">Outstanding</th>
                  <th className="px-4 py-3">Actions</th>
                </tr>
```

  Rewrite `FamilyTableRow` (lines 183–231) to render Contact and Login columns and an inline "Send invite" action:

```jsx
function FamilyTableRow({ row }: { row: BillingSetupRow }) {
  const billingChip = stateChip(row.registration_state);
  const login = loginChip(row.login_state);
  const href = familyHref(row.parent_id);
  const queryClient = useQueryClient();
  const inviteMutation = useMutation({
    mutationFn: () => inviteBillingSetupParent(row.parent_id),
    // Without this the Login chip keeps showing the pre-invite state and
    // Task 8.7's "invite click updates it" e2e assertion fails.
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.billingSetupAll() }),
  });

  return (
    <tr className="border-b border-slate-100 last:border-0">
      <td className="px-4 py-3">
        <Link
          href={href}
          data-testid={`family-link-${row.parent_id}`}
          className="font-medium text-slate-900 hover:underline"
        >
          {row.parent_name}
        </Link>
        <div className="mt-1 flex flex-wrap gap-1">
          {row.students.map((s) => (
            <span
              key={s.student_id}
              className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600"
            >
              {s.full_name}
            </span>
          ))}
        </div>
      </td>
      <td className="px-4 py-3 text-xs text-slate-600">
        <div>{row.parent_email ?? "—"}</div>
        <div>{row.parent_phone ?? "—"}</div>
      </td>
      <td className="px-4 py-3">
        <Chip variant={login.variant} label={login.label} />
      </td>
      <td className="px-4 py-3">
        <Chip variant={billingChip.variant} label={billingChip.label} />
      </td>
      <td className="px-4 py-3 text-slate-700">
        {row.autopay_active_count > 0 || row.autopay_eligible_count > 0
          ? `${row.autopay_active_count} active · ${row.autopay_eligible_count} resumable`
          : "—"}
      </td>
      <td className="px-4 py-3 text-slate-700">{formatCents(row.outstanding_balance_cents)}</td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-3">
          <Link href={href} className="text-sm font-medium text-rally-cobalt-700 hover:underline">
            Open
          </Link>
          {row.login_state !== "active" && (
            <Button
              size="sm"
              variant="secondary"
              disabled={inviteMutation.isPending}
              onClick={() => inviteMutation.mutate()}
              data-testid={`family-invite-${row.parent_id}`}
            >
              {inviteMutation.isPending ? "Sending…" : "Send invite"}
            </Button>
          )}
        </div>
      </td>
    </tr>
  );
}
```

  Add `useMutation` and `useQueryClient` from `@tanstack/react-query` (the file today imports only `useInfiniteQuery`), `type BillingSetupLoginState` and `inviteBillingSetupParent` from `@/lib/api/admin`. `queryKeys` and `Chip`/`ChipVariant` are already imported (lines 22, 26).

  `loginChip`'s `"nocharge"` / `"pending"` / `"paid"` are all real `ChipVariant` members
  (`frontend/components/ds/chip.tsx` lines 5–11) — verified.

- [ ] 7.3 Run typecheck and lint: `cd frontend && pnpm typecheck && pnpm lint`.

- [ ] 7.4 Run any existing vitest for this page if one exists: `ls frontend/app/\(admin\)/admin/families/__tests__/ 2>/dev/null || echo none`; if a test file exists, run `pnpm vitest run <path>` and fix any failures from the column rename.

- [ ] 7.5 Manually verify with `pnpm exec playwright test admin-family-billing.spec.ts --project=chromium` (existing spec) — expect PASS (it should still find `family-link-<id>`, unaffected by the column reshuffle).

- [ ] 7.6 Commit:
  `git add frontend/app/\(admin\)/admin/families/page.tsx`
  Message:
  ```
  feat(frontend): families list gets Contact/Login columns + login filter

  Spec 2026-09-10-families-directory-consolidation §3.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

---

### Task 8: Frontend — FamilyHeader identity strip (mailto/tel, login badge, password reset, edit contact)

**Files:**
- Create: `frontend/app/(admin)/admin/families/[parentId]/EditContactDialog.tsx`
- Modify: `frontend/app/(admin)/admin/families/[parentId]/FamilyHeader.tsx` (lines 30–89)
- Modify: `frontend/app/(admin)/admin/families/[parentId]/page.tsx` (wire new callbacks, lines 197–215)
- Modify: `frontend/app/(admin)/admin/families/[parentId]/family-view.ts` (add a `loginChip`/badge helper alongside the existing `registrationChip`/`autopayToggle` — read this file first to match its style; it wasn't opened this session, so read it before editing)

**Interfaces:**
- Consumes: `sendFamilyPasswordReset`, `updateFamilyContact` (Task 6)
- Produces: `EditContactDialog` component (props: `open`, `parentId`, `initialName`, `initialPhone`, `onClose`, `onSaved`)

Steps:

- [ ] 8.1 Read `frontend/app/(admin)/admin/families/[parentId]/family-view.ts` and `family-dialogs.tsx` in full before writing new code, to match the existing helper/dialog conventions exactly (dialog styling should mirror `ReasonDialog` in `family-dialogs.tsx`, not reinvent a new pattern).

- [ ] 8.2 In `family-view.ts`, add next to `registrationChip` (line ~77), matching its existing `RegistrationChip { label; variant: ChipVariant }` return shape (`ChipVariant` is already imported at line 2). Note `registrationChip` uses `"manual"` — not `"nocharge"` — for its "Not invited" state; use `"manual"` here too so the two chips do not disagree visually for the same parent:

```typescript
export function loginBadge(
  login: { state: "never_invited" | "invited" | "active" } | null,
): RegistrationChip {
  if (login?.state === "active") return { label: "Login active", variant: "paid" };
  if (login?.state === "invited") return { label: "Invite sent", variant: "pending" };
  return { label: "Never invited", variant: "manual" };
}
```

  (Accepting `null` matches the `FamilyHeader.login` type from Task 6.3.) Add a case to
  the existing `frontend/app/(admin)/admin/families/[parentId]/family-view.test.ts`
  covering all three states plus `null`, matching that file's existing style. Note per
  project memory: frontend vitest files run in **no CI job**, so run it locally —
  `cd frontend && pnpm vitest run "app/(admin)/admin/families/[parentId]/family-view.test.ts"`.

- [ ] 8.3 Create `EditContactDialog.tsx` following the `Dialog.Root` pattern already used in `frontend/components/admin/AdminUsersDirectory.tsx` (lines 180–268, read this session):

```tsx
"use client";

import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useMutation } from "@tanstack/react-query";

import { Button } from "@/components/ds/button";
import { updateFamilyContact } from "@/lib/api/admin-families";

export function EditContactDialog({
  open,
  parentId,
  initialName,
  initialPhone,
  onClose,
  onSaved,
}: {
  open: boolean;
  parentId: string;
  initialName: string;
  initialPhone: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [displayName, setDisplayName] = useState(initialName);
  const [phone, setPhone] = useState(initialPhone);
  const [reason, setReason] = useState("Contact info correction");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      updateFamilyContact(parentId, {
        display_name: displayName.trim() || undefined,
        phone: phone.trim() || undefined,
        reason,
      }),
    onSuccess: () => {
      setError(null);
      onSaved();
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : "Could not update contact details.");
    },
  });

  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-neutral-950/40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(92vw,480px)] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-rally-line bg-white p-5 shadow-xl focus:outline-none">
          <Dialog.Title className="font-display text-xl font-bold text-rally-ink">
            Edit contact details
          </Dialog.Title>
          <form
            className="mt-4 space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              setError(null);
              mutation.mutate();
            }}
          >
            <label className="block">
              <span className="mb-1.5 block font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Name
              </span>
              <input
                data-testid="edit-contact-name"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                required
                maxLength={120}
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Phone
              </span>
              <input
                data-testid="edit-contact-phone"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                maxLength={40}
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Reason
              </span>
              <input
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                required
                maxLength={500}
              />
            </label>
            {error && (
              <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
                {error}
              </p>
            )}
            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="secondary" onClick={onClose}>
                Cancel
              </Button>
              <Button type="submit" disabled={mutation.isPending} data-testid="edit-contact-save">
                {mutation.isPending ? "Saving..." : "Save"}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
```

- [ ] 8.4 Rewrite `FamilyHeader.tsx`'s identity block (lines 30–63) to add mailto/tel links, the login badge, and the two new action buttons, and thread the new `onSendPasswordReset`/`onEditContact` props:

```tsx
export function FamilyHeader({
  view,
  busy,
  onToggleAutopay,
  onSendInvite,
  onSendInvoice,
  onRecordPayment,
  onSendPasswordReset,
  onEditContact,
}: {
  view: AdminFamilyBillingView;
  busy: boolean;
  onToggleAutopay: (turnOn: boolean) => void;
  onSendInvite: () => void;
  onSendInvoice: () => void;
  onRecordPayment: () => void;
  onSendPasswordReset: () => void;
  onEditContact: () => void;
}) {
  const { parent, header, actions } = view;
  const toggle = autopayToggle(header.autopay);
  const reg = registrationChip(header.registration.state);
  const login = loginBadge(header.login ?? null);
  const studentCount = view.students.length;
  return (
    <Card p={20}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="font-display text-xl font-semibold text-rally-ink">
            {parent.name ?? "Parent"}
          </h1>
          <p className="text-sm text-rally-muted">
            {parent.email ? (
              <a href={`mailto:${parent.email}`} className="hover:underline">
                {parent.email}
              </a>
            ) : (
              "no email"
            )}
            {" · "}
            {studentCount} {studentCount === 1 ? "student" : "students"}
            {parent.phone && (
              <>
                {" · "}
                <a href={`tel:${parent.phone}`} className="hover:underline">
                  {parent.phone}
                </a>
              </>
            )}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span data-testid="family-registration-chip">
              <Chip variant={reg.variant} label={reg.label} />
            </span>
            <span data-testid="family-login-chip">
              <Chip variant={login.variant} label={login.label} />
            </span>
            {actions.includes("send_invite") && (
              <Button
                size="sm"
                variant="secondary"
                data-testid="family-send-invite"
                onClick={onSendInvite}
                disabled={busy}
              >
                {header.login?.last_invited_at ? "Resend invite" : "Send invite"}
              </Button>
            )}
            {actions.includes("send_password_reset") && (
              <Button
                size="sm"
                variant="secondary"
                data-testid="family-send-password-reset"
                onClick={onSendPasswordReset}
                disabled={busy}
              >
                Send password reset
              </Button>
            )}
            {actions.includes("edit_contact") && (
              <Button
                size="sm"
                variant="secondary"
                data-testid="family-edit-contact"
                onClick={onEditContact}
                disabled={busy}
              >
                Edit contact details
              </Button>
            )}
            <Link
              href={`/admin/messages?dm=${encodeURIComponent(parent.parent_id)}`}
              className="text-sm text-rally-cobalt-700 hover:underline"
            >
              Message
            </Link>
          </div>
        </div>
        ...
```

  (Keep the rest of the component — the `send_invoice`/`record_payment` buttons and the `Tile` grid — unchanged; only the identity block above and the prop list change. Import `loginBadge` from `./family-view`.)

- [ ] 8.5 In `page.tsx`, add local state for the edit-contact dialog and wire the two new `FamilyHeader` callbacks (around lines 48–55 and 197–215):

```typescript
  const [editContactOpen, setEditContactOpen] = useState(false);
```

```jsx
      <FamilyHeader
        view={view}
        busy={simple.isPending}
        onToggleAutopay={...}
        onSendInvite={...}
        onSendInvoice={...}
        onRecordPayment={...}
        onSendPasswordReset={() =>
          simple.mutate(async () => {
            const r = await sendFamilyPasswordReset(parentId);
            setToast(r.ok ? "Password reset sent." : "Password reset failed.");
          })
        }
        onEditContact={() => setEditContactOpen(true)}
      />
      <EditContactDialog
        open={editContactOpen}
        parentId={parentId}
        initialName={view.parent.name ?? ""}
        initialPhone={view.parent.phone ?? ""}
        onClose={() => setEditContactOpen(false)}
        onSaved={() => {
          setEditContactOpen(false);
          void refresh();
        }}
      />
```

  Add `sendFamilyPasswordReset` to the `@/lib/api/admin-families` import and `EditContactDialog` to the local imports.

- [ ] 8.6 Run `cd frontend && pnpm typecheck && pnpm lint`.

- [ ] 8.7 Add a Playwright assertion to `admin-family-billing.spec.ts` (read the file's existing test structure first) covering: login badge renders `family-login-chip`, invite click updates it, edit-contact dialog saves and closes. Run: `cd frontend && pnpm exec playwright test admin-family-billing.spec.ts --project=chromium`.

- [ ] 8.8 Commit:
  `git add "frontend/app/(admin)/admin/families/[parentId]/EditContactDialog.tsx" "frontend/app/(admin)/admin/families/[parentId]/FamilyHeader.tsx" "frontend/app/(admin)/admin/families/[parentId]/page.tsx" "frontend/app/(admin)/admin/families/[parentId]/family-view.ts" frontend/e2e/specs/admin-family-billing.spec.ts`
  Message:
  ```
  feat(frontend): FamilyHeader becomes identity strip (login badge, reset, edit contact)

  Spec 2026-09-10-families-directory-consolidation §4.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

---

### Task 9: Frontend — redirects (`/admin/parents`, `/admin/users?role=parent`) to `/admin/families`

**Files:**
- Modify: `frontend/app/(admin)/admin/parents/page.tsx` (currently 5 lines, `redirect("/admin/users?role=parent")`)
- Modify: `frontend/app/(admin)/admin/users/page.tsx` (currently 10 lines, no redirect logic)
- Test: `frontend/e2e/specs/saas-launch-route-matrix.spec.ts` (read first to match its existing redirect-assertion style)

**Interfaces:**
- Produces: `GET /admin/parents` → 307/308 to `/admin/families`; `GET /admin/users?role=parent` → client-side redirect to `/admin/families`

Steps:

- [ ] 9.1 Read `frontend/e2e/specs/saas-launch-route-matrix.spec.ts` in full to find its existing assertion(s) for `/admin/parents` (grep `grep -n "admin/parents\|admin/users" frontend/e2e/specs/saas-launch-route-matrix.spec.ts`) and match its style exactly when updating.

- [ ] 9.2 Update `frontend/app/(admin)/admin/parents/page.tsx`:

```typescript
import { redirect } from "next/navigation";

export default function AdminParentsPage() {
  redirect("/admin/families");
}
```

- [ ] 9.3 Update `frontend/app/(admin)/admin/users/page.tsx` to redirect when `role=parent` is present. Since `redirect()` from `next/navigation` needs a server component and this page is currently a server component (no `"use client"` directive at its top — confirm by re-reading it), use `searchParams`:

```tsx
import { Suspense } from "react";
import { redirect } from "next/navigation";

import { AdminUsersDirectory } from "@/components/admin/AdminUsersDirectory";

export default async function AdminUsersPage({
  searchParams,
}: {
  searchParams: Promise<{ role?: string }>;
}) {
  const { role } = await searchParams;
  if (role === "parent") {
    redirect("/admin/families");
  }
  return (
    <Suspense>
      <AdminUsersDirectory />
    </Suspense>
  );
}
```

  Next.js 16's `searchParams` prop is a `Promise`. Confirm against a page in this repo that already reads it server-side before assuming the shape:
  `grep -rln "searchParams" frontend/app --include='page.tsx' | head` then read one. Do not
  guess. Note the current `users/page.tsx` (11 lines) has no `"use client"` directive, so
  it is already a server component and `redirect()` is legal there.

  Also note the two redirects are not equivalent: `/admin/parents` redirects
  unconditionally (a server redirect, 307/308 on a hard navigation), while
  `/admin/users?role=parent` redirects only when the query param is present. A client-side
  `router.replace` inside `AdminUsersDirectory` would ALSO work but would double-render
  the directory; the server-side `searchParams` check above avoids that. Keep the server
  version.

- [ ] 9.4 Update `frontend/e2e/specs/saas-launch-route-matrix.spec.ts` and/or `admin-shell.spec.ts` per spec §9: assert `/admin/parents` and `/admin/users?role=parent` land on `/admin/families`. Add (matching the file's existing test structure, read in step 9.1):

```typescript
test("/admin/parents redirects to /admin/families", async ({ page }) => {
  await page.goto("/admin/parents");
  await expect(page).toHaveURL(/\/admin\/families/);
});

test("/admin/users?role=parent redirects to /admin/families", async ({ page }) => {
  await page.goto("/admin/users?role=parent");
  await expect(page).toHaveURL(/\/admin\/families/);
});
```

- [ ] 9.5 Run: `cd frontend && pnpm exec playwright test saas-launch-route-matrix.spec.ts admin-shell.spec.ts --project=chromium` — expect PASS.

- [ ] 9.6 Run `cd frontend && pnpm typecheck` to confirm the `searchParams` Promise typing is correct.

- [ ] 9.7 Commit:
  `git add "frontend/app/(admin)/admin/parents/page.tsx" "frontend/app/(admin)/admin/users/page.tsx" frontend/e2e/specs/saas-launch-route-matrix.spec.ts frontend/e2e/specs/admin-shell.spec.ts`
  Message:
  ```
  feat(frontend): /admin/parents and /admin/users?role=parent redirect to /admin/families

  Spec 2026-09-10-families-directory-consolidation §2, §7.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

---

### Task 10: Frontend — drop the Parents pill from `AdminUsersDirectory`; move "Add parent" to Families

**Files:**
- Modify: `frontend/components/admin/AdminUsersDirectory.tsx` (`roles` array line 26–32, `CreatableRole` line 35, `fixedRole` prop line 47–50, `CreateUserDialog` role handling lines 140–208)
- Modify: `frontend/app/(admin)/admin/families/page.tsx` — add an "Add parent" button + dialog (reuse `CreateUserDialog`'s shape, but do not import a component from `AdminUsersDirectory.tsx` that is about to lose its parent-creation support — instead extract a small shared `CreateParentDialog` or inline one on the Families page)
- Test: any existing `frontend/components/admin/__tests__/AdminUsersDirectory*` test (check with `ls frontend/components/admin/__tests__/ 2>/dev/null | grep -i users`)

**Interfaces:**
- Produces: `AdminUsersDirectory` no longer renders a "Parents" tab or accepts `fixedRole="parent"`; `/admin/families` page gains an "Add parent" button using `createAdminUser({role: "parent", ...})` (already exists, `frontend/lib/api/admin.ts`, used at `AdminUsersDirectory.tsx` line 160)

Steps:

- [ ] 10.1 Check for an existing component test: `ls frontend/components/admin/__tests__/ 2>/dev/null`. If `AdminUsersDirectory.test.tsx` (or similar) exists, read it fully before editing so the changes below keep it green or you update its now-invalid parent-pill assertions in the same commit.

- [ ] 10.2 In `AdminUsersDirectory.tsx`, drop `parent` from the `roles` array (lines 26–32), `CreatableRole` (line 35), `parseRoleParam` (lines 37–44) and the `fixedRole` type. **`fixedRole` is typed in three places, not one** — lines 49, 148 (`CreateUserDialog`'s props) and the ternaries at 73, 186. Verified this session: no caller anywhere in `frontend/` actually passes `fixedRole="parent"` (`grep -rn "fixedRole" frontend --include='*.tsx'` shows only internal uses), so this is a type-only narrowing with no call-site fallout.

```typescript
const roles: Array<{ label: string; value: AdminUserRole | undefined }> = [
  { label: "All", value: undefined },
  { label: "Coaches", value: "coach" },
  { label: "Assistant coaches", value: "assistant_coach" },
  { label: "Admins", value: "admin" },
];

type CreatableRole = Extract<AdminUserRole, "coach" | "assistant_coach">;

function parseRoleParam(value: string | null): AdminUserRole | undefined {
  return value === "coach" || value === "assistant_coach" || value === "admin"
    ? value
    : undefined;
}

export function AdminUsersDirectory({
  fixedRole,
}: {
  fixedRole?: Extract<AdminUserRole, "coach">;
}) {
```

  Update `createLabel` (line 73) to drop the `parent` branch: `const createLabel = fixedRole === "coach" ? "Add coach" : "Add user";`, and the identical ternary in `CreateUserDialog`'s `<Dialog.Title>` (line 186).

  In `CreateUserDialog`, change the default `role` state (line 151) from `useState<CreatableRole>(fixedRole ?? "parent")` to `useState<CreatableRole>(fixedRole ?? "coach")` — it currently defaults to `"parent"`, which would no longer be a `CreatableRole` — and remove `<option value="parent">Parent</option>` from the role `<select>` (line ~203).

- [ ] 10.3 Add a minimal parent-creation dialog to the Families list page. Reuse the exact `Dialog.Root`/`Field` pattern already proven in Task 8's `EditContactDialog.tsx` and in `AdminUsersDirectory.tsx`'s `CreateUserDialog`, calling `createAdminUser({ role: "parent", ... })` from `@/lib/api/admin`. Add to `frontend/app/(admin)/admin/families/page.tsx`, above the filter row:

```tsx
        <Button
          size="sm"
          icon={<Plus className="size-4" aria-hidden="true" />}
          onClick={() => setAddParentOpen(true)}
          data-testid="families-add-parent"
        >
          Add parent
        </Button>
```

  with `const [addParentOpen, setAddParentOpen] = useState(false);`, `const queryClient = useQueryClient();` and:

```tsx
        <CreateParentDialog
          open={addParentOpen}
          onOpenChange={setAddParentOpen}
          onCreated={() => {
            setAddParentOpen(false);
            void queryClient.invalidateQueries({
              queryKey: queryKeys.admin.billingSetupAll(),
            });
          }}
        />
```

  Define `CreateParentDialog` in a co-located `CreateParentDialog.tsx`, copying the field
  set (Name, Email, Phone, Reason) from `CreateUserDialog` (`AdminUsersDirectory.tsx`
  lines 140–268) verbatim, minus the role `<select>` (role is fixed to `"parent"`), and
  calling `createAdminUser({ role: "parent", display_name, email, phone: phone || null, reason })`
  from `@/lib/api/admin`. `createAdminUser` takes `AdminUserRole`, not the directory's
  local `CreatableRole`, so narrowing `CreatableRole` in 10.2 does not block this — confirm
  by reading its signature in `frontend/lib/api/admin.ts` first. Also import `Plus` from
  `lucide-react` for the button icon (the Families page does not import it today).

- [ ] 10.4 Run `cd frontend && pnpm typecheck && pnpm lint`.

- [ ] 10.5 Run the component test from 10.1 if it exists, or the broader unit suite touching this file: `cd frontend && pnpm vitest run frontend/components/admin/AdminUsersDirectory.test.tsx` (adjust path to what 10.1 found).

- [ ] 10.6 Run `pnpm exec playwright test admin-shell.spec.ts --project=chromium` (read the file first — it likely asserts nav pills/tabs; update any now-invalid "Parents" pill assertion in the same commit).

- [ ] 10.7 Commit:
  `git add frontend/components/admin/AdminUsersDirectory.tsx "frontend/app/(admin)/admin/families/page.tsx" "frontend/app/(admin)/admin/families/CreateParentDialog.tsx" frontend/e2e/specs/admin-shell.spec.ts`
  Message:
  ```
  feat(frontend): drop Parents pill from Users directory; Add parent moves to Families

  Spec 2026-09-10-families-directory-consolidation §2, §5.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

---

### Task 11: Frontend — user detail page shows a pointer for parents, hides the invite panel

**Files:**
- Modify: `frontend/app/(admin)/admin/users/[userId]/page.tsx` (lines 75–104, `LoginInvitePanel` render at line 99)

**Interfaces:**
- Produces: for `user.role === "parent"`, the page renders a banner "This is a parent — manage on the family page" linking to `/admin/families/${user.user_id}`, and does not render `LoginInvitePanel`

Steps:

- [ ] 11.1 Before editing, confirm a parent's `user_id` is the same id used as `parentId` in `/admin/families/[parentId]` — grep `grep -n "parent_id\b" backend/v2/contexts/billing/infrastructure/family_billing_read_model.py` (already read this session: `_parent` at line 398 queries `users` by `user_id`/`auth_uid`/`_id`, and `ParentFacts.parent_id` is set to the same `parent_id` the route received) — this confirms `user.user_id` from the Users directory is a valid `parentId` for the family route.

- [ ] 11.2 Edit lines 75–103 (verified this session: `const user = userQuery.data;` is at line 75, `const isCoach = ...` at 76, the `return (` block runs 85–103, and `<LoginInvitePanel user={user} onSaved={invalidate} />` is at line 99 — unconditional today):

```tsx
  const user = userQuery.data;
  const isCoach = user.role === "coach";
  const isParent = user.role === "parent";
  ...
  return (
    <section className="space-y-6" data-testid="admin-user-detail">
      <BackLink />
      <Header user={user} />
      {isParent && (
        <Card p={20} data-testid="admin-user-parent-pointer">
          <p className="text-sm text-rally-base">
            This is a parent — manage on the family page.{" "}
            <Link
              href={`/admin/families/${encodeURIComponent(user.user_id)}`}
              className="font-medium text-rally-cobalt-700 hover:underline"
            >
              Open family page
            </Link>
          </p>
        </Card>
      )}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card p={20} className="lg:col-span-2">
          <Overline>Profile</Overline>
          <UserEditForm user={user} onSaved={invalidate} />
        </Card>
        <Card p={20}>
          <Overline>Access</Overline>
          <RolesPanel user={user} onSaved={invalidate} />
        </Card>
      </div>
      {!isParent && <LoginInvitePanel user={user} onSaved={invalidate} />}
      {isCoach && <CoachPayRatePanel coachId={user.user_id} />}
      {isCoach && <CoachSessionsPanel user={user} onAssigned={invalidate} />}
    </section>
  );
```

  Add `import Link from "next/link";` at the top of the file if not already present (check first — `AdminUsersDirectory.tsx` already imports it, this file may too).

- [ ] 11.3 Run `cd frontend && pnpm typecheck && pnpm lint`.

- [ ] 11.4 Add/update a Playwright assertion in `admin-shell.spec.ts` (per spec §9: "user detail for a parent shows the pointer and hides the invite panel") — read the file's existing structure first, then add:

  Do not hardcode a parent id. Navigate to one, the way the spec file already reaches
  seeded users — read its existing helpers first, then write the test in that shape:

```typescript
test("user detail for a parent shows the family pointer, hides invite panel", async ({ page }) => {
  // Reach a real seeded parent through the directory rather than hardcoding an
  // id: /admin/users?role=parent now redirects (Task 9), so go via the API stub
  // / fixture this spec file already uses for admin users, or open a family and
  // reuse its parentId as the userId (Task 11.1 proves they are the same id).
  await page.goto(`/admin/users/${parentUserId}`);
  await expect(page.getByTestId("admin-user-parent-pointer")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send login invite" })).toHaveCount(0);
});
```

  `"Send login invite"` is the real label — `LoginInvitePanel` is at
  `frontend/app/(admin)/admin/users/[userId]/page.tsx` line 786 and its button text is at
  line 834 (`… : "Send login invite"`), verified this session. Read lines 786–840 to see
  the resend variant's label before asserting `toHaveCount(0)` on only one of them.

- [ ] 11.5 Run `cd frontend && pnpm exec playwright test admin-shell.spec.ts --project=chromium`.

- [ ] 11.6 Commit:
  `git add "frontend/app/(admin)/admin/users/[userId]/page.tsx" frontend/e2e/specs/admin-shell.spec.ts`
  Message:
  ```
  feat(frontend): parent user-detail page points to the family page, hides invite panel

  Spec 2026-09-10-families-directory-consolidation §5.

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

---

### Task 11b: Backend — parents with no students still appear in the list

> **Owner decision 2026-09-10.** `ListBillingSetup.execute` derives its roster from
> students (`list_admin_students` → group by `parent_id`), so a parent user with
> zero student rows is absent from `/admin/families` while being present in
> `/admin/users?role=parent` today. Task 9's redirect would make those people
> unreachable. Before running this task, confirm the premise with a one-line check
> against the read model, and if `ListBillingSetup` already unions the users
> collection, skip this task and record that in the Self-review.

**Files:**
- Modify: `backend/v2/contexts/billing/application/use_cases/billing_setup_registration.py` (`ListBillingSetup.execute`, and the roster port it calls)
- Modify: `backend/v2/composition/families.py` (`_BillingSetupRosterAdapter` — the adapter that supplies parents)
- Test: the same test module Task 3 created/extended for `ListBillingSetup`

**Interfaces:**
- Consumes: `BillingSetupRow` and the `login_state` facet from Task 3.
- Produces: rows for every parent-role user in the tenant, whether or not they have students. `BillingSetupRow.student_names` is an empty list for those rows; no field is added.

- [ ] **Step 1: Write the failing test.** In the `ListBillingSetup` test module:

```python
@pytest.mark.asyncio
async def test_lists_a_parent_who_has_no_students():
    """A parent invited but never enrolled must not vanish from the Families
    list — after the Parents directory retires this is the only place they
    exist (owner decision 2026-09-10)."""
    use_case = _build(  # the module's existing builder helper — reuse it
        parents=[_parent("usr-childless", display_name="Ravi Kumar", email="ravi@example.com")],
        students=[],
    )
    result = await use_case.execute(BillingSetupQuery())
    assert [r.parent_id for r in result.rows] == ["usr-childless"]
    assert result.rows[0].student_names == []
```

- [ ] **Step 2: Run it and confirm it fails.**

Run: `cd backend && pytest v2/tests -k "billing_setup and childless" -v`
Expected: FAIL — `assert [] == ['usr-childless']`, because the roster is built from students only.

- [ ] **Step 3: Read the current roster derivation before changing it.**

Run: `cd backend && grep -n "list_parents\|parent_id\|RosterPort\|_BillingSetupRosterAdapter" v2/contexts/billing/application/use_cases/billing_setup_registration.py v2/composition/families.py`
Record which side owns "who is a parent" — the use case or the adapter. Make the change on that side only; do not add a second source of truth.

- [ ] **Step 4: Union the parent users into the roster.** In `_BillingSetupRosterAdapter` (`composition/families.py`), after the student-derived grouping is built, add every `role=parent` user in the tenant that the grouping does not already contain, with an empty student list. One query, tenant-scoped:

```python
        async for user_doc in db["users"].find(
            {"academy_id": academy_id, "roles": "parent"},
            {"user_id": 1, "display_name": 1, "email": 1, "phone": 1},
        ):
            parent_id = str(user_doc.get("user_id"))
            if parent_id in by_parent:
                continue
            by_parent[parent_id] = _empty_family(user_doc)
```

  Match the field names the adapter already uses for a student-derived row — read the surrounding code and mirror it rather than inventing `_empty_family`'s shape. If the tenant's parent role is stored as `academy_memberships` rather than a `roles` array on the user, use that collection instead; the grep in Step 3 tells you which.

- [ ] **Step 5: Render the empty state.** In `frontend/app/(admin)/admin/families/page.tsx`, where the row's student names are rendered, show `No students on file` in muted text when the list is empty, so the row does not look broken.

- [ ] **Step 6: Run the tests.**

Run: `cd backend && pytest v2/tests -k "billing_setup" -q && cd ../frontend && pnpm typecheck`
Expected: the new test PASSES, no existing `billing_setup` test regresses, typecheck clean.

- [ ] **Step 7: Commit.**

```bash
git add backend/v2/composition/families.py backend/v2/contexts/billing/application/use_cases/billing_setup_registration.py "frontend/app/(admin)/admin/families/page.tsx"
git commit -m "feat(admin): list parents with no students on the Families page

The Families list derived its rows from students, so a parent invited but not
yet enrolled existed only in the Users directory — which this branch retires.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11c: Frontend + backend — the "Needs attention" sort

> **Owner decision 2026-09-10.** Default order is alphabetical by name (predictable
> for lookup, which is the old Parents-directory job). A toggle switches to
> "Needs attention", which is what plan 3 later extends with profile-completeness.

**Files:**
- Modify: `backend/v2/contexts/billing/application/use_cases/billing_setup_registration.py` (`BillingSetupQuery` gains `sort`; `ListBillingSetup.execute` orders rows)
- Modify: `backend/v2/interfaces/admin/families_routes.py` (`sort` query param)
- Modify: `frontend/lib/api/admin.ts` (`BillingSetupListParams.sort`)
- Modify: `frontend/app/(admin)/admin/families/page.tsx` (the toggle)
- Test: the `ListBillingSetup` test module

**Interfaces:**
- Consumes: `BillingSetupRow` with `login_state` (Task 3), childless rows (Task 11b).
- Produces: `BillingSetupQuery.sort: Literal["name", "needs_attention"] = "name"`, honoured by `ListBillingSetup.execute`. Plan 3 (`2026-09-10-birthdays-and-profile-nudges.md`, Task 11) adds a profile-incomplete term to the same comparator — it must not introduce a second sort.

- [ ] **Step 1: Write the failing test.**

```python
@pytest.mark.asyncio
async def test_needs_attention_sort_puts_money_and_access_problems_first():
    use_case = _build(  # reuse the module's builder
        parents=[
            _parent("usr-fine", display_name="Anita Rao"),
            _parent("usr-owing", display_name="Zara Ahmed"),
            _parent("usr-uninvited", display_name="Bob Stone"),
        ],
        outstanding={"usr-owing": 12_000},
        never_invited={"usr-uninvited"},
    )
    result = await use_case.execute(BillingSetupQuery(sort="needs_attention"))
    assert [r.parent_id for r in result.rows] == ["usr-owing", "usr-uninvited", "usr-fine"]


@pytest.mark.asyncio
async def test_default_sort_is_alphabetical():
    use_case = _build(
        parents=[
            _parent("usr-z", display_name="Zara Ahmed"),
            _parent("usr-a", display_name="Anita Rao"),
        ],
    )
    result = await use_case.execute(BillingSetupQuery())
    assert [r.parent_id for r in result.rows] == ["usr-a", "usr-z"]
```

  Use whatever keyword arguments the module's existing builder actually takes — read it first; `outstanding` / `never_invited` above are illustrative names for "this parent owes money" and "this parent was never invited".

- [ ] **Step 2: Run it and confirm it fails.**

Run: `cd backend && pytest v2/tests -k "billing_setup and sort" -v`
Expected: FAIL — `BillingSetupQuery` has no `sort` field (`TypeError: unexpected keyword argument 'sort'`).

- [ ] **Step 3: Implement.** Add to `BillingSetupQuery`:

```python
    sort: Literal["name", "needs_attention"] = "name"
```

  And at the end of `ListBillingSetup.execute`, before returning, order the rows:

```python
        def _needs_attention_key(row: BillingSetupRow) -> tuple:
            # Lower sorts first. Money first, then people who cannot pay at all,
            # then failing autopay. Plan 3 adds a profile-incomplete term here.
            return (
                0 if row.outstanding_cents > 0 else 1,
                -row.outstanding_cents,
                0 if row.registration_state == "no_account" else 1,
                0 if row.autopay_failing else 1,
                (row.parent_name or "").lower(),
            )

        if query.sort == "needs_attention":
            rows.sort(key=_needs_attention_key)
        else:
            rows.sort(key=lambda row: (row.parent_name or "").lower())
```

  Use the real field names on `BillingSetupRow` — read it; `autopay_failing` and `outstanding_cents` above must be replaced with whatever it actually calls them, and if there is no autopay-failure boolean, drop that term rather than inventing a field.

- [ ] **Step 4: Run the tests.**

Run: `cd backend && pytest v2/tests -k "billing_setup" -q`
Expected: PASS.

- [ ] **Step 5: Thread it through the route and the client.** Add `sort: Literal["name", "needs_attention"] = Query("name")` to the families list route and pass it into `BillingSetupQuery`. Add `sort?: "name" | "needs_attention";` to `BillingSetupListParams` in `frontend/lib/api/admin.ts`.

- [ ] **Step 6: Add the toggle.** In `frontend/app/(admin)/admin/families/page.tsx`, beside the existing `FILTERS` row, render two pills — "A–Z" (default) and "Needs attention" — holding the value in the same state/query-param pattern the existing filter uses, and pass it into the list query. Include it in the React Query key so switching refetches.

- [ ] **Step 7: Verify.**

Run: `cd frontend && pnpm typecheck && pnpm lint`
Expected: PASS.

- [ ] **Step 8: Commit.**

```bash
git add backend/v2/contexts/billing/application/use_cases/billing_setup_registration.py backend/v2/interfaces/admin/families_routes.py frontend/lib/api/admin.ts "frontend/app/(admin)/admin/families/page.tsx" backend/v2/tests
git commit -m "feat(admin): Needs attention sort on the Families list

Default stays alphabetical for lookup; the toggle surfaces outstanding balance,
never-invited and failing-autopay families first.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: QA inventory manifest + route-matrix + final verification pass

**Files:**
- Modify: `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` — `/admin/families` (line 252), `/admin/parents` (line 622), `/admin/users` (line 1778); the redirect template to copy is `/admin/billing-setup` (lines 228–250). All verified present this session.
- Test: `backend/v2/tests/unit/test_audit_inventory_manifest.py` and `backend/v2/tests/unit/test_inventory_manifest_summary.py` (both located this session)

**Interfaces:** none new — verification task.

Steps:

- [ ] 12.1 Read `backend/v2/tests/unit/test_audit_inventory_manifest.py`. Verified this session: it asserts `len(routes) >= 49`, that a `required_routes` set (which includes `/admin/users`) is present, and that the manifest's route set matches the `frontend/app` route tree. **No page is added or deleted by this plan**, so neither of those checks changes — but that is not a licence to skip the manifest edit. Also read `test_inventory_manifest_summary.py` for any counts it derives.

- [ ] 12.2 Update the `/admin/parents` entry (line 622). It currently claims `workflows: ["List parents", "Inspect family records"]`, `controls.buttons: ["Search", "Open"]`, `states: ["loading", "empty", "error", "large pagination"]`, `risk_edges: ["Scale parent pagination", "Missing invited_by provenance"]` and five matching `acceptance` strings — **every one of which is false once the page is a bare `redirect()`**. Rewrite it to the shape `/admin/billing-setup` already uses for the same situation (lines 228–250):

```json
    {
      "route": "/admin/parents",
      "role": "admin",
      "source": "frontend/app/(admin)/admin/parents/page.tsx",
      "workflows": ["Redirect to /admin/families"],
      "controls": { "buttons": [], "inputs": [], "modals": [] },
      "states": ["redirect"],
      "risk_edges": ["Old bookmark lands on the redirect"],
      "acceptance": [
        "Workflow evidence: \"Redirect to /admin/families\" completes for the admin route /admin/parents with real-user evidence and no framework or runtime errors.",
        "Risk evidence: \"Old bookmark lands on the redirect\" has an explicit pass, fail, or blocked result with reproduction context in the real-user checklist."
      ]
    },
```

- [ ] 12.2b Update the `/admin/families` entry (line 252): add the new workflows ("Filter by login state", "Search by phone or child name", "Add parent", "Send invite from the list") and the new `controls` (buttons `Add parent`, `Send invite`; modals `Add parent`), each with its matching `acceptance` string in the file's exact wording template. Update `/admin/users` (line 1778) to drop any "Parents" tab from its `controls`/`workflows` if it names one (grep the entry before editing).

- [ ] 12.3 Run both manifest tests: `cd backend && .venv/bin/pytest v2/tests/unit/test_audit_inventory_manifest.py v2/tests/unit/test_inventory_manifest_summary.py -q` — expect PASS. Project memory's "2 hardcoded route counts" rule applies to *adding* an `app/` route; this plan adds none (`CreateParentDialog.tsx` and `EditContactDialog.tsx` are components, not `page.tsx` files, and `test_inventory_manifest_matches_frontend_app_route_tree` only globs `page.tsx`/`route.ts`). If a count assertion fails anyway, read the failure message rather than assuming.

- [ ] 12.4 Run the full backend test suite for touched modules: `cd backend && .venv/bin/pytest v2/tests/interface/test_admin_families_routes.py v2/tests/interface/test_admin_billing_setup.py v2/tests/unit/test_billing_setup_registration.py v2/tests/unit/test_family_billing.py v2/tests/structural/test_composition_is_wiring.py -q`, then `.venv/bin/lint-imports --config pyproject.toml`.

- [ ] 12.5 Run the full frontend typecheck/lint: `cd frontend && pnpm typecheck && pnpm lint`.

- [ ] 12.6 Run the three named e2e specs together: `cd frontend && pnpm exec playwright test admin-shell.spec.ts saas-launch-route-matrix.spec.ts admin-family-billing.spec.ts --project=chromium`.

- [ ] 12.7 Commit the manifest edit. Per the repo rule this must land in the **same commit** as the `/admin/parents` redirect, so do steps 12.1–12.2b **before** Task 9.7 and stage the manifest with it. `git commit --amend` is blocked by a repo hook, so do not plan to fix this after the fact. If you have already committed Task 9, land the manifest as its own follow-up commit and say so in the PR body:
  `git add docs/qa/2026-06-28-production-scale-local-inventory-manifest.json`
  Message:
  ```
  chore(qa): update inventory manifest for families-directory redirect target

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

---

### Task 13: Release note

**Files:**
- Create: `docs/release-notes/2026-09-10-families-directory-consolidation.md`

Steps:

- [ ] 13.1 Create the release note with exactly the three required sections — verified against `scripts/dev/release_notes_check.py` line 26: `REQUIRED_SECTIONS = ["## What changed", "## Deploy notes", "## Risk / rollback"]`, and `validate_note` (lines 89–105) also rejects a section whose body is empty, starts with `<`, or contains a placeholder marker. Read `PLACEHOLDER_MARKERS` in that script before writing, and keep the words it lists (e.g. TBD / TODO / auto-generated stub) out of every section body. The `PR: #<number>` line goes **above** the first `## ` heading (see `generate_note`, lines 145–165) so it is not part of any section body; fill in the real number once the PR is open — the "Release Notes Gate" required check will not pass with a placeholder:

```markdown
# Families directory consolidation

PR: #<number>

## What changed

`/admin/families` is now the single admin surface for parent identity,
login, and billing. The Families list gained Contact (email/phone) and
Login (never invited / invited / active) columns plus a login-state
filter and phone/child-name search; the per-family header (`FamilyHeader`)
gained a login badge, mailto/tel links, "Send password reset", and "Edit
contact details". `/admin/parents` and `/admin/users?role=parent` now
redirect to `/admin/families`; the Users directory dropped its Parents
tab and "Add parent" moved to the Families list; the user-detail page for
a parent now points to the family page instead of showing login-invite
controls.

## Deploy notes

No data migration — a family is still one parent `User` plus the
`Student` rows pointing at it. No feature flag; this ships as a normal
deploy. The Billing Setup list's composition wiring moved from
`composition/admin.py` to `composition/families.py` (late-bound in
`main.py`) — a boot smoke check (`python -c "import backend.v2.main"`)
should be part of the deploy's pre-flight if not already automated.

## Risk / rollback

Additive on the Families side (Tasks 1–8) and can ship independently of
the redirect/pill-removal side (Tasks 9–11) per the spec's two-PR
rollout. If the redirect PR causes issues, revert `frontend/app/(admin)/admin/parents/page.tsx`
and `frontend/app/(admin)/admin/users/page.tsx` to restore the old
`/admin/users?role=parent` target and re-add the Parents pill in
`AdminUsersDirectory.tsx`; the backend list/detail endpoints are backward
compatible (new fields are additive, no field removed) so no backend
rollback is required for a frontend-only revert.
```

- [ ] 13.2 Commit:
  `git add docs/release-notes/2026-09-10-families-directory-consolidation.md`
  Message:
  ```
  docs(release-notes): add release note for families directory consolidation

  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

---

## Self-review

| Spec section | Covered by |
|---|---|
| §2 Owner decisions — parents removed from Users, `/admin/parents` + `?role=parent` redirect, no new data model, identity folded into `FamilyHeader`, Add-parent moves | Tasks 9, 10, 11 (redirects/pill/add-parent); Task 8 (header fold) |
| §3 Families list — columns, search (name/email/phone/child), filters, login-invite facts from `users` doc | Tasks 1, 2, 3 (backend roster+login_state+search), Task 7 (frontend columns/filter) |
| §4 Family detail page — header identity strip, send/resend invite, send password reset, edit contact (name/phone only, email stays admin-only path), roles not editable here | Tasks 4, 5 (backend actions/routes), Task 8 (frontend header/dialog). "Send password reset" carries an OPEN QUESTION (Task 4) — no distinct use case exists. |
| §4 "Each student row in StudentsPanel links to the student page" | **Already satisfied** — `frontend/app/(admin)/admin/families/[parentId]/StudentsPanel.tsx` has `studentHref` (line 23) used at lines 59, 81 and 119. No task needed; verified this session. |
| §9 "tenant scoping (parent outside the tenant is absent, never 403)" | Task 3.5 (added by review — the original plan had no test for it) |
| §5 Users directory — drop Parents pill, `fixedRole="parent"` removed, parent user-detail shows pointer + hides invite panel | Tasks 10, 11 |
| §6 What this unblocks — Spec 4's `ChangeParentPanel` move, Spec 1's enrollment rows on the family page | Explicitly out of scope for this plan (see below) |
| §7 Rollout — list+header first (additive), then redirects+pill+Add-parent | Reflected in task ordering: Tasks 1–8 are additive, Tasks 9–11 are the breaking/redirect half |
| §8 Out of scope — second guardian, merging duplicate accounts, coach/admin directory changes | Not built; no task touches these |
| §9 Testing — backend search/login-state/tenant-scoping tests, e2e redirects/invite/pointer/manifest | Tasks 1, 3 (backend tests), Task 12 (manifest + e2e), Tasks 8/9/11 (per-feature e2e) |

**Deferred, with reason:**

- §7 step 2's "one-off script" comparing Users-directory parents against Families-list parents for parity — this is an ops verification step the spec describes as run once during rollout, not a shippable artifact; not included as a plan task. If needed, run it ad hoc against the Task 1–8 deployment before merging the Task 9–11 PR, comparing `GET /admin/users?role=parent` (pre-redirect, on a branch that still has it) against `GET /admin/billing/setup`.
- §6 "What this unblocks" (Spec 4's `ChangeParentPanel` removal reusing `POST /students/{id}/change-parent`; Spec 1's enrollment rows on the family page) — these are explicitly follow-on specs per the doc itself ("Spec 4 removes...", "Spec 1 §2 noted...a later slice can list..."), not part of this spec's scope. **Consequence for plan 4:** `2026-09-10-student-page-single-view.md` Task 8 gates `ChangeParentPanel`'s removal on a "Move child to another family" action on the family page; because this plan does not ship it, that task is expected to skip and `ChangeParentPanel` stays inside the student page's Compliance section. That is the intended sequencing, not a gap in either plan.
- The "existing password-reset use case" is now identified concretely:
  `SendLoginInvite` (`backend/v2/contexts/identity/application/use_cases/send_login_invite.py`
  line 116), already constructed at `composition/admin.py` line 1750 and exposed as
  `AdminUseCases.send_login_invite` (line 4204). It is the ONLY one — see the OPEN
  QUESTION under Task 4.

## Open questions

- **OPEN QUESTION (owner):** spec §4 asks for "Send / resend invite" *and* "Send password
  reset" as two header actions, but the codebase has only `SendLoginInvite`, and what it
  sends is a Firebase password-reset link. Are these one action with two labels (drop the
  new `POST /families/{parent_id}/password-reset` route and just relabel the invite button
  when `login.state === "active"`), or does a genuinely distinct reset flow need building?
  Task 4 implements the former; confirm before shipping two buttons.

## Review corrections applied (2026-09-10)

Every file path, line number, symbol and command in this plan was re-checked against the
worktree at `ada7f6032`. The substantive corrections were:

1. `backend/v2/tests/interface/test_billing_setup_routes.py` **does not exist**; the real
   file is `test_admin_billing_setup.py`. Fixed in all 11 references.
2. `backend/v2/tests/unit/test_billing_setup_registration.py` **already exists** (327 lines,
   12 tests, `FakeRoster`/`_make_use_case`). Task 1 now appends to it instead of dumping a
   parallel file with colliding helper names.
3. `parent_phone` was unobtainable: `ListAdminStudents` returns `AdminStudentSummary`, which
   has no phone. Task 1 now sources phone (and the login-invite timestamp) from a new
   identity-directory port.
4. `login_state` was being derived from `parent_billing_customers.billing_setup_last_invited_at`
   — the *add-a-card* invite, not the login invite. Corrected to
   `academy_memberships.login_invite_sent_at`, per spec §3.
5. `queryKeys.admin.billingSetup` does not include `login_state`, so the new filter would
   have been a silent cache no-op. Task 6.2b added.
6. `family_actions`' new kwarg + the new leading `edit_contact` breaks four existing
   assertions in `test_family_billing.py`. Task 4.4b added.
7. `FamilyAction` in `frontend/lib/api/admin-families.ts` was never extended, so Task 8's
   `actions.includes("send_password_reset")` would not compile. Task 6.3b added.
8. `AdminUseCases.list_billing_setup` has ~119 non-default fields after it; the draft's
   `= None` fallback would have raised `non-default argument follows default argument`.
   Corrected to widening the annotation only.
9. `users_r` / `parent_customers_repo` / `student_billing_enrollment_repo` /
   `billing_ledger_repo` are locals of `compose_admin` and are not reachable from `main.py`.
   `compose_admin_families` now builds its own repos and takes only the two use cases.
10. The `_reuse_billing_setup_*_adapter(...)` placeholders were removed from the
    `composition/families.py` code block.
11. Spec §9's tenant-scoping test had no task (Task 3.5), and the QA manifest update was
    hedged as "verify no update needed" when `/admin/parents`' workflows/acceptance become
    false on redirect (Task 12.2).
