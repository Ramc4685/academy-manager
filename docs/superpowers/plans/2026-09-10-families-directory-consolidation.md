# Families Directory Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/admin/families` the single place an admin finds a parent — identity, login state and billing in one list and one detail header — and remove parents from `/admin/users`.

**Architecture:** The families list gains `q` (name/email/phone/child name), `login_state`, a `has_balance` filter, a `needs_attention` sort and cursor pagination by extending the existing `ListBillingSetup` read-model use case (`backend/v2/contexts/billing/application/use_cases/billing_setup_registration.py`) with an optional login-invite port and a child-name/phone search, then wiring a **second**, families-scoped instance of it in `backend/v2/composition/families.py` (new `GET /families` route) so `composition/admin.py` — verified at 4318 lines against the 4500 budget in `backend/v2/tests/structural/test_composition_is_wiring.py` — needs zero edits. The family detail header (`FamilyHeader.tsx`) becomes the identity strip by exposing login facts as a new `header.login` field, and by reusing two existing, unmodified endpoints for its new actions: `POST /admin/users/{id}/login-invite` (the "set your password" / login invite — see `contexts/identity/application/use_cases/send_login_invite.py`) and `PATCH /admin/users/{id}` (edit name/phone) — both already used by the Users directory's user-detail page.

**Two different "invites" — do not conflate them:**

| Fact | Stored on | Meaning | Surfaced as |
|---|---|---|---|
| `parent_billing_customers.billing_setup_last_invited_at` → `CustomerFacts.last_invited_at` → `ParentBillingCustomerSnapshot.last_invited_at` | billing | "add a card" / Billing Setup reminder (`inviteBillingSetupParent`) | `header.registration.last_invited_at`, the existing **Send/Resend invite** button, the list's **Billing** chip |
| `academy_memberships.login_invite_sent_at` (written by `MongoUserRepository.record_login_invite`) | identity | "set your password" Firebase login invite (`sendLoginInvite`) | the new `header.login.invited_at`, the list's **Login** chip |

Every new login-state fact in this plan comes from the *second* row. `CustomerFacts.last_invited_at` is **never** the login invite (verified: `family_billing_read_model.py:816` reads `billing_setup_last_invited_at`).

**Tech Stack:** FastAPI/Pydantic (backend/v2), Next.js 16.3.4 + TanStack Query v5 (frontend), pytest (`asyncio_mode = "auto"`, `testpaths = ["v2/tests"]`), vitest (`globals: false` — import `describe`/`it`/`expect`), Playwright.

**Command conventions (verified against `backend/pyproject.toml` and AGENTS.md):** there is **no `backend/.venv`** in this worktree and pytest's `testpaths` is `v2/tests`. Every backend test command in this plan is therefore `cd backend && pytest v2/tests/<path> -q`, never `.venv/bin/pytest tests/<path>`.

## Global Constraints

- 1 parent `User` = 1 family; no new `Family` model (spec §2).
- `/admin/users` keeps Coaches and Admins only; `/admin/parents` and `/admin/users?role=parent` redirect to `/admin/families` (spec §2).
- Roles are not editable from the family page; a parent who is also a coach is still managed from `/admin/users` (spec §4).
- Email edit stays the existing admin-only path (`UserEditForm` on `/admin/users/[userId]`) with its warning — the family header edits name/phone only (spec §4).
- `composition/admin.py` is at 4318/4500 lines: this plan makes **zero** edits to it. All new wiring lives in `composition/families.py` (spec §3). Only `admin.py` is line-budgeted (`test_composition_is_wiring.py`); `families.py` is not.
- Registration state (`no_account`/`account_no_card`/`card_on_file`, i.e. card-on-file) is a separate concept from login state (`never_invited`/`invited`/`active`, i.e. Firebase account) — the list's Billing chip and Login chip are driven by different facts, per the "two different invites" table above (spec §3).
- Second guardian, merging duplicate parent accounts, and coach/admin directory changes are out of scope (spec §8).
- **Both** `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` entries this plan touches — `/admin/parents` (redirect target changed) **and** `/admin/families` (Task 9 rewrites the page and adds buttons/inputs) — are updated in the same commit as the code (spec §9). `backend/v2/tests/unit/test_inventory_static_gaps.py::test_current_inventory_manifest_has_no_static_source_gaps` scans the real `page.tsx` sources against the manifest's `controls`, so a stale `/admin/families` entry fails the backend suite.
- **Wrong-persona access returns 404, never 403** (AGENTS.md §Guardrails, `docs/security-matrix.md`). The new `GET /admin/families` list route is guarded by `require_persona("admin")` like its siblings and must have a coach-gets-404 test.
- No migration and no new collection in this plan. (For reference: prod runs migrations by hand — `V2_RUN_MIGRATIONS_ON_BOOT` is false, issue #629 — so any future migration here would need a manual prod run. Nothing to run for this PR.)

## File structure

| File | Responsibility |
|---|---|
| `backend/v2/contexts/billing/application/ports.py` | Add `parent_phone` to `ParentRosterEntry`; add `LoginInviteDirectory` protocol for bulk login-invite facts. |
| `backend/v2/contexts/billing/application/use_cases/billing_setup_registration.py` | Add `login_invite_sent_at` / `has_login_account` / `parent_phone` to `BillingSetupRow`; add `login_state` + `has_balance` filters and a `sort` param; extend `q` to match child name + phone; optional `login_invites` port (backward-compatible). |
| `backend/v2/contexts/identity/infrastructure/mongo_user_repo.py` | New bulk method `list_login_facts` (has_login_account, login_invite_sent_at, phone per parent) for the families list and the family header. |
| `backend/v2/composition/families.py` | New `_FamiliesLoginFacts` cache + `_FamiliesRosterAdapter`, `_FamiliesLoginAccountAdapter`, `_FamiliesLoginInviteAdapter`, `_FamiliesCustomerAdapter`, `_FamiliesAutopayAdapter`, `_FamiliesBalanceAdapter` and a families-scoped `ListBillingSetup` instance; `AdminFamilies.lister` field; pass `users` into the read model so it can read login-invite facts. |
| `backend/v2/interfaces/admin/families_routes.py` | New `GET /families` route. |
| `backend/v2/interfaces/admin/families_views.py` | New `FamiliesListRowView`/`FamiliesListResponse` DTOs; new `FamilyLogin` view + `login` field on `FamilyHeader`. |
| `backend/v2/contexts/billing/application/family_billing.py` | Add `login_invite_sent_at` to `CustomerFacts`; `build_family_billing_view` emits `header.login = {has_account, invited_at}`. |
| `backend/v2/contexts/billing/infrastructure/family_billing_read_model.py` | `_customer()` fills the new `CustomerFacts.login_invite_sent_at` from `MongoUserRepository.list_login_facts` (**not** from `billing_setup_last_invited_at`). |
| `frontend/lib/api/admin-families.ts` | `FamilyLogin` type, `login` field on `FamilyHeader`; new `fetchFamiliesList`, `FamiliesListRow`, `FamiliesListParams`. |
| `frontend/app/(admin)/admin/families/[parentId]/family-view.ts` | New `loginBadge()` helper. |
| `frontend/app/(admin)/admin/families/[parentId]/FamilyHeader.tsx` | mailto/tel links, login badge, "Send password reset", "Edit contact details" dialog. |
| `frontend/app/(admin)/admin/families/[parentId]/family-contact-dialog.tsx` | New: the edit-contact-details dialog. |
| `frontend/app/(admin)/admin/families/page.tsx` | Switch to `fetchFamiliesList`; Login column, login-state filter, "has balance" filter, "Needs attention" sort, Add-parent dialog. |
| `frontend/components/admin/CreateUserDialog.tsx` | New: `CreateUserDialog` extracted from `AdminUsersDirectory.tsx` so Families and Users share it. |
| `frontend/components/admin/AdminUsersDirectory.tsx` | Drop Parents pill, drop `fixedRole="parent"`, drop the "Parent" create-role option; use shared `CreateUserDialog`. |
| `frontend/app/(admin)/admin/parents/page.tsx` | Redirect target `/admin/users?role=parent` → `/admin/families`. |
| `frontend/app/(admin)/admin/users/page.tsx` | Redirect `?role=parent` to `/admin/families`. |
| `frontend/app/(admin)/admin/users/[userId]/page.tsx` | Parent pointer banner + hide `LoginInvitePanel` for parent-only users. |
| `frontend/components/admin/screen-meta.ts` | `/admin/users` subtitle drops "parents". |
| `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` | `/admin/parents` entry becomes redirect-shaped; `/admin/families` entry gains the new controls/workflows. |
| `frontend/e2e/specs/admin-shell.spec.ts` | Update the `/admin/parents` redirect assertion to land on `/admin/families`. |
| `frontend/e2e/specs/admin-family-billing.spec.ts` | **Both** header fixtures gain `header.login`; new assertions for login badge, login invite, edit contact. |
| `frontend/e2e/specs/admin-families-list.spec.ts` | New: list search/filter/sort + Add-parent dialog. |
| `scripts/dev/families_parity_check.py` | New (spec §7 step 2): one-off script comparing `/admin/users?role=parent` against `GET /admin/families` for the same tenant. |
| `docs/release-notes/2026-09-10-families-directory-consolidation.md` | Release note (3 exact `##` sections + real `PR: #<n>`). |

## Task 1: Backend — extend the Billing Setup read model with login facts and search

**Files:**
- Modify: `backend/v2/contexts/billing/application/ports.py` (`ParentRosterEntry` at lines 71-76; add `LoginInviteDirectory` protocol after `LoginAccountDirectory`, which is lines 90-95)
- Modify: `backend/v2/contexts/billing/application/use_cases/billing_setup_registration.py` (`BillingSetupRow` lines 46-62; `RegistrationState`/new `LoginState` at line 34; `ListBillingSetup.__init__` lines 93-106; `ListBillingSetup.execute` lines 108-231)
- Test: `backend/v2/tests/unit/test_billing_setup_registration.py`

**Interfaces:**
- Consumes: nothing new (still `ParentStudentRoster`, `LoginAccountDirectory`, `BillingCustomerDirectory`, `EnrollmentAutopayDirectory`, `OutstandingBalanceDirectory`; adds an **optional** `login_invites: LoginInviteDirectory | None = None` keyword)
- Produces: `BillingSetupRow.login_invite_sent_at: datetime | None`, `BillingSetupRow.has_login_account: bool`, `BillingSetupRow.parent_phone: str | None`; `ListBillingSetup.execute(..., login_state: LoginState | Literal["all"] = "all", has_balance: bool = False, sort: Literal["name","needs_attention"] = "name")`

**Why the filters and the sort live here, not in the React page:** the list is cursor-paginated. A "has balance" filter or a "needs attention" reorder applied to `data.pages.flatMap(...)` only sees the pages already fetched, so what the admin sees depends on how many times they clicked "Load more" — and the summary tiles would disagree with the rows. `ListBillingSetup.execute` already materialises every row before slicing (lines 203-229), so both belong next to the existing `status_filter`/`q` filters and before the `rows.sort(...)`/summary/cursor block.

Steps:

- [ ] Write the failing test in `backend/v2/tests/unit/test_billing_setup_registration.py`. First add `from datetime import UTC, datetime` to the module header (the file has no datetime import today), then append at end of file:
  ```python
  class FakeLoginInvites:
      def __init__(self, sent_at: dict[str, object]) -> None:
          self._sent_at = sent_at

      async def login_invite_sent_at_by_parent(
          self, parent_ids: list[str], *, academy_id: str
      ) -> dict[str, object | None]:
          return {pid: self._sent_at.get(pid) for pid in parent_ids}


  @pytest.mark.asyncio
  async def test_login_state_filter_and_child_name_search() -> None:
      parents = [
          ParentRosterEntry(parent_id="p1", parent_name="Ana Cruz", parent_email="ana@x.com"),
          ParentRosterEntry(parent_id="p2", parent_name="Bo Lee", parent_email="bo@x.com"),
          ParentRosterEntry(parent_id="p3", parent_name="Cy Park", parent_email="cy@x.com"),
      ]
      students = {
          "p1": [BillingSetupStudent(student_id="s1", full_name="Priya Cruz")],
          "p2": [BillingSetupStudent(student_id="s2", full_name="Max Lee")],
          "p3": [],
      }
      sent_at = {"p2": datetime(2026, 9, 1, tzinfo=UTC)}
      use_case = ListBillingSetup(
          roster=FakeRoster(parents, students),
          login_accounts=FakeLoginAccounts({"p3"}),  # p3 = active login account
          customers=FakeCustomers([]),   # NOTE: this fake takes a *list*, not a dict
          autopay=FakeAutopay([]),       # NOTE: this fake takes a *list*, not a dict
          balances=FakeBalances({"p2": 5000}),  # this one really is dict[str, int]
          login_invites=FakeLoginInvites(sent_at),
      )

      never_invited = await use_case.execute(academy_id=ACADEMY_ID, login_state="never_invited")
      assert [r.parent_id for r in never_invited.rows] == ["p1"]

      invited = await use_case.execute(academy_id=ACADEMY_ID, login_state="invited")
      assert [r.parent_id for r in invited.rows] == ["p2"]
      assert invited.rows[0].login_invite_sent_at == sent_at["p2"]

      active = await use_case.execute(academy_id=ACADEMY_ID, login_state="active")
      assert [r.parent_id for r in active.rows] == ["p3"]
      assert active.rows[0].has_login_account is True

      by_child = await use_case.execute(academy_id=ACADEMY_ID, q="priya")
      assert [r.parent_id for r in by_child.rows] == ["p1"]

      only_owing = await use_case.execute(academy_id=ACADEMY_ID, has_balance=True)
      assert [r.parent_id for r in only_owing.rows] == ["p2"]

      # needs_attention: balance first, then never-invited, then the rest.
      ranked = await use_case.execute(academy_id=ACADEMY_ID, sort="needs_attention")
      assert [r.parent_id for r in ranked.rows] == ["p2", "p1", "p3"]
  ```
  `FakeRoster`/`FakeLoginAccounts`/`FakeCustomers`/`FakeAutopay`/`FakeBalances` and `ACADEMY_ID` are already defined at the top of this file (lines 18-102) — reuse them unchanged; only `FakeLoginInvites` is new. Do **not** route this through the file's `_make_use_case` helper (line 105): it does not accept `login_invites`.

- [ ] Run it and confirm it fails on the missing `login_invites` kwarg / `login_state` filter:
  ```
  cd backend && pytest v2/tests/unit/test_billing_setup_registration.py -q -k login_state_filter
  ```
  Expected: `TypeError: ListBillingSetup.__init__() got an unexpected keyword argument 'login_invites'`.

- [ ] In `ports.py`, add `parent_phone` to `ParentRosterEntry` (after `parent_email` at line 76):
  ```python
  class ParentRosterEntry(BaseModel):
      model_config = {"frozen": True}

      parent_id: str
      parent_name: str
      parent_email: str | None = None
      parent_phone: str | None = None
  ```
  and add a new protocol directly after `LoginAccountDirectory` (which ends at line 95, immediately before `class ParentStudentRoster` at line 98):
  ```python
  class LoginInviteDirectory(Protocol):
      """Bulk fetch of the *login-invite* timestamp tracked on the user's
      academy membership (``login_invite_sent_at``) — distinct from
      ``ParentBillingCustomerSnapshot.last_invited_at``, which tracks the
      Billing Setup card/add-card-reminder invite. See spec
      ``2026-09-10-families-directory-consolidation-design.md`` §3."""

      async def login_invite_sent_at_by_parent(
          self, parent_ids: list[str], *, academy_id: str
      ) -> dict[str, datetime | None]: ...
  ```

- [ ] In `billing_setup_registration.py`, add `LoginState` next to `RegistrationState` (line 34):
  ```python
  RegistrationState = Literal["no_account", "account_no_card", "card_on_file"]
  LoginState = Literal["never_invited", "invited", "active"]
  ```
  add fields to `BillingSetupRow` (after `last_invited_at` at line 62):
  ```python
      last_invited_at: datetime | None = None
      login_invite_sent_at: datetime | None = None
      has_login_account: bool = False
      parent_phone: str | None = None
  ```
  add the import and constructor param:
  ```python
  from backend.v2.contexts.billing.application.ports import (
      BillingCustomerDirectory,
      BillingSetupStudent,
      EnrollmentAutopayDirectory,
      EnrollmentAutopaySnapshot,
      LoginAccountDirectory,
      LoginInviteDirectory,
      OutstandingBalanceDirectory,
      ParentStudentRoster,
  )
  ```
  ```python
      def __init__(
          self,
          *,
          roster: ParentStudentRoster,
          login_accounts: LoginAccountDirectory,
          customers: BillingCustomerDirectory,
          autopay: EnrollmentAutopayDirectory,
          balances: OutstandingBalanceDirectory,
          login_invites: LoginInviteDirectory | None = None,
      ) -> None:
          self._roster = roster
          self._login_accounts = login_accounts
          self._customers = customers
          self._autopay = autopay
          self._balances = balances
          self._login_invites = login_invites
  ```
  add the new params to `execute()`'s signature (after `parent_id: str | None = None,`, line 116):
  ```python
          login_state: LoginState | Literal["all"] = "all",
          has_balance: bool = False,
          sort: Literal["name", "needs_attention"] = "name",
  ```
  after the existing `login_account_ids = ...` fetch in both branches (single-parent branch and bulk branch), fetch invite timestamps:
  ```python
          if self._login_invites is not None:
              sent_at_by_parent = await self._login_invites.login_invite_sent_at_by_parent(
                  parent_ids, academy_id=academy_id
              )
          else:
              sent_at_by_parent = {}
  ```
  (add this once, after the `if parent_id is not None: ... else: ...` block, using the `parent_ids` list already computed at line 152) — then in the row-building loop, set:
  ```python
              rows.append(
                  BillingSetupRow(
                      parent_id=parent.parent_id,
                      parent_name=parent.parent_name,
                      parent_email=parent.parent_email,
                      parent_phone=parent.parent_phone,
                      students=tuple(students_by_parent.get(parent.parent_id, [])),
                      registration_state=state,
                      card_label=customer.card_label if customer else None,
                      card_last4=customer.card_last4 if customer else None,
                      autopay_active_count=active_count,
                      autopay_eligible_count=eligible_count,
                      outstanding_balance_cents=balance.outstanding_cents if balance else 0,
                      charge_invoice_id=balance.charge_invoice_id if balance else None,
                      charge_amount_cents=balance.charge_amount_cents if balance else 0,
                      charge_autopay_eligible=charge_autopay_eligible,
                      last_invited_at=customer.last_invited_at if customer else None,
                      login_invite_sent_at=sent_at_by_parent.get(parent.parent_id),
                      has_login_account=parent.parent_id in login_account_ids,
                  )
              )
  ```
  add two module-level helpers next to `_registration_state` (line 82) so no function is defined inside an `if` block:
  ```python
  def _login_state(row: BillingSetupRow) -> LoginState:
      if row.has_login_account:
          return "active"
      if row.login_invite_sent_at is not None:
          return "invited"
      return "never_invited"


  def _needs_attention_rank(row: BillingSetupRow) -> int:
      """Spec §3: outstanding-balance rows first, then never-invited, then the rest."""
      if row.outstanding_balance_cents > 0:
          return 0
      if _login_state(row) == "never_invited":
          return 1
      return 2
  ```
  add the `login_state` and `has_balance` filters next to the existing `status_filter` filter (line 203):
  ```python
          if login_state != "all":
              rows = [r for r in rows if _login_state(r) == login_state]
          if has_balance:
              rows = [r for r in rows if r.outstanding_balance_cents > 0]
  ```
  extend the `q` search to include child names and phone:
  ```python
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
  and replace the existing single sort line (line 213, `rows.sort(key=lambda r: r.parent_name.lower())`) with a stable two-key sort so `needs_attention` still orders by name inside each band, and paging stays deterministic:
  ```python
          rows.sort(key=lambda r: r.parent_name.lower())
          if sort == "needs_attention":
              rows.sort(key=_needs_attention_rank)
  ```
  Leave the summary/cursor block below untouched: the summary is computed after filtering (existing behaviour for `status_filter`), and the cursor walk keys off `parent_id` in the *sorted* order, so both stay correct.

- [ ] Run and confirm PASS:
  ```
  cd backend && pytest v2/tests/unit/test_billing_setup_registration.py -q
  ```

- [ ] Commit:
  ```
  git add backend/v2/contexts/billing/application/ports.py backend/v2/contexts/billing/application/use_cases/billing_setup_registration.py backend/v2/tests/unit/test_billing_setup_registration.py
  git commit -m "feat(billing): add login state, phone and child-name search to Billing Setup rows

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 2: Backend — bulk login facts on `MongoUserRepository`

**Files:**
- Modify: `backend/v2/contexts/identity/infrastructure/mongo_user_repo.py` (add method immediately after `list_existing_user_ids`, lines 282-332, i.e. before `get_billing_setup_parent` at line 334)
- Test: append to the existing `backend/v2/tests/contract/test_identity_mongo_user_repo.py` (verified: this is the Mongo-backed user-repo contract test, and the `db` fixture it uses is the `mongomock-motor` fixture in `backend/v2/tests/contract/conftest.py` — that fixture is **not** visible from `backend/v2/tests/unit/`, so this test must live under `contract/`)

**Interfaces:**
- Produces: `async def list_login_facts(self, parent_ids: list[str], *, academy_id: str) -> dict[str, "LoginFacts"]` where `LoginFacts` is `{has_login_account: bool, login_invite_sent_at: datetime | None, phone: str | None}`

Steps:

- [ ] Read `backend/v2/tests/contract/test_identity_mongo_user_repo.py`'s existing tests (they take `db` positionally and use plain `@pytest.mark.asyncio`) and match that style.

- [ ] Append the failing test to that file (add `from datetime import UTC, datetime` to its header):
  ```python
  @pytest.mark.asyncio
  async def test_list_login_facts_reads_membership_and_phone(db) -> None:
      await db["users"].insert_one(
          {"_id": "u1", "user_id": "u1", "firebase_uid": "fb-1", "email": "a@x.com",
           "display_name": "Ana", "phone": "+15551234567", "role": "parent"}
      )
      await db["academy_memberships"].insert_one(
          {"academy_id": "acad-1", "user_id": "fb-1", "status": "active",
           "roles": ["parent"], "login_invite_sent_at": datetime(2026, 9, 1, tzinfo=UTC)}
      )
      repo = MongoUserRepository(db)

      facts = await repo.list_login_facts(["u1", "u-missing"], academy_id="acad-1")

      assert facts["u1"].has_login_account is True
      assert facts["u1"].phone == "+15551234567"
      assert facts["u1"].login_invite_sent_at == datetime(2026, 9, 1, tzinfo=UTC)
      assert facts["u-missing"].has_login_account is False
      assert facts["u-missing"].phone is None
  ```
  `MongoUserRepository` is already imported at the top of that file — do not re-import it inside the test.

- [ ] Run it and confirm it fails with `AttributeError: 'MongoUserRepository' object has no attribute 'list_login_facts'`:
  ```
  cd backend && pytest v2/tests/contract/test_identity_mongo_user_repo.py -q -k list_login_facts
  ```

- [ ] Add a small frozen dataclass and the method to `mongo_user_repo.py`, mirroring `list_existing_user_ids` (lines 282-332) but returning richer per-parent facts and phone from the raw user doc. **Two membership queries total, not two per parent** — `list_existing_user_ids` already does a `find_one` per user, and this method is called once per families-list request for up to 200 parents, so a per-parent `find_one` here would be a 400-round-trip page load. Fetch the memberships in one `$in` pass:
  ```python
  @dataclass(frozen=True)
  class LoginFacts:
      has_login_account: bool
      login_invite_sent_at: datetime | None
      phone: str | None
  ```
  (`mongo_user_repo.py` has no `from dataclasses import dataclass` today — add it to the module header. `ObjectId` and `datetime` are already imported.)
  ```python
      async def list_login_facts(
          self, parent_ids: list[str], *, academy_id: str
      ) -> dict[str, LoginFacts]:
          """Login facts for the Families list and the family header: whether a
          parent's Firebase login is live in this academy, the
          ``login_invite_sent_at`` timestamp from their academy membership, and
          their phone.

          ``login_invite_sent_at`` is the "set your password" invite written by
          ``record_login_invite``. It is NOT
          ``parent_billing_customers.billing_setup_last_invited_at`` (the
          add-a-card reminder), which the Billing Setup read model surfaces
          separately as ``registration.last_invited_at``.

          "Has a login account" uses exactly the predicate
          ``list_existing_user_ids`` uses — active parent membership with
          ``login_invite_pending`` unset — so the list's Login chip and the
          Billing Setup ``account_no_card`` state can never disagree.
          """
          result: dict[str, LoginFacts] = {
              pid: LoginFacts(has_login_account=False, login_invite_sent_at=None, phone=None)
              for pid in parent_ids
          }
          if not parent_ids:
              return result
          object_ids = [ObjectId(value) for value in parent_ids if ObjectId.is_valid(value)]
          aliases: list[dict[str, object]] = [
              {"user_id": {"$in": parent_ids}},
              {"auth_uid": {"$in": parent_ids}},
              {"firebase_uid": {"$in": parent_ids}},
          ]
          if object_ids:
              aliases.append({"_id": {"$in": object_ids}})
          docs = [
              doc
              async for doc in self.collection.find(
                  {"$or": aliases},
                  {"user_id": 1, "auth_uid": 1, "firebase_uid": 1, "phone": 1},
              )
          ]
          uids = [
              str(doc.get("firebase_uid") or doc.get("auth_uid"))
              for doc in docs
              if doc.get("firebase_uid") or doc.get("auth_uid")
          ]
          memberships: dict[str, dict[str, Any]] = {}
          if uids:
              async for row in self._db["academy_memberships"].find(
                  {"academy_id": academy_id, "user_id": {"$in": uids}},
                  {"user_id": 1, "status": 1, "roles": 1,
                   "login_invite_pending": 1, "login_invite_sent_at": 1},
              ):
                  memberships[str(row.get("user_id"))] = row
          wanted = set(parent_ids)
          for doc in docs:
              doc_aliases = {
                  str(value)
                  for value in (
                      doc.get("user_id"),
                      doc.get("auth_uid"),
                      doc.get("firebase_uid"),
                      doc.get("_id"),
                  )
                  if value
              }
              matched = wanted & doc_aliases
              if not matched:
                  continue
              phone = str(doc.get("phone")) if doc.get("phone") is not None else None
              firebase_uid = doc.get("firebase_uid") or doc.get("auth_uid")
              row = memberships.get(str(firebase_uid)) if firebase_uid else None
              has_account = bool(
                  row
                  and row.get("status") == "active"
                  and "parent" in (row.get("roles") or [])
                  and row.get("login_invite_pending") is not True
              )
              sent_at = row.get("login_invite_sent_at") if row else None
              for pid in matched:
                  result[pid] = LoginFacts(
                      has_login_account=has_account,
                      login_invite_sent_at=sent_at,
                      phone=phone,
                  )
          return result
  ```
  Add a second test asserting the parity with `list_existing_user_ids`, since the two predicates must not drift:
  ```python
  @pytest.mark.asyncio
  async def test_list_login_facts_has_account_matches_list_existing_user_ids(db) -> None:
      await db["users"].insert_one(
          {"_id": "u2", "user_id": "u2", "firebase_uid": "fb-2", "email": "b@x.com",
           "display_name": "Bo", "role": "parent"}
      )
      await db["academy_memberships"].insert_one(
          {"academy_id": "acad-1", "user_id": "fb-2", "status": "active",
           "roles": ["parent"], "login_invite_pending": True}
      )
      repo = MongoUserRepository(db)

      facts = await repo.list_login_facts(["u2"], academy_id="acad-1")
      existing = await repo.list_existing_user_ids(["u2"], academy_id="acad-1")

      assert facts["u2"].has_login_account is False
      assert existing == set()
  ```

- [ ] Run and confirm PASS:
  ```
  cd backend && pytest v2/tests/contract/test_identity_mongo_user_repo.py -q
  ```

- [ ] Commit:
  ```
  git add backend/v2/contexts/identity/infrastructure/mongo_user_repo.py backend/v2/tests/contract/test_identity_mongo_user_repo.py
  git commit -m "feat(identity): add bulk login-facts lookup for the families list

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 3: Backend — wire the families-scoped list in `composition/families.py`

**Files:**
- Modify: `backend/v2/composition/families.py` (add adapters + `lister`; `AdminFamilies` dataclass is lines 43-46, `compose_admin_families` is lines 49-66)
- Test: **`backend/v2/tests/contract/test_compose_admin_families.py`** (create). It must live under `contract/`, not `unit/`: the `db` fixture (mongomock-motor) is defined in `backend/v2/tests/contract/conftest.py` and is not visible from `unit/`.

**Interfaces:**
- Consumes: `ListBillingSetup` (Task 1), `MongoUserRepository.list_login_facts` (Task 2), `MongoStudentRepository`, `ListAdminStudents`, `MongoParentBillingCustomerRepository`, `MongoStudentBillingEnrollmentRepository`, `MongoBillingLedgerRepository`
- Produces: `AdminFamilies.lister: ListBillingSetup`

Steps:

- [ ] Write the failing test `backend/v2/tests/contract/test_compose_admin_families.py`. The tenant-scope helper is **`tenant_scope`** (a *sync* `@contextmanager` in `backend/v2/shared/tenancy/context.py:80`, re-exported from `backend.v2.shared.tenancy`) — there is no `academy_context` in this repo. `contract/conftest.py` also offers an `acad` fixture pinned to `"test-academy"`; use `tenant_scope` here so the academy id is explicit:
  ```python
  """Composition smoke test: compose_admin_families wires a working lister."""

  from __future__ import annotations

  import pytest

  from backend.v2.composition.families import compose_admin_families
  from backend.v2.shared.tenancy import tenant_scope


  @pytest.mark.asyncio
  async def test_compose_admin_families_lister_lists_parents(db) -> None:
      await db["students"].insert_one(
          {"student_id": "s1", "parent_id": "p1", "parent_name": "Ana Cruz",
           "parent_email": "ana@x.com", "full_name": "Priya Cruz", "academy_id": "acad-1",
           "status": "active"}
      )
      families = compose_admin_families(db)

      with tenant_scope("acad-1"):
          page = await families.lister.execute(academy_id="acad-1")

      assert [r.parent_id for r in page.rows] == ["p1"]
      assert page.rows[0].students[0].full_name == "Priya Cruz"
  ```
  If `MongoStudentRepository.list_admin_students` needs more fields on the seed doc than the ones above (check `backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py`'s projection/mapper before running), add exactly those — do not switch to a different fixture.

- [ ] Run it and confirm it fails with `AttributeError: 'AdminFamilies' object has no attribute 'lister'`:
  ```
  cd backend && pytest v2/tests/contract/test_compose_admin_families.py -q
  ```

- [ ] In `composition/families.py`, add the new imports:
  ```python
  from backend.v2.contexts.billing.application.ports import (
      BillingSetupStudent,
      EnrollmentAutopaySnapshot,
      ParentBalanceSnapshot,
      ParentBillingCustomerSnapshot,
      ParentRosterEntry,
  )
  from backend.v2.contexts.billing.application.use_cases.billing_setup_registration import (
      ListBillingSetup,
  )
  from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
      MongoBillingLedgerRepository,
  )
  from backend.v2.contexts.enrollment.application.use_cases.admin_directory import ListAdminStudents
  from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import MongoStudentRepository
  from backend.v2.shared.tenancy import current_academy_id
  ```
  add the adapter classes and `lister` field, modelled exactly on `composition/admin.py` lines 1775-1999 (`_BillingSetupRosterAdapter`, `_BillingSetupLoginAccountAdapter`, `_BillingSetupCustomerAdapter`, `_BillingSetupAutopayAdapter`, `_BillingSetupBalanceAdapter`) but with `parent_phone` and a `login_invites` adapter added.

  **One login-facts fetch per request, shared by three adapters.** `ListBillingSetup.execute` asks the roster for phones, the login-account port for account ids and the login-invite port for timestamps. If each adapter calls `list_login_facts` independently that is three full sweeps of `users` + `academy_memberships` per page load. Put a tiny per-call cache in front of it and hand the same instance to all three:
  ```python
  class _FamiliesLoginFacts:
      """One `list_login_facts` round trip per distinct parent-id set, shared by
      the roster/login-account/login-invite adapters inside a single request.
      Composition objects are process-wide, so the cache is keyed by the exact
      id set and holds only the most recent one — never a growing map."""

      def __init__(self, users: MongoUserRepository) -> None:
          self._users = users
          self._key: tuple[str, frozenset[str]] | None = None
          self._value: dict[str, Any] = {}

      async def get(self, parent_ids: list[str], *, academy_id: str) -> dict[str, Any]:
          key = (academy_id, frozenset(parent_ids))
          if self._key != key:
              self._value = await self._users.list_login_facts(parent_ids, academy_id=academy_id)
              self._key = key
          return self._value
  ```
  ```python
  class _FamiliesRosterAdapter:
      def __init__(
          self,
          list_students: ListAdminStudents,
          facts: _FamiliesLoginFacts,
          users: MongoUserRepository,
          db: Any,
      ) -> None:
          self._list_students = list_students
          self._facts = facts
          self._users = users
          self._db = db

      async def _all_students(self) -> list[Any]:
          students: list[Any] = []
          cursor: str | None = None
          for _ in range(1000):
              page = await self._list_students.execute(limit=200, cursor=cursor)
              students.extend(page.students)
              if not page.next_cursor:
                  break
              cursor = page.next_cursor
          return students

      async def _phones(self, parent_ids: list[str], *, academy_id: str) -> dict[str, str | None]:
          facts = await self._facts.get(parent_ids, academy_id=academy_id)
          return {pid: f.phone for pid, f in facts.items()}

      async def list_parents(self, *, academy_id: str) -> list[ParentRosterEntry]:
          seen: dict[str, ParentRosterEntry] = {}
          for student in await self._all_students():
              if student.parent_id not in seen:
                  seen[student.parent_id] = ParentRosterEntry(
                      parent_id=student.parent_id,
                      parent_name=student.parent_name or student.parent_id,
                      parent_email=student.parent_email,
                  )
          phones = await self._phones(list(seen.keys()), academy_id=academy_id)
          return [
              entry.model_copy(update={"parent_phone": phones.get(pid)})
              for pid, entry in seen.items()
          ]

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
          # admin.py's version is a nested closure over the composition-local
          # `db`; this one is a module-level class, so it uses the injected
          # `self._db`.
          cursor = self._db["students"].find(
              {"academy_id": current_academy_id(),
               "$or": [{"parent_id": parent_id}, {"parent_user_id": parent_id}]}
          )
          return [doc async for doc in cursor]

      async def get_parent(self, parent_id: str, *, academy_id: str) -> ParentRosterEntry | None:
          docs = await self._direct_student_docs(parent_id)
          if not docs:
              return None
          user = await self._users.get_billing_setup_parent(parent_id, academy_id=academy_id)
          if user is None:
              user = await self._users.get_by_id(parent_id)
          first = docs[0]
          fallback_name = str(first.get("parent_name") or first.get("guardian_name") or parent_id)
          fallback_email = first.get("parent_email") or first.get("guardian_email")
          phones = await self._phones([parent_id], academy_id=academy_id)
          return ParentRosterEntry(
              parent_id=parent_id,
              parent_name=user.display_name if user else fallback_name,
              parent_email=str(user.email) if user else (str(fallback_email) if fallback_email else None),
              parent_phone=phones.get(parent_id),
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
              rows.append(BillingSetupStudent(student_id=str(doc.get("student_id") or doc["_id"]), full_name=full_name))
          return rows


  class _FamiliesLoginAccountAdapter:
      def __init__(self, facts: _FamiliesLoginFacts) -> None:
          self._facts = facts

      async def login_account_parent_ids(self, parent_ids: list[str], *, academy_id: str) -> set[str]:
          facts = await self._facts.get(parent_ids, academy_id=academy_id)
          return {pid for pid, f in facts.items() if f.has_login_account}

      async def has_login_account(self, parent_id: str, *, academy_id: str) -> bool:
          facts = await self._facts.get([parent_id], academy_id=academy_id)
          return facts[parent_id].has_login_account


  class _FamiliesLoginInviteAdapter:
      def __init__(self, facts: _FamiliesLoginFacts) -> None:
          self._facts = facts

      async def login_invite_sent_at_by_parent(
          self, parent_ids: list[str], *, academy_id: str
      ) -> dict[str, Any]:
          facts = await self._facts.get(parent_ids, academy_id=academy_id)
          return {pid: f.login_invite_sent_at for pid, f in facts.items()}


  class _FamiliesCustomerAdapter:
      def __init__(self, customers: MongoParentBillingCustomerRepository) -> None:
          self._customers = customers

      async def list_customers(self, *, academy_id: str) -> list[ParentBillingCustomerSnapshot]:
          docs = await self._customers.list_academy_customers()
          snapshots: list[ParentBillingCustomerSnapshot] = []
          for doc in docs:
              label, last4 = self._customers.display_payment_method(doc)
              snapshots.append(
                  ParentBillingCustomerSnapshot(
                      parent_id=str(doc["parent_id"]), stripe_customer_id=doc.get("stripe_customer_id"),
                      card_label=label, card_last4=last4,
                      last_invited_at=doc.get("billing_setup_last_invited_at"),
                  )
              )
          return snapshots

      async def get_customer(self, parent_id: str, *, academy_id: str) -> ParentBillingCustomerSnapshot | None:
          doc = await self._customers.get_academy_customer(parent_id=parent_id)
          if doc is None:
              return None
          label, last4 = self._customers.display_payment_method(doc)
          return ParentBillingCustomerSnapshot(
              parent_id=str(doc["parent_id"]), stripe_customer_id=doc.get("stripe_customer_id"),
              card_label=label, card_last4=last4, last_invited_at=doc.get("billing_setup_last_invited_at"),
          )


  class _FamiliesAutopayAdapter:
      def __init__(self, enrollments: MongoStudentBillingEnrollmentRepository) -> None:
          self._enrollments = enrollments

      async def list_autopay_states(self, *, academy_id: str) -> list[EnrollmentAutopaySnapshot]:
          docs = await self._enrollments.list_academy_autopay_states()
          return [
              EnrollmentAutopaySnapshot(
                  enrollment_id=str(d["enrollment_id"]), parent_id=str(d["parent_id"]),
                  autopay_enrollment_status=d.get("autopay_enrollment_status") or "not_offered",
              )
              for d in docs
          ]

      async def list_parent_autopay_states(
          self, parent_id: str, *, academy_id: str
      ) -> list[EnrollmentAutopaySnapshot]:
          enrollments = await self._enrollments.list_for_parent(parent_id)
          return [
              EnrollmentAutopaySnapshot(
                  enrollment_id=e.enrollment_id, parent_id=e.parent_id,
                  autopay_enrollment_status=e.autopay_enrollment_status,
              )
              for e in enrollments
          ]


  class _FamiliesBalanceAdapter:
      def __init__(self, ledger: MongoBillingLedgerRepository) -> None:
          self._ledger = ledger

      async def billing_setup_by_parent(self, *, academy_id: str) -> dict[str, ParentBalanceSnapshot]:
          rows = await self._ledger.billing_setup_by_parent()
          return {
              pid: ParentBalanceSnapshot(
                  outstanding_cents=int(r["outstanding_cents"]), charge_invoice_id=str(r["charge_invoice_id"]),
                  charge_enrollment_id=str(r["charge_enrollment_id"]) if r.get("charge_enrollment_id") else None,
                  charge_amount_cents=int(r["charge_amount_cents"]),
              )
              for pid, r in rows.items()
          }

      async def billing_setup_for_parent(self, parent_id: str, *, academy_id: str) -> ParentBalanceSnapshot | None:
          rows = await self._ledger.billing_setup_by_parent(parent_id=parent_id)
          r = rows.get(parent_id)
          if r is None:
              return None
          return ParentBalanceSnapshot(
              outstanding_cents=int(r["outstanding_cents"]), charge_invoice_id=str(r["charge_invoice_id"]),
              charge_enrollment_id=str(r["charge_enrollment_id"]) if r.get("charge_enrollment_id") else None,
              charge_amount_cents=int(r["charge_amount_cents"]),
          )
  ```
  update `AdminFamilies` and `compose_admin_families`:
  ```python
  @dataclass(frozen=True)
  class AdminFamilies:
      reader: MongoFamilyBillingReadModel
      pause_autopay: PauseFamilyAutopay
      lister: ListBillingSetup


  def compose_admin_families(db: Any) -> AdminFamilies:
      audit = MongoBillingAuditLogRepository(db)
      users = MongoUserRepository(db)
      login_facts = _FamiliesLoginFacts(users)
      reader = MongoFamilyBillingReadModel(
          db,
          academy_timezone=academy_timezone_lookup(db),
          connected_accounts=MongoConnectedAccountRepository(db),
          billing_settings=MongoBillingSettingsRepository(db),
          customers=MongoParentBillingCustomerRepository(db),
          credits=MongoCreditLedgerRepository(db),
          users=users,
          audit=audit,
      )
      pause = PauseFamilyAutopay(
          enrollments=MongoStudentBillingEnrollmentRepository(db),
          audit=audit,
          idempotency=MongoIdempotencyStore(db),
      )
      lister = ListBillingSetup(
          roster=_FamiliesRosterAdapter(
              ListAdminStudents(MongoStudentRepository(db)), login_facts, users, db
          ),
          login_accounts=_FamiliesLoginAccountAdapter(login_facts),
          customers=_FamiliesCustomerAdapter(MongoParentBillingCustomerRepository(db)),
          autopay=_FamiliesAutopayAdapter(MongoStudentBillingEnrollmentRepository(db)),
          balances=_FamiliesBalanceAdapter(MongoBillingLedgerRepository(db)),
          login_invites=_FamiliesLoginInviteAdapter(login_facts),
      )
      return AdminFamilies(reader=reader, pause_autopay=pause, lister=lister)
  ```
  (`users` was constructed inline as `users=MongoUserRepository(db)` in the existing `reader = MongoFamilyBillingReadModel(...)` call — hoist it to the `users` local above and pass `users=users` there so one repository instance serves both the reader and the lister.)

- [ ] Run and confirm PASS, plus the structural tripwire that guards the composition layer:
  ```
  cd backend && pytest v2/tests/contract/test_compose_admin_families.py v2/tests/structural -q
  ```
  `test_composition_is_wiring.py` only line-budgets `composition/admin.py` (4318/4500, untouched here); `families.py` has no budget. If it fails, the cause is `admin.py` — not this task.

- [ ] Commit:
  ```
  git add backend/v2/composition/families.py backend/v2/tests/contract/test_compose_admin_families.py
  git commit -m "feat(families): wire a families-scoped Billing Setup lister

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 4: Backend — `GET /families` list route

**Files:**
- Modify: `backend/v2/interfaces/admin/families_routes.py` (add route + `AdminFamiliesServices.lister` Protocol member; `AdminFamiliesServices` is at lines 45-47, `router = APIRouter(...)` at line 62)
- Modify: `backend/v2/interfaces/admin/families_views.py` (add DTOs at the end of the file)
- Test: `backend/v2/tests/interface/test_admin_families_routes.py` (existing fixtures: `services` → `FakeServices` at line 145, and the `admin`/`owner`/`coach` `TestClient` fixtures at lines 164-184; `_make_app` mounts `admin_router` under `/api/v2`, so the new route is `GET /api/v2/admin/families`)

**Interfaces:**
- Consumes: `AdminFamiliesServices.lister: FamiliesLister` (new Protocol member)
- Produces: `GET /admin/families?q=&login_state=&status=&has_balance=&sort=&cursor=&limit=` → `FamiliesListResponse`

**Naming note:** `families_views.py` already defines a module-level `RegistrationState = Literal["registered","invited","not_invited"]` (line 15) for the *detail* view. The list's states are the Billing Setup vocabulary (`no_account`/`account_no_card`/`card_on_file`) — spell them inline on `FamiliesListRowView` and in the route signature; do **not** reuse or redefine `RegistrationState`.

Steps:

- [ ] Write the failing test — append to `backend/v2/tests/interface/test_admin_families_routes.py`:
  ```python
  from backend.v2.contexts.billing.application.use_cases.billing_setup_registration import (
      BillingSetupPage,
      BillingSetupRow,
      BillingSetupSummary,
  )


  class FakeLister:
      def __init__(self) -> None:
          self.calls: list[dict[str, Any]] = []

      async def execute(self, **kwargs: Any) -> BillingSetupPage:
          self.calls.append(kwargs)
          row = BillingSetupRow(
              parent_id="p1", parent_name="Ana Cruz", parent_email="ana@x.com",
              registration_state="card_on_file", has_login_account=True,
          )
          return BillingSetupPage(
              rows=(row,),
              summary=BillingSetupSummary(
                  families_total=1, families_registered=1, families_no_card=0, outstanding_total_cents=0
              ),
          )


  def test_list_families_returns_rows(admin: TestClient, services: FakeServices) -> None:
      resp = admin.get(
          "/api/v2/admin/families?q=ana&login_state=active&has_balance=true&sort=needs_attention"
      )
      assert resp.status_code == 200
      body = resp.json()
      assert body["rows"][0]["parent_id"] == "p1"
      assert body["rows"][0]["has_login_account"] is True
      assert services.lister.calls[0]["q"] == "ana"
      assert services.lister.calls[0]["login_state"] == "active"
      assert services.lister.calls[0]["has_balance"] is True
      assert services.lister.calls[0]["sort"] == "needs_attention"


  def test_list_families_is_404_for_coach(coach: TestClient, services: FakeServices) -> None:
      """Wrong persona is 404, never 403 (AGENTS.md, docs/security-matrix.md)."""
      resp = coach.get("/api/v2/admin/families")
      assert resp.status_code == 404
      assert services.lister.calls == []


  def test_list_families_scopes_to_the_caller_academy(
      admin: TestClient, services: FakeServices
  ) -> None:
      """Spec §9: a parent outside the tenant is absent, not forbidden. The route
      never takes an academy id from the client — it passes the claims/tenant one
      through, so a foreign parent simply is not in `rows`."""
      resp = admin.get("/api/v2/admin/families?academy_id=someone-else")
      assert resp.status_code == 200
      assert services.lister.calls[0]["academy_id"] == "acad"
  ```
  and add `self.lister = FakeLister()` to `FakeServices.__init__` (line 146, next to `self.reader`/`self.pause_autopay`), defining `FakeLister` above `FakeServices`. No `# type: ignore` is needed — `lister` is a real attribute of `FakeServices` once it is set in `__init__`.

- [ ] Run and confirm all three fail (404, no such route):
  ```
  cd backend && pytest v2/tests/interface/test_admin_families_routes.py -q -k list_families
  ```

- [ ] In `families_views.py`, add DTOs after `PauseFamilyAutopayResponse` (end of file):
  ```python
  class FamiliesListStudentView(_View):
      student_id: str
      full_name: str


  class FamiliesListRowView(_View):
      parent_id: str
      parent_name: str
      parent_email: str | None = None
      parent_phone: str | None = None
      students: list[FamiliesListStudentView] = []
      registration_state: Literal["no_account", "account_no_card", "card_on_file"]
      card_label: str | None = None
      card_last4: str | None = None
      autopay_active_count: int = 0
      autopay_eligible_count: int = 0
      outstanding_balance_cents: int = 0
      has_login_account: bool = False
      login_invite_sent_at: str | None = None


  class FamiliesListSummaryView(_View):
      families_total: int
      families_registered: int
      families_no_card: int
      outstanding_total_cents: int


  class FamiliesListResponse(_View):
      rows: list[FamiliesListRowView]
      summary: FamiliesListSummaryView
      next_cursor: str | None = None
  ```

- [ ] In `families_routes.py`, add the `FamiliesLister` Protocol member and route. Extend the `Protocol` block (after `FamilyAutopayPauser`, before `AdminFamiliesServices`):
  ```python
  from typing import Literal

  from backend.v2.contexts.billing.application.use_cases.billing_setup_registration import (
      BillingSetupPage,
  )
  from backend.v2.interfaces.admin.families_views import (
      AdminFamilyBillingView,
      FamiliesListResponse,
      FamiliesListRowView,
      FamiliesListStudentView,
      FamiliesListSummaryView,
      PauseFamilyAutopayRequest,
      PauseFamilyAutopayResponse,
  )


  class FamiliesLister(Protocol):
      # Spell the real keyword-only signature, not `**kwargs: object`: a
      # `**kwargs` Protocol is not structurally satisfied by
      # `ListBillingSetup.execute`'s named keyword params, so mypy (CI-only in
      # this repo) would reject any typed assignment of one to the other.
      async def execute(
          self,
          *,
          academy_id: str,
          status_filter: str = "all",
          login_state: str = "all",
          has_balance: bool = False,
          sort: str = "name",
          q: str | None = None,
          cursor: str | None = None,
          limit: int = 50,
      ) -> BillingSetupPage: ...


  class AdminFamiliesServices(Protocol):
      reader: FamilyBillingReader
      pause_autopay: FamilyAutopayPauser
      lister: FamiliesLister
  ```
  add the route, above `family_billing` (right after `router = APIRouter(...)`):
  ```python
  def _to_list_response(page: BillingSetupPage) -> FamiliesListResponse:
      return FamiliesListResponse(
          rows=[
              FamiliesListRowView(
                  parent_id=row.parent_id,
                  parent_name=row.parent_name,
                  parent_email=row.parent_email,
                  parent_phone=row.parent_phone,
                  students=[
                      FamiliesListStudentView(student_id=s.student_id, full_name=s.full_name)
                      for s in row.students
                  ],
                  registration_state=row.registration_state,
                  card_label=row.card_label,
                  card_last4=row.card_last4,
                  autopay_active_count=row.autopay_active_count,
                  autopay_eligible_count=row.autopay_eligible_count,
                  outstanding_balance_cents=row.outstanding_balance_cents,
                  has_login_account=row.has_login_account,
                  login_invite_sent_at=row.login_invite_sent_at.isoformat()
                  if row.login_invite_sent_at
                  else None,
              )
              for row in page.rows
          ],
          summary=FamiliesListSummaryView(
              families_total=page.summary.families_total,
              families_registered=page.summary.families_registered,
              families_no_card=page.summary.families_no_card,
              outstanding_total_cents=page.summary.outstanding_total_cents,
          ),
          next_cursor=page.next_cursor,
      )


  @router.get("/families", response_model=FamiliesListResponse)
  async def list_families(
      status: Literal["all", "no_account", "account_no_card", "card_on_file"] = "all",
      login_state: Literal["all", "never_invited", "invited", "active"] = "all",
      has_balance: bool = False,
      sort: Literal["name", "needs_attention"] = "name",
      q: str | None = None,
      cursor: str | None = None,
      limit: int = Query(default=50, ge=1, le=200),
      claims: AuthClaims = Depends(require_persona("admin")),
      services: AdminFamiliesServices = Depends(get_admin_families),
  ) -> FamiliesListResponse:
      """Every parent, folding identity + login state with billing (spec §3).

      Tenant scope comes from `_academy_id(claims)` only — there is deliberately
      no `academy_id` query param, so a foreign parent is *absent* rather than
      403 (spec §9).
      """
      page = await services.lister.execute(
          academy_id=_academy_id(claims),
          status_filter=status,
          login_state=login_state,
          has_balance=has_balance,
          sort=sort,
          q=q,
          cursor=cursor,
          limit=limit,
      )
      return _to_list_response(page)
  ```
  (`Query` comes from `fastapi` — extend the existing `from fastapi import APIRouter, Depends, HTTPException, Request` import on line 16. The bare `int = 50` in the original draft let a caller ask for `limit=100000` and page the whole tenant in one request.)

  Register this route **before** `family_billing` so `/families` is matched literally rather than being shadowed — with `/families/{parent_id}/billing` it cannot actually collide, but keeping the literal first is the house pattern.

- [ ] Run and confirm PASS:
  ```
  cd backend && pytest v2/tests/interface/test_admin_families_routes.py -q
  ```

- [ ] Commit:
  ```
  git add backend/v2/interfaces/admin/families_routes.py backend/v2/interfaces/admin/families_views.py backend/v2/tests/interface/test_admin_families_routes.py
  git commit -m "feat(families): add GET /admin/families list route

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 5: Backend — expose login state on the family detail header

**Files:**
- Modify: `backend/v2/contexts/billing/application/family_billing.py` (`CustomerFacts` at lines 187-193; `build_family_billing_view`'s header dict, lines 767-805)
- Modify: `backend/v2/contexts/billing/infrastructure/family_billing_read_model.py` (`_customer()`, lines 779-817)
- Modify: `backend/v2/interfaces/admin/families_views.py` (`FamilyHeader` at lines 68-75)
- Test: `backend/v2/tests/unit/test_family_billing.py`

**Interfaces:**
- Produces: `CustomerFacts.login_invite_sent_at: datetime | None`; `header.login = {has_account: bool, invited_at: str | None}` in `AdminFamilyBillingView`

> **Do not reuse `CustomerFacts.last_invited_at` for this.** Verified at
> `family_billing_read_model.py:816`, it is
> `parent_billing_customers.billing_setup_last_invited_at` — the *add-a-card*
> reminder, already surfaced as `header.registration.last_invited_at`. Wiring
> `header.login.invited_at` to it would (a) print the wrong date under a
> "Never invited / Invited / Active" badge and (b) make the detail header
> disagree with the list's Login chip, which Task 1 sources from
> `academy_memberships.login_invite_sent_at`. Both surfaces must read the same
> fact.

Steps:

- [ ] Add the new fact to `CustomerFacts` (line 187, `@dataclass(frozen=True)`), defaulting so nothing else has to change:
  ```python
  @dataclass(frozen=True)
  class CustomerFacts:
      has_card: bool | None  # None = lookup failed (unknown)
      card_last4: str | None
      card_label: str | None
      last_invited_at: datetime | None  # Billing Setup "add a card" reminder
      has_login_account: bool
      login_invite_sent_at: datetime | None = None  # identity "set your password" invite
  ```

- [ ] In `family_billing_read_model.py`'s `_customer()` (lines 779-817), fetch the login facts alongside the existing `list_existing_user_ids` call and thread the timestamp into all three `CustomerFacts(...)` return sites:
  ```python
          has_login = False
          login_sent_at: datetime | None = None
          try:
              facts = await self._users.list_login_facts([parent_id], academy_id=academy_id)
              row = facts.get(parent_id)
              has_login = bool(row and row.has_login_account)
              login_sent_at = row.login_invite_sent_at if row else None
          except Exception:
              log.warning("family billing read model: login lookup failed", exc_info=True)
  ```
  `list_login_facts` uses exactly the predicate `list_existing_user_ids` used, so `has_login` is unchanged (Task 2 has a parity test for that). Pass `login_invite_sent_at=login_sent_at` in each of the three `CustomerFacts(...)` constructions (lines ~797, ~805, ~812).

- [ ] Write the failing test, appended to `backend/v2/tests/unit/test_family_billing.py`. Its `_facts(**kw)` helper (line 92) takes **top-level `FamilyFacts` fields** — `_facts(has_login_account=...)` would raise `TypeError`; pass a whole `CustomerFacts`. `NOW`/`TODAY` are already defined in that file:
  ```python
  def test_header_exposes_login_state() -> None:
      view = build_family_billing_view(
          _facts(
              customer=CustomerFacts(
                  has_card=True,
                  card_last4="4242",
                  card_label="Visa",
                  last_invited_at=None,          # billing-setup invite: absent
                  has_login_account=True,
                  login_invite_sent_at=datetime(2026, 9, 1, tzinfo=UTC),
              )
          ),
          timezone="America/Chicago",
          generated_at=NOW,
          today=TODAY,
      )
      assert view["header"]["login"] == {
          "has_account": True,
          "invited_at": "2026-09-01T00:00:00+00:00",
      }
      # The two invites stay separate.
      assert view["header"]["registration"]["last_invited_at"] is None
  ```

- [ ] Run and confirm it fails (`KeyError: 'login'`):
  ```
  cd backend && pytest v2/tests/unit/test_family_billing.py -q -k login_state
  ```

- [ ] In `family_billing.py`, add `"login"` to the `"header"` dict (after `"registration"`, before `"enrollment_counts"`, around line 796):
  ```python
          "header": {
              "balance_cents": sum(inv.balance_due_cents for inv in open_rows),
              "open_invoice_count": len(open_rows),
              "available_credit_cents": facts.available_credit_cents,
              "last_payment": _last_payment(facts),
              "autopay": { ... unchanged ... },
              "registration": { ... unchanged ... },
              "login": {
                  "has_account": facts.customer.has_login_account,
                  "invited_at": _iso(facts.customer.login_invite_sent_at),
              },
              "enrollment_counts": { ... unchanged ... },
          },
  ```
  (only the new `"login"` key is added; leave every existing key exactly as-is — note `enrollment_counts` really does carry a `held` key in the source, which the view model drops via `extra="ignore"`; do not "tidy" it.)

- [ ] In `families_views.py`, add `FamilyLogin` and wire it into `FamilyHeader` (lines 68-75):
  ```python
  class FamilyLogin(_View):
      has_account: bool
      invited_at: str | None = None


  class FamilyHeader(_View):
      balance_cents: int
      open_invoice_count: int
      available_credit_cents: int
      last_payment: FamilyLastPayment | None = None
      autopay: FamilyAutopay
      registration: FamilyRegistration
      login: FamilyLogin
      enrollment_counts: FamilyEnrollmentCounts
  ```

- [ ] `login: FamilyLogin` is **required** on `FamilyHeader` (no default), so every fixture that feeds `AdminFamilyBillingView.model_validate` must gain it. Fix them before running:
  - `backend/v2/tests/interface/test_admin_families_routes.py`'s `_view()` (starts line 23; the `"header"` dict is lines 28-45): add `"login": {"has_account": False, "invited_at": None},` next to `"registration"`.
  - Grep for any other builder of this payload before running the suite: `grep -rn '"registration": {' backend/v2/tests backend/v2/contexts | grep -v family_billing.py`.

- [ ] Run and confirm PASS (the whole billing/families surface, not just the two files, since `CustomerFacts` gained a field):
  ```
  cd backend && pytest v2/tests/unit/test_family_billing.py v2/tests/interface/test_admin_families_routes.py v2/tests/contract/test_family_billing_read_model.py -q
  ```

- [ ] Commit:
  ```
  git add backend/v2/contexts/billing/application/family_billing.py backend/v2/contexts/billing/infrastructure/family_billing_read_model.py backend/v2/interfaces/admin/families_views.py backend/v2/tests/unit/test_family_billing.py backend/v2/tests/interface/test_admin_families_routes.py
  git commit -m "feat(families): expose login account state on the family header

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 6: Frontend — types and pure view helpers

**Files:**
- Modify: `frontend/lib/api/admin-families.ts` (`FamilyHeader` interface lines 50-58; add `FamilyLogin`, `fetchFamiliesList`; `apiFetch` is already imported from `./client` at line 7)
- Modify: `frontend/app/(admin)/admin/families/[parentId]/family-view.ts` (add `loginBadge` after `registrationChip`)
- Modify: `frontend/lib/query/keys.ts` (add `familiesList` immediately after `families: () => ...` at line 68)
- Test: `frontend/app/(admin)/admin/families/[parentId]/family-view.test.ts` (exists; vitest runs with `globals: false`, and the file already imports `describe`/`expect`/`it` from `"vitest"` and several helpers from `"./family-view"`)

**Interfaces:**
- Produces: `loginBadge(login: FamilyLogin): { label: string; variant: ChipVariant }`; `fetchFamiliesList(params: FamiliesListParams): Promise<FamiliesListResponse>`

Steps:

- [ ] Write the failing test — add `loginBadge` to the file's **existing** `from "./family-view"` import block (a second `import … from "./family-view"` is a duplicate-import lint error), then append:
  ```ts
  describe("loginBadge", () => {
    it("active: has an account", () => {
      expect(loginBadge({ has_account: true, invited_at: "2026-09-01T00:00:00Z" })).toEqual({
        label: "Active", variant: "enrolled",
      });
    });
    it("invited: no account yet but invited", () => {
      expect(loginBadge({ has_account: false, invited_at: "2026-09-01T00:00:00Z" })).toEqual({
        label: "Invited Sep 1", variant: "pending",
      });
    });
    it("never invited", () => {
      expect(loginBadge({ has_account: false, invited_at: null })).toEqual({
        label: "Never invited", variant: "manual",
      });
    });
  });
  ```

- [ ] Run and confirm it fails to import `loginBadge`:
  ```
  cd frontend && pnpm vitest run app/\(admin\)/admin/families/\[parentId\]/family-view.test.ts
  ```

- [ ] In `admin-families.ts`, add `FamilyLogin` and wire it into `FamilyHeader` (lines 50-58):
  ```ts
  export interface FamilyLogin {
    has_account: boolean;
    invited_at: string | null;
  }

  export interface FamilyHeader {
    balance_cents: number;
    open_invoice_count: number;
    available_credit_cents: number;
    last_payment: FamilyLastPayment | null;
    autopay: FamilyAutopay;
    registration: FamilyRegistration;
    login: FamilyLogin;
    enrollment_counts: { active: number; paused: number; cancelled: number };
  }
  ```
  add the list types and fetcher at the end of the file. `admin-families.ts` already exports a *different* `RegistrationState` (`"registered" | "invited" | "not_invited"`, the detail-view vocabulary), so the list row needs its own name — re-export the Billing Setup one that `lib/api/admin.ts` already defines rather than inventing a third spelling:
  ```ts
  import type { BillingSetupRegistrationState } from "./admin";
  // …or, if importing across the two api modules is undesirable, declare it here:
  // export type BillingSetupRegistrationState = "no_account" | "account_no_card" | "card_on_file";
  ```
  ```ts
  export interface FamiliesListStudent {
    student_id: string;
    full_name: string;
  }

  export interface FamiliesListRow {
    parent_id: string;
    parent_name: string;
    parent_email: string | null;
    parent_phone: string | null;
    students: FamiliesListStudent[];
    registration_state: BillingSetupRegistrationState;
    card_label: string | null;
    card_last4: string | null;
    autopay_active_count: number;
    autopay_eligible_count: number;
    outstanding_balance_cents: number;
    has_login_account: boolean;
    login_invite_sent_at: string | null;
  }

  export interface FamiliesListSummary {
    families_total: number;
    families_registered: number;
    families_no_card: number;
    outstanding_total_cents: number;
  }

  export interface FamiliesListResponse {
    rows: FamiliesListRow[];
    summary: FamiliesListSummary;
    next_cursor: string | null;
  }

  export type LoginStateFilter = "all" | "never_invited" | "invited" | "active";

  export interface FamiliesListParams {
    status?: "all" | BillingSetupRegistrationState;
    login_state?: LoginStateFilter;
    has_balance?: boolean;
    sort?: "name" | "needs_attention";
    q?: string;
    cursor?: string;
    limit?: number;
  }

  export function fetchFamiliesList(
    params: FamiliesListParams = {},
  ): Promise<FamiliesListResponse> {
    const search = new URLSearchParams();
    if (params.status) search.set("status", params.status);
    if (params.login_state) search.set("login_state", params.login_state);
    if (params.has_balance) search.set("has_balance", "true");
    if (params.sort) search.set("sort", params.sort);
    if (params.q) search.set("q", params.q);
    if (params.cursor) search.set("cursor", params.cursor);
    if (params.limit) search.set("limit", String(params.limit));
    const qs = search.toString();
    return apiFetch<FamiliesListResponse>(`/admin/families${qs ? `?${qs}` : ""}`, { method: "GET" });
  }
  ```

- [ ] In `family-view.ts`, add `loginBadge` (after `registrationChip`, using the `shortDate` helper already in the file — verified: it slices `iso.slice(0, 10)`, so an ISO instant like `"2026-09-01T00:00:00Z"` yields `"Sep 1"`). Add `FamilyLogin` to the **existing** `import type { … } from "@/lib/api/admin-families"` block at the top of the file rather than adding a second import:
  ```ts
  export interface LoginBadge {
    label: string;
    variant: ChipVariant;
  }

  export function loginBadge(login: FamilyLogin): LoginBadge {
    if (login.has_account) return { label: "Active", variant: "enrolled" };
    // shortDate returns `string | null`; fall back rather than printing "Invited null".
    const day = shortDate(login.invited_at);
    if (day) return { label: `Invited ${day}`, variant: "pending" };
    if (login.invited_at) return { label: "Invited", variant: "pending" };
    return { label: "Never invited", variant: "manual" };
  }
  ```
  (`ChipVariant` is already imported at the top of `family-view.ts`; `"enrolled"`, `"pending"` and `"manual"` are all real `ChipVariant` members — verified against `components/ds/chip.tsx`.)

- [ ] In `frontend/lib/query/keys.ts`, add a list-params key immediately after `families: () => ["admin", "families"] as const,` (line 68, above `familyBilling` on line 69):
  ```ts
      families: () => ["admin", "families"] as const,
      familiesList: (params?: {
        q?: string;
        loginState?: string;
        status?: string;
        hasBalance?: boolean;
        sort?: string;
      }) =>
        [
          "admin",
          "families",
          "list",
          params?.q ?? "",
          params?.loginState ?? "all",
          params?.status ?? "all",
          params?.hasBalance ?? false,
          params?.sort ?? "name",
        ] as const,
  ```
  Spell the prefix literally rather than `[...queryKeys.admin.families(), …]`: `queryKeys` is still being initialised inside its own object literal, so referring to it there is a TDZ error. Note this key is a *sibling* of `familyBilling` under the same `["admin","families"]` prefix, so `invalidateQueries({ queryKey: queryKeys.admin.families() })` correctly refreshes both the list and any open detail page.

- [ ] Run and confirm PASS:
  ```
  cd frontend && pnpm vitest run app/\(admin\)/admin/families/\[parentId\]/family-view.test.ts
  ```

- [ ] Commit:
  ```
  git add frontend/lib/api/admin-families.ts frontend/app/\(admin\)/admin/families/\[parentId\]/family-view.ts frontend/app/\(admin\)/admin/families/\[parentId\]/family-view.test.ts frontend/lib/query/keys.ts
  git commit -m "feat(families): add login badge helper and families-list API client

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 7: Frontend — `FamilyHeader` identity strip

**Files:**
- Modify: `frontend/app/(admin)/admin/families/[parentId]/FamilyHeader.tsx` (rewrite of the top identity block, lines 29-63; the tiles/`Tile` below are unchanged)
- Create: `frontend/app/(admin)/admin/families/[parentId]/family-contact-dialog.tsx`
- Modify: `frontend/app/(admin)/admin/families/[parentId]/page.tsx` (wire new handlers next to `onSendInvite`, lines 197-215)
- Test: manual verification via `pnpm typecheck` (no new pure-logic branch beyond `loginBadge`, already tested in Task 6); e2e coverage added in Task 12.

**Interfaces:**
- Consumes: `sendLoginInvite(parentId)` (`frontend/lib/api/admin.ts:1567` → `POST /admin/users/{id}/login-invite`), `updateAdminUser(parentId, payload)` (`frontend/lib/api/admin.ts:1492` → `PATCH /admin/users/{id}`; `reason` is optional server-side with a default, but pass an explicit one so the audit trail is readable)
- Produces: `FamilyHeader` props gain `onSendLoginInvite: () => void`, `onEditContact: (patch: { display_name: string; phone: string | null }) => void`

**Two buttons, two different invites — and the login one must not be hidden from the parents who need it.** The header already has a `send_invite` action driven by `actions.includes("send_invite")`; verified at `page.tsx:204-209` it calls `inviteBillingSetupParent` — the *add a card* invite. The new button is the identity **login invite** (`sendLoginInvite`), and it must be visible in all three login states, with the label following the state:

| `header.login` | Label | Why |
|---|---|---|
| `has_account: false, invited_at: null` | **Send login invite** | never invited — this is precisely when the admin needs the button |
| `has_account: false, invited_at: <date>` | **Resend login invite** | invited, hasn't set a password yet |
| `has_account: true` | **Send password reset** | live account; the same endpoint mails a fresh reset link |

Gating the button on `header.login.has_account` (as the first draft did) hides it in rows 1 and 2. That is backwards: a parent created through "Add parent" gets a Firebase user with `login_invite_pending: true` on their membership, so `has_login_account` is **false** until the first invite is sent — the button would never appear for a brand-new parent. Spec §4 requires "Send / resend invite" here.

Steps:

- [ ] Create `family-contact-dialog.tsx`, modelled on the `ReasonDialog` pattern in `family-dialogs.tsx` (read that file's imports/Radix Dialog usage first: `grep -n "^import\|Dialog.Root" frontend/app/\(admin\)/admin/families/\[parentId\]/family-dialogs.tsx`):
  ```tsx
  "use client";

  import { useState } from "react";
  import * as Dialog from "@radix-ui/react-dialog";

  import { Button } from "@/components/ds/button";

  export function EditContactDialog({
    open,
    initialName,
    initialPhone,
    busy,
    onClose,
    onSubmit,
  }: {
    open: boolean;
    initialName: string;
    initialPhone: string;
    busy: boolean;
    onClose: () => void;
    onSubmit: (patch: { display_name: string; phone: string | null }) => void;
  }) {
    const [name, setName] = useState(initialName);
    const [phone, setPhone] = useState(initialPhone);

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
              onSubmit={(e) => {
                e.preventDefault();
                onSubmit({ display_name: name.trim(), phone: phone.trim() || null });
              }}
            >
              <label className="block text-sm">
                <span className="mb-1 block font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                  Name
                </span>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  maxLength={120}
                  data-testid="family-contact-name"
                  className="h-10 w-full rounded-md border border-neutral-200 px-3 text-sm"
                />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                  Phone
                </span>
                <input
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  maxLength={40}
                  data-testid="family-contact-phone"
                  className="h-10 w-full rounded-md border border-neutral-200 px-3 text-sm"
                />
              </label>
              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="secondary" onClick={onClose}>
                  Cancel
                </Button>
                <Button type="submit" disabled={busy} data-testid="family-contact-save">
                  {busy ? "Saving..." : "Save"}
                </Button>
              </div>
            </form>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    );
  }
  ```

- [ ] Rewrite the identity block in `FamilyHeader.tsx` (lines 1-64), adding mailto/tel links, the login badge, and the two new actions:
  ```tsx
  "use client";

  import { useState } from "react";
  import Link from "next/link";

  import { Button, Card, Chip, Overline } from "@/components/ds";
  import type { AdminFamilyBillingView, FamilyLogin } from "@/lib/api/admin-families";
  import { formatCents, formatInstantDay } from "@/lib/money";

  import { EditContactDialog } from "./family-contact-dialog";
  import { autopayToggle, loginBadge, registrationChip } from "./family-view";

  export function FamilyHeader({
    view,
    busy,
    onToggleAutopay,
    onSendInvite,
    onSendLoginInvite,
    onEditContact,
    onSendInvoice,
    onRecordPayment,
  }: {
    view: AdminFamilyBillingView;
    busy: boolean;
    onToggleAutopay: (turnOn: boolean) => void;
    /** Billing Setup "add a card" invite (existing behaviour). */
    onSendInvite: () => void;
    /** Identity "set your password" login invite / password reset (new). */
    onSendLoginInvite: () => void;
    onEditContact: (patch: { display_name: string; phone: string | null }) => void;
    onSendInvoice: () => void;
    onRecordPayment: () => void;
  }) {
    const { parent, header, actions } = view;
    const toggle = autopayToggle(header.autopay);
    const reg = registrationChip(header.registration.state);
    const login = loginBadge(header.login);
    const studentCount = view.students.length;
    const [editOpen, setEditOpen] = useState(false);

    return (
      <Card p={20}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="font-display text-xl font-semibold text-rally-ink">
              {parent.name ?? "Parent"}
            </h1>
            <p className="text-sm text-rally-muted">
              {parent.email ? (
                <a href={`mailto:${parent.email}`} className="hover:underline" data-testid="family-email">
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
                  <a href={`tel:${parent.phone}`} className="hover:underline" data-testid="family-phone">
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
                <Button size="sm" variant="secondary" data-testid="family-send-invite" onClick={onSendInvite} disabled={busy}>
                  {header.registration.last_invited_at ? "Resend card invite" : "Send card invite"}
                </Button>
              )}
              {/* Always rendered — a never-invited parent is exactly who needs it. */}
              <Button size="sm" variant="secondary" data-testid="family-send-login-invite" onClick={onSendLoginInvite} disabled={busy}>
                {loginInviteLabel(header.login)}
              </Button>
              <Button size="sm" variant="secondary" data-testid="family-edit-contact" onClick={() => setEditOpen(true)} disabled={busy}>
                Edit contact
              </Button>
              <Link href={`/admin/messages?dm=${encodeURIComponent(parent.parent_id)}`} className="text-sm text-rally-cobalt-700 hover:underline">
                Message
              </Link>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {actions.includes("send_invoice") && (
              <Button size="sm" variant="secondary" data-testid="family-send-invoice" onClick={onSendInvoice} disabled={busy}>
                Send invoice
              </Button>
            )}
            {actions.includes("record_payment") && (
              <Button size="sm" variant="primary" data-testid="family-record-payment" onClick={onRecordPayment} disabled={busy}>
                Record payment
              </Button>
            )}
          </div>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Tile overline="Balance" testId="family-balance" big={formatCents(header.balance_cents)}
            sub={`${header.open_invoice_count} open ${header.open_invoice_count === 1 ? "invoice" : "invoices"}${header.available_credit_cents > 0 ? ` · ${formatCents(header.available_credit_cents)} credit` : ""}`} />
          <div className="rounded-xl border border-rally-line p-3">
            <Overline>Autopay</Overline>
            <label className="mt-1 flex items-center gap-3">
              <input type="checkbox" role="switch" data-testid="family-autopay-toggle" aria-label="Autopay"
                aria-checked={toggle.checked} checked={toggle.checked} disabled={toggle.disabled || busy}
                onChange={(e) => onToggleAutopay(e.target.checked)} className="size-5 accent-rally-cobalt-600" />
              <span className="font-display text-lg font-semibold text-rally-ink">{toggle.label}</span>
            </label>
            <p className="mt-1 text-xs text-rally-muted" data-testid="family-autopay-hint">{toggle.hint}</p>
            {header.autopay.last_failure?.code && (
              <p className="mt-1 text-xs text-status-red-600">Last failure: {header.autopay.last_failure.code}</p>
            )}
          </div>
          <Tile overline="Last payment" testId="family-last-payment"
            big={header.last_payment ? formatCents(header.last_payment.amount_cents) : "—"}
            sub={header.last_payment ? `${formatInstantDay(header.last_payment.paid_at)} · ${header.last_payment.method ?? "payment"}` : "No payments yet"} />
          <Tile overline="Enrollments" testId="family-enrollments"
            big={String(header.enrollment_counts.active + header.enrollment_counts.paused)}
            sub={`${header.enrollment_counts.active} active · ${header.enrollment_counts.paused} paused`} />
        </div>

        <EditContactDialog
          open={editOpen}
          initialName={parent.name ?? ""}
          initialPhone={parent.phone ?? ""}
          busy={busy}
          onClose={() => setEditOpen(false)}
          onSubmit={(patch) => {
            onEditContact(patch);
            setEditOpen(false);
          }}
        />
      </Card>
    );
  }

  /** Label for the identity login invite — see the state table in this task. */
  function loginInviteLabel(login: FamilyLogin): string {
    if (login.has_account) return "Send password reset";
    return login.invited_at ? "Resend login invite" : "Send login invite";
  }

  function Tile({ overline, big, sub, testId }: { overline: string; big: string; sub: string; testId: string }) {
    return (
      <div className="rounded-xl border border-rally-line p-3" data-testid={testId}>
        <Overline>{overline}</Overline>
        <div className="mt-1 font-display text-lg font-semibold text-rally-ink">{big}</div>
        <p className="text-xs text-rally-muted">{sub}</p>
      </div>
    );
  }
  ```

- [ ] In `page.tsx`, add the two new handlers next to `onSendInvite` (after line 209) and pass them to `<FamilyHeader>`. Add `sendLoginInvite` and `updateAdminUser` to the **existing** `from "@/lib/api/admin"` import block (lines 9-18, alphabetically ordered — `sendLoginInvite` goes after `sendAdminInvoice`, `updateAdminUser` after `voidAdminInvoice`'s block per the file's ordering):
  ```tsx
        onSendLoginInvite={() =>
          simple.mutate(async () => {
            await sendLoginInvite(parentId);
            setToast(
              view.header.login.has_account
                ? "Password reset email sent."
                : "Login invite sent.",
            );
          })
        }
        onEditContact={(patch) =>
          simple.mutate(async () => {
            await updateAdminUser(parentId, {
              ...patch,
              reason: "family page contact edit",
            });
            setToast("Contact details updated.");
          })
        }
  ```
  `simple`'s `onSuccess` already invalidates `queryKeys.admin.familyBilling(parentId)`, so the login badge and the header name/phone refresh on their own — do not add a manual refetch. `sendLoginInvite` can reject (`LoginInviteSendFailed` → non-2xx); `simple`'s `onError` surfaces the message in the same toast, which is the behaviour the neighbouring actions already have.

- [ ] Typecheck and run the existing family-view/admin-families vitest suites:
  ```
  cd frontend && pnpm typecheck && pnpm vitest run app/\(admin\)/admin/families
  ```

- [ ] Commit:
  ```
  git add frontend/app/\(admin\)/admin/families/\[parentId\]/FamilyHeader.tsx frontend/app/\(admin\)/admin/families/\[parentId\]/family-contact-dialog.tsx frontend/app/\(admin\)/admin/families/\[parentId\]/page.tsx
  git commit -m "feat(families): fold identity, login badge and contact actions into FamilyHeader

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 8: Frontend — extract `CreateUserDialog` for reuse

**Files:**
- Create: `frontend/components/admin/CreateUserDialog.tsx`
- Modify: `frontend/components/admin/AdminUsersDirectory.tsx` (remove the inline `CreateUserDialog`/`Field` definitions at lines 139-288, import the shared one; drop the "Parents" pill and `fixedRole="parent"` support). Verified: nothing in `app/` passes `fixedRole` today — `app/(admin)/admin/users/page.tsx` is this component's only caller — so narrowing the prop type is type-only churn, not a behaviour change.
- Test: existing `frontend/e2e/specs/admin-shell.spec.ts` "Create user" coverage (run, not rewritten, in Task 12) plus a typecheck pass here.

**Interfaces:**
- Produces: `CreateUserDialog({ open, onOpenChange, fixedRole, onCreated, roleOptions })` — `roleOptions` lets a caller restrict the dropdown (Users directory: `["coach", "assistant_coach"]`; Families page: fixed to `"parent"`).

Steps:

- [ ] Create `frontend/components/admin/CreateUserDialog.tsx` by lifting `CreateUserDialog` (line 139) and `Field` (ends line 288) out of `AdminUsersDirectory.tsx` verbatim, generalizing the role dropdown to a `roleOptions` prop instead of the hardcoded `<option>` list. Note `components/ds/dialog-chrome.tsx` already exports a `Field`; keep this one module-local (do not export it) so the two never collide:
  ```tsx
  "use client";

  import { useState } from "react";
  import type { ReactNode } from "react";
  import * as Dialog from "@radix-ui/react-dialog";
  import { useMutation } from "@tanstack/react-query";

  import { createAdminUser, type AdminUserRole } from "@/lib/api/admin";
  import { Button } from "@/components/ds/button";

  type CreatableRole = Extract<AdminUserRole, "coach" | "assistant_coach" | "parent">;

  const ROLE_LABELS: Record<CreatableRole, string> = {
    parent: "Parent",
    coach: "Coach",
    assistant_coach: "Assistant coach",
  };

  export function CreateUserDialog({
    open,
    onOpenChange,
    fixedRole,
    roleOptions,
    onCreated,
  }: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    fixedRole?: CreatableRole;
    roleOptions: CreatableRole[];
    onCreated: () => void;
  }) {
    const [role, setRole] = useState<CreatableRole>(fixedRole ?? roleOptions[0]);
    const [displayName, setDisplayName] = useState("");
    const [email, setEmail] = useState("");
    const [phone, setPhone] = useState("");
    const [reason, setReason] = useState("Manual user onboarding");
    const [error, setError] = useState<string | null>(null);

    const mutation = useMutation({
      mutationFn: () =>
        createAdminUser({
          role: fixedRole ?? role,
          display_name: displayName.trim(),
          email: email.trim().toLowerCase(),
          phone: phone.trim() || null,
          reason,
        }),
      onSuccess: () => {
        setDisplayName("");
        setEmail("");
        setPhone("");
        setReason("Manual user onboarding");
        setError(null);
        onCreated();
      },
      onError: (err: unknown) => {
        setError(err instanceof Error ? err.message : "Could not create user.");
      },
    });

    return (
      <Dialog.Root open={open} onOpenChange={onOpenChange}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-neutral-950/40" />
          <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(92vw,520px)] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-rally-line bg-white p-5 shadow-xl focus:outline-none">
            <Dialog.Title className="font-display text-xl font-bold text-rally-ink">
              {fixedRole ? `Add ${ROLE_LABELS[fixedRole].toLowerCase()}` : "Add user"}
            </Dialog.Title>
            <form
              className="mt-4 space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                setError(null);
                mutation.mutate();
              }}
            >
              {!fixedRole && (
                <Field label="Role" htmlFor="create-user-role">
                  <select
                    id="create-user-role"
                    value={role}
                    onChange={(event) => setRole(event.target.value as CreatableRole)}
                    className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                  >
                    {roleOptions.map((r) => (
                      <option key={r} value={r}>{ROLE_LABELS[r]}</option>
                    ))}
                  </select>
                </Field>
              )}
              <Field label="Name" htmlFor="create-user-name">
                <input id="create-user-name" value={displayName} onChange={(e) => setDisplayName(e.target.value)}
                  className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                  required maxLength={120} />
              </Field>
              <Field label="Email" htmlFor="create-user-email">
                <input id="create-user-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                  className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                  required maxLength={254} />
              </Field>
              <Field label="Phone" htmlFor="create-user-phone">
                <input id="create-user-phone" value={phone} onChange={(e) => setPhone(e.target.value)}
                  className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                  maxLength={40} />
              </Field>
              <Field label="Reason" htmlFor="create-user-reason">
                <input id="create-user-reason" value={reason} onChange={(e) => setReason(e.target.value)}
                  className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                  required maxLength={500} />
              </Field>
              {error && <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}
              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button>
                <Button type="submit" disabled={mutation.isPending}>{mutation.isPending ? "Saving..." : "Save"}</Button>
              </div>
            </form>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    );
  }

  function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: ReactNode }) {
    return (
      <label className="block" htmlFor={htmlFor}>
        <span className="mb-1.5 block font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">{label}</span>
        {children}
      </label>
    );
  }
  ```

- [ ] In `AdminUsersDirectory.tsx`: delete the inline `CreateUserDialog` and `Field` functions (lines 139-288), delete the `"Parents"` entry from the `roles` array (line 30), delete `type CreatableRole` (line 34, now owned by the shared file), replace the import block and usage. The now-unused `Dialog`, `useMutation` and `ReactNode` imports (lines 4, 7, 8) must go too or `pnpm lint` fails:
  ```tsx
  import { createAdminUser, listAdminUsers, type AdminUserRole, type AdminUserView } from "@/lib/api/admin";
  ```
  remove `createAdminUser` from that import (no longer used directly here) and add:
  ```tsx
  import { CreateUserDialog } from "@/components/admin/CreateUserDialog";
  ```
  update the `roles` array (line 26-32) to drop Parents:
  ```tsx
  const roles: Array<{ label: string; value: AdminUserRole | undefined }> = [
    { label: "All", value: undefined },
    { label: "Coaches", value: "coach" },
    { label: "Assistant coaches", value: "assistant_coach" },
    { label: "Admins", value: "admin" },
  ];
  ```
  change the `AdminUsersDirectory` signature to drop `"parent"` from `fixedRole`'s type (lines 45-49):
  ```tsx
  export function AdminUsersDirectory({
    fixedRole,
  }: {
    fixedRole?: Extract<AdminUserRole, "coach">;
  }) {
  ```
  update the `createLabel`/render usage (line 73, 111-119) to use the shared component with `roleOptions`:
  ```tsx
    const createLabel = fixedRole === "coach" ? "Add coach" : "Add user";
  ```
  ```tsx
        <CreateUserDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          fixedRole={fixedRole}
          roleOptions={["coach", "assistant_coach"]}
          onCreated={() => {
            setCreateOpen(false);
            void queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
          }}
        />
  ```
  update `parseRoleParam` (lines 36-43) to stop accepting `"parent"` as a valid role tab value (Task 10 makes `role=parent` redirect before this component ever sees it, but the parser should no longer treat it as a legal in-page tab):
  ```tsx
  function parseRoleParam(value: string | null): AdminUserRole | undefined {
    return value === "coach" || value === "assistant_coach" || value === "admin" ? value : undefined;
  }
  ```

- [ ] Typecheck:
  ```
  cd frontend && pnpm typecheck
  ```
  Fix any remaining reference to the removed `"parent"` role tab or unused imports the compiler flags.

- [ ] Commit:
  ```
  git add frontend/components/admin/CreateUserDialog.tsx frontend/components/admin/AdminUsersDirectory.tsx
  git commit -m "refactor(admin): extract CreateUserDialog and drop parents from AdminUsersDirectory

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 9: Frontend — Families list page

**Files:**
- Modify: `frontend/app/(admin)/admin/families/page.tsx` (full rewrite)
- Test: e2e coverage added in Task 12 (`admin-families-list.spec.ts`); this task ends with `pnpm typecheck`.

**Interfaces:**
- Consumes: `fetchFamiliesList` (Task 6), `CreateUserDialog` (Task 8)

Steps:

- [ ] Rewrite `page.tsx` to call `fetchFamiliesList`, add the Login column + login-state filter + "has balance" filter + "Needs attention" sort, and the Add-parent dialog:
  ```tsx
  "use client";

  /**
   * Admin Families list — the one place to find a parent: identity, login
   * state and billing folded together (spec 2026-09-10-families-directory-
   * consolidation §3). Detail actions live on `/admin/families/[parentId]`.
   */

  import { useEffect, useMemo, useState } from "react";
  import type { Route } from "next";
  import Link from "next/link";
  import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
  import { Plus } from "lucide-react";

  import { sendLoginInvite } from "@/lib/api/admin";
  import {
    fetchFamiliesList,
    type FamiliesListRow,
    type LoginStateFilter,
  } from "@/lib/api/admin-families";
  import { queryKeys } from "@/lib/query/keys";

  import { Button } from "@/components/ds/button";
  import { Card } from "@/components/ds/card";
  import { Chip, type ChipVariant } from "@/components/ds/chip";
  import { BigNum, Overline } from "@/components/ds/typography";
  import { CreateUserDialog } from "@/components/admin/CreateUserDialog";

  function formatCents(cents: number): string {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
  }

  function billingChip(state: FamiliesListRow["registration_state"]): { variant: ChipVariant; label: string } {
    if (state === "card_on_file") return { variant: "paid", label: "REGISTERED" };
    if (state === "account_no_card") return { variant: "pending", label: "NO CARD" };
    return { variant: "nocharge", label: "NOT INVITED" };
  }

  function loginChip(row: FamiliesListRow): { variant: ChipVariant; label: string } {
    if (row.has_login_account) return { variant: "enrolled", label: "ACTIVE" };
    if (row.login_invite_sent_at) return { variant: "pending", label: "INVITED" };
    return { variant: "manual", label: "NEVER INVITED" };
  }

  const BILLING_FILTERS: { value: "all" | "no_account" | "account_no_card" | "card_on_file"; label: string }[] = [
    { value: "all", label: "All" },
    { value: "no_account", label: "Not invited" },
    { value: "account_no_card", label: "No card" },
    { value: "card_on_file", label: "Chargeable" },
  ];

  const LOGIN_FILTERS: { value: LoginStateFilter; label: string }[] = [
    { value: "all", label: "Any login" },
    { value: "never_invited", label: "Never invited" },
    { value: "invited", label: "Invited" },
    { value: "active", label: "Active" },
  ];

  const familyHref = (parentId: string) => `/admin/families/${encodeURIComponent(parentId)}` as Route;

  export default function FamiliesPage() {
    const queryClient = useQueryClient();
    const [status, setStatus] = useState<"all" | "no_account" | "account_no_card" | "card_on_file">("all");
    const [loginState, setLoginState] = useState<LoginStateFilter>("all");
    const [hasBalanceOnly, setHasBalanceOnly] = useState(false);
    const [needsAttention, setNeedsAttention] = useState(false);
    const [q, setQ] = useState("");
    const [debouncedQ, setDebouncedQ] = useState("");
    const [addOpen, setAddOpen] = useState(false);

    // Spec §3 row actions: "Open, Send invite when applicable".
    const invite = useMutation({
      mutationFn: (parentId: string) => sendLoginInvite(parentId),
      onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.admin.families() }),
    });

    useEffect(() => {
      const timer = window.setTimeout(() => setDebouncedQ(q.trim()), 300);
      return () => window.clearTimeout(timer);
    }, [q]);

    // Every filter and the sort are SERVER-side: the list is cursor-paginated,
    // so filtering or reordering `pages.flatMap(...)` would only touch the pages
    // already fetched and would disagree with the summary tiles.
    const params = useMemo(
      () => ({
        status,
        login_state: loginState,
        has_balance: hasBalanceOnly || undefined,
        sort: needsAttention ? ("needs_attention" as const) : undefined,
        q: debouncedQ || undefined,
      }),
      [status, loginState, hasBalanceOnly, needsAttention, debouncedQ],
    );
    const { data, isLoading, isError, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
      queryKey: queryKeys.admin.familiesList({
        q: debouncedQ,
        loginState,
        status,
        hasBalance: hasBalanceOnly,
        sort: needsAttention ? "needs_attention" : "name",
      }),
      queryFn: ({ pageParam }) => fetchFamiliesList({ ...params, cursor: pageParam || undefined }),
      initialPageParam: "",
      getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    });

    const summary = data?.pages[0]?.summary;
    const rows = data?.pages.flatMap((page) => page.rows) ?? [];

    return (
      <div className="flex flex-col gap-6" data-testid="admin-families">
        <div className="flex items-center justify-between">
          <p className="text-sm text-rally-muted">
            Families · every parent, their login and billing state; open one for the full picture
          </p>
          <Button size="sm" icon={<Plus className="size-4" aria-hidden="true" />} onClick={() => setAddOpen(true)} data-testid="admin-families-add">
            Add parent
          </Button>
        </div>

        <CreateUserDialog
          open={addOpen}
          onOpenChange={setAddOpen}
          fixedRole="parent"
          roleOptions={["parent"]}
          onCreated={() => {
            setAddOpen(false);
            void queryClient.invalidateQueries({ queryKey: queryKeys.admin.families() });
          }}
        />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
          <Card p={20}><Overline>Families</Overline><BigNum>{summary?.families_total ?? "—"}</BigNum></Card>
          <Card p={20}><Overline>Registered</Overline><BigNum className="text-rally-cobalt-700">{summary?.families_registered ?? "—"}</BigNum></Card>
          <Card p={20}><Overline>Missing a card</Overline><BigNum className="text-rally-volt-700">{summary?.families_no_card ?? "—"}</BigNum></Card>
          <Card p={20}><Overline>Outstanding</Overline><BigNum size={28}>{formatCents(summary?.outstanding_total_cents ?? 0)}</BigNum></Card>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex gap-1 rounded-md border border-slate-200 bg-white p-1">
            {BILLING_FILTERS.map((f) => (
              <button key={f.value} onClick={() => setStatus(f.value)}
                className={`rounded px-3 py-1.5 text-sm font-medium ${status === f.value ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}>
                {f.label}
              </button>
            ))}
          </div>
          <div className="flex gap-1 rounded-md border border-slate-200 bg-white p-1">
            {LOGIN_FILTERS.map((f) => (
              <button key={f.value} onClick={() => setLoginState(f.value)}
                className={`rounded px-3 py-1.5 text-sm font-medium ${loginState === f.value ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}>
                {f.label}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" checked={hasBalanceOnly} onChange={(e) => setHasBalanceOnly(e.target.checked)} data-testid="admin-families-has-balance" />
            Has balance
          </label>
          <button
            type="button"
            onClick={() => setNeedsAttention((v) => !v)}
            data-testid="admin-families-needs-attention"
            className={`rounded px-3 py-1.5 text-sm font-medium ${needsAttention ? "bg-slate-900 text-white" : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-100"}`}
          >
            Needs attention
          </button>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, email, phone or child…"
            className="w-72 rounded-md border border-slate-200 px-3 py-1.5 text-sm" />
        </div>

        <Card p={0}>
          {isLoading ? (
            <div className="p-8 text-center text-sm text-slate-500">Loading…</div>
          ) : isError ? (
            <div className="p-8 text-center text-sm text-red-600">Failed to load Families.</div>
          ) : rows.length === 0 ? (
            <div className="p-8 text-center text-sm text-slate-500">No families match this filter.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-xs uppercase text-slate-500">
                    <th className="px-4 py-3">Family</th>
                    <th className="px-4 py-3">Contact</th>
                    <th className="px-4 py-3">Login</th>
                    <th className="px-4 py-3">Billing</th>
                    <th className="px-4 py-3">Autopay</th>
                    <th className="px-4 py-3">Outstanding</th>
                    <th className="px-4 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <FamilyTableRow
                      key={row.parent_id}
                      row={row}
                      busy={invite.isPending}
                      onSendInvite={() => invite.mutate(row.parent_id)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {hasNextPage && (
            <div className="border-t border-rally-line p-4 text-center">
              <Button size="sm" variant="secondary" onClick={() => fetchNextPage()} disabled={isFetchingNextPage}>
                {isFetchingNextPage ? "Loading…" : "Load more families"}
              </Button>
            </div>
          )}
        </Card>
      </div>
    );
  }

  function FamilyTableRow({
    row,
    busy,
    onSendInvite,
  }: {
    row: FamiliesListRow;
    busy: boolean;
    onSendInvite: () => void;
  }) {
    const billing = billingChip(row.registration_state);
    const login = loginChip(row);
    const href = familyHref(row.parent_id);
    // "when applicable" (spec §3) = the parent has no live login yet.
    const canInvite = !row.has_login_account;

    return (
      <tr className="border-b border-slate-100 last:border-0">
        <td className="px-4 py-3">
          <Link href={href} data-testid={`family-link-${row.parent_id}`} className="font-medium text-slate-900 hover:underline">
            {row.parent_name}
          </Link>
          <div className="mt-1 flex flex-wrap gap-1">
            {row.students.map((s) => (
              <span key={s.student_id} className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">{s.full_name}</span>
            ))}
          </div>
        </td>
        <td className="px-4 py-3 text-xs text-slate-500">
          <div>{row.parent_email ?? "—"}</div>
          <div>{row.parent_phone ?? "—"}</div>
        </td>
        <td className="px-4 py-3"><Chip variant={login.variant} label={login.label} /></td>
        <td className="px-4 py-3"><Chip variant={billing.variant} label={billing.label} /></td>
        <td className="px-4 py-3 text-slate-700">
          {row.autopay_active_count > 0 || row.autopay_eligible_count > 0
            ? `${row.autopay_active_count} active · ${row.autopay_eligible_count} resumable`
            : "—"}
        </td>
        <td className="px-4 py-3 text-slate-700">{formatCents(row.outstanding_balance_cents)}</td>
        <td className="px-4 py-3">
          <div className="flex items-center gap-3">
            <Link href={href} className="text-sm font-medium text-rally-cobalt-700 hover:underline">Open</Link>
            {canInvite && (
              <button
                type="button"
                onClick={onSendInvite}
                disabled={busy}
                data-testid={`family-invite-${row.parent_id}`}
                className="text-sm font-medium text-rally-cobalt-700 hover:underline disabled:opacity-50"
              >
                {row.login_invite_sent_at ? "Resend invite" : "Send invite"}
              </button>
            )}
          </div>
        </td>
      </tr>
    );
  }
  ```

- [ ] Typecheck and lint:
  ```
  cd frontend && pnpm typecheck && pnpm lint
  ```

- [ ] **Do the `/admin/families` manifest edit from Task 12 now, and commit it with this page** — spec §9 and the repo convention require the QA inventory manifest to move in the same commit as the page it describes, and `test_inventory_static_gaps.py` goes red the moment this rewrite lands without it. (Task 12 still owns the `/admin/parents` entry, which rides with Task 10's redirect.)

- [ ] Commit:
  ```
  git add frontend/app/\(admin\)/admin/families/page.tsx docs/qa/2026-06-28-production-scale-local-inventory-manifest.json
  git commit -m "feat(families): consolidate list with login state, search and Add-parent

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 10: Frontend — redirects and Users directory subtitle

**Files:**
- Modify: `frontend/app/(admin)/admin/parents/page.tsx` (redirect target)
- Modify: `frontend/app/(admin)/admin/users/page.tsx` (redirect `?role=parent`)
- Modify: `frontend/components/admin/screen-meta.ts` (line 178 subtitle)

**Interfaces:** none new — both are `next/navigation` redirects already used elsewhere in this file tree.

Steps:

- [ ] Update `frontend/app/(admin)/admin/parents/page.tsx`:
  ```tsx
  import { redirect } from "next/navigation";

  export default function AdminParentsPage() {
    redirect("/admin/families");
  }
  ```

- [ ] Update `frontend/app/(admin)/admin/users/page.tsx` to redirect when `role=parent` is present. The existing file is a sync server component that just renders `<Suspense><AdminUsersDirectory /></Suspense>`; make it `async` and read the `searchParams` prop. **There is no precedent for a server-side `searchParams` read in `frontend/app/` — every existing page uses the client `useSearchParams()` hook** — so this is the first one; `next` is pinned at `16.3.4` in `frontend/package.json`, where `searchParams` is a `Promise`:
  ```tsx
  import { redirect } from "next/navigation";
  import { Suspense } from "react";

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
  Because no other page in the repo does this, verify it end to end rather than trusting the shape: after `pnpm typecheck`, run `pnpm build` for this route and then the Task 12 e2e (`admin-shell`), which asserts the redirect actually lands. Reading `searchParams` makes `/admin/users` dynamic; that is fine (the whole `(admin)` tree is client-rendered behind auth), but a build error here would otherwise only surface in CI.

  **OPEN QUESTION (owner):** `/admin/users?role=parent` is a *tab* link inside `AdminUsersDirectory` today (`selectRole` pushes the query string). Task 8 removes the Parents pill, so nothing in-app produces that URL any more and this redirect exists purely for old bookmarks. Confirm that a permanent server redirect (rather than, say, silently normalising to `?role=coach`) is the wanted behaviour for a bookmarked parent tab — the spec says "redirect to `/admin/families`", which this implements literally.

- [ ] Update `frontend/components/admin/screen-meta.ts` line 178:
  ```ts
    "/admin/users": { title: "Users", subtitle: "Coaches and admins", breadcrumbs: ["Admin", "Users"] },
  ```

- [ ] Typecheck:
  ```
  cd frontend && pnpm typecheck
  ```

- [ ] **Do the `/admin/parents` manifest edit from Task 12 now and include it here** — spec §9: "a redirect target change touches `docs/qa/…inventory-manifest.json` — same commit".

- [ ] Commit:
  ```
  git add frontend/app/\(admin\)/admin/parents/page.tsx frontend/app/\(admin\)/admin/users/page.tsx frontend/components/admin/screen-meta.ts docs/qa/2026-06-28-production-scale-local-inventory-manifest.json
  git commit -m "feat(admin): redirect /admin/parents and users?role=parent to Families

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 11: Frontend — user detail page parent pointer

**Files:**
- Modify: `frontend/app/(admin)/admin/users/[userId]/page.tsx` (`AdminUserDetailPage` lines 85-104; `Header` lines 413-454)

**Interfaces:** none new.

Steps:

- [ ] In `AdminUserDetailPage` (around line 76, next to `const isCoach = user.role === "coach";`), compute a parent-only flag and hide `LoginInvitePanel` for it:
  ```tsx
    const isCoach = user.role === "coach";
    const isParentOnly = user.role === "parent" && (user.roles.length === 0 || user.roles.every((r) => r === "parent"));
  ```
  then in the JSX (lines 85-103), pass `isParentOnly` to `Header` and conditionally render `LoginInvitePanel`:
  ```tsx
    return (
      <section className="space-y-6" data-testid="admin-user-detail">
        <BackLink />
        <Header user={user} isParentOnly={isParentOnly} />
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
        {!isParentOnly && <LoginInvitePanel user={user} onSaved={invalidate} />}
        {isCoach && <CoachPayRatePanel coachId={user.user_id} />}
        {isCoach && <CoachSessionsPanel user={user} onAssigned={invalidate} />}
      </section>
    );
  ```

- [ ] In `Header` (lines 413-454), add the pointer banner:
  ```tsx
  function Header({ user, isParentOnly }: { user: AdminUserDetail; isParentOnly: boolean }) {
    return (
      <Card p={20}>
        {isParentOnly && (
          <div
            className="mb-4 rounded-md border border-rally-line bg-rally-paper px-3 py-2 text-sm text-rally-muted"
            data-testid="user-detail-parent-pointer"
          >
            This is a parent — manage on the{" "}
            <Link href={`/admin/families/${encodeURIComponent(user.user_id)}`} className="text-rally-cobalt-700 hover:underline">
              family page
            </Link>
            .
          </div>
        )}
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          {/* ... unchanged ... */}
        </div>
      </Card>
    );
  }
  ```
  add the `Link` import at the top of the file if not already present (`grep -n '^import Link' frontend/app/\(admin\)/admin/users/\[userId\]/page.tsx` — it already imports `Link` from `"next/link"` at line 4, so reuse it).

- [ ] Typecheck:
  ```
  cd frontend && pnpm typecheck
  ```

- [ ] Commit:
  ```
  git add frontend/app/\(admin\)/admin/users/\[userId\]/page.tsx
  git commit -m "feat(users): point a parent-only user detail page at the family page

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 12: QA manifest and e2e coverage

**Files:**
- Modify: `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` (`/admin/parents` entry at lines 621-656 **and** the `/admin/families` entry at lines 251-284)
- Modify: `frontend/e2e/specs/admin-shell.spec.ts` (redirect test, lines 984-1002)
- Modify: `frontend/e2e/specs/admin-family-billing.spec.ts` (**both** `header` fixtures — the module-level `FAMILY` at line 20 and the second one inside the later test at line 266 — plus new assertions)
- Create: `frontend/e2e/specs/admin-families-list.spec.ts`
- Test: `cd backend && pytest v2/tests/unit -q -k "inventory or manifest"`; `cd frontend && pnpm exec playwright test admin-shell admin-family-billing admin-families-list --project=chromium-desktop --project=chromium-mobile` (there is **no** project named `chromium` — `frontend/playwright.config.ts` defines only `chromium-mobile`, `webkit-mobile`, `chromium-desktop`; `admin-shell` matches `chromium-desktop`'s `testMatch`, the two `*famil*` specs run under `chromium-mobile`)

**Interfaces:** none new — verification task.

Steps:

- [ ] Update the `/admin/parents` manifest entry (lines 621-656) to the redirect shape, mirroring the `/admin/billing-setup` entry at lines 228-249:
  ```json
      {
        "route": "/admin/parents",
        "role": "admin",
        "source": "frontend/app/(admin)/admin/parents/page.tsx",
        "workflows": [
          "Redirect to /admin/families"
        ],
        "controls": {
          "buttons": [],
          "inputs": [],
          "modals": []
        },
        "states": [
          "redirect"
        ],
        "risk_edges": [
          "Old bookmark lands on the redirect"
        ],
        "acceptance": [
          "Workflow evidence: \"Redirect to /admin/families\" completes for the admin route /admin/parents with real-user evidence and no framework or runtime errors.",
          "Risk evidence: \"Old bookmark lands on the redirect\" has an explicit pass, fail, or blocked result with reproduction context in the real-user checklist."
        ]
      },
  ```

- [ ] Update the `/admin/families` manifest entry too (lines 251-284). Task 9 rewrote `frontend/app/(admin)/admin/families/page.tsx`, and `backend/v2/tests/unit/test_inventory_static_gaps.py::test_current_inventory_manifest_has_no_static_source_gaps` scans that real source against the manifest's `controls` — a stale entry fails the backend suite, and spec §9 requires the manifest move in the same commit. Reflect the new surface:
  ```json
        "workflows": [
          "Filter and search families",
          "Open a family",
          "Send a login invite from the list",
          "Add a parent"
        ],
        "controls": {
          "buttons": [
            "All",
            "Not invited",
            "No card",
            "Chargeable",
            "Any login",
            "Never invited",
            "Invited",
            "Active",
            "Needs attention",
            "Load more families",
            "Open",
            "Send invite",
            "Add parent"
          ],
          "inputs": [
            "Search name, email, phone or child",
            "Has balance"
          ],
          "modals": [
            "Add parent"
          ]
        },
  ```
  and add matching `acceptance` lines for the two new workflows (the audit test asserts `len(acceptance) >= len(workflows)` and `>= len(risk_edges)`), following the exact sentence template the file already uses.

- [ ] Run the four manifest/inventory audit tests (they live in `backend/v2/tests/unit/`, not `tests/interface/`):
  ```
  cd backend && pytest v2/tests/unit/test_audit_inventory_manifest.py v2/tests/unit/test_inventory_static_gaps.py v2/tests/unit/test_inventory_acceptance_coverage.py v2/tests/unit/test_inventory_control_evidence.py -q
  ```
  No new `app/` route is added by this plan (only existing routes change), so the hardcoded route-count assertions (`len(routes) >= 49`, `test_inventory_manifest_matches_frontend_app_route_tree`) need no edit — but re-run them to confirm.

- [ ] In `admin-shell.spec.ts`, update the redirect test (lines 984-1002). The real body is below — keep `stubAdminBff(page)` and the pre-armed `waitForURL` (the comment explains the #683 race), swap the URL regex and title, and replace the two Users-directory assertions with a Families one. **Also add a `GET /api/v2/admin/families*` stub**, since the page now lands on a list that fetches:
  ```ts
    test("/admin/parents redirects into Families", async ({ page }) => {
      const errors = collectConsoleErrors(page);
      await stubAdminBff(page);
      await page.route("**/api/v2/admin/families?*", (route) =>
        fulfillJson(route, {
          rows: [],
          summary: {
            families_total: 0,
            families_registered: 0,
            families_no_card: 0,
            outstanding_total_cents: 0,
          },
          next_cursor: null,
        }),
      );
      // Arm before navigating: the redirect fires during load and can abort
      // `page.goto` itself, and the 5s expect default is shorter than a cold
      // compile — the same race #683 armed for the other bookmark redirects.
      const landed = page.waitForURL(/\/admin\/families$/, { timeout: 30_000 });
      await page.goto("/admin/parents", { waitUntil: "commit" }).catch(() => undefined);
      await landed;
      await expect(page.getByTestId("admin-families")).toBeVisible();
      expect(
        errors,
        `App console errors on /admin/parents redirect: ${errors.join("\n")}`,
      ).toEqual([]);
    });
  ```
  Check whether `stubAdminBff` in this file already covers `/admin/families*`; if it does, drop the extra `page.route` rather than double-registering. Confirm `fulfillJson` is imported in `admin-shell.spec.ts` (it is imported in `admin-family-billing.spec.ts`; add it here if missing).
  The neighbouring `/admin/coaches` redirect test (just above, ending line 982) is untouched by this plan.

- [ ] In `admin-family-billing.spec.ts`, add `login` to **both** header fixtures — `FamilyHeader.login` is required, so a fixture without it makes `loginBadge(undefined)` throw at render and the spec fails with a blank page:
  - the module-level `FAMILY.header` (line 20, next to `registration` on line 40): `login: { has_account: true, invited_at: null },`
  - the second `header` inside the later test (line 266, next to `registration` on line 275): `login: { has_account: false, invited_at: null },`

  Then add new assertions in the existing test body (find the test that asserts `family-registration-chip`, and add alongside it):
  ```ts
    await expect(page.getByTestId("family-login-chip")).toHaveText(/ACTIVE|Active/i);
    // has_account: true → the button reads "Send password reset" (see Task 7's table)
    await expect(page.getByTestId("family-send-login-invite")).toHaveText(/password reset/i);

    await page.getByTestId("family-send-login-invite").click();
    await expect(page.getByTestId("family-toast")).toContainText("Password reset");

    await page.getByTestId("family-edit-contact").click();
    await page.getByTestId("family-contact-name").fill("Sahaya V.");
    await page.getByTestId("family-contact-save").click();
    await expect(page.getByTestId("family-toast")).toContainText("Contact details updated");
  ```
  **Register both new route stubs before `page.goto`, with the other stubs** — a Playwright handler added after the request fires never runs, so putting them inline (as an earlier draft did) makes the two clicks hit the real backend and hang:
  ```ts
    await page.route("**/api/v2/admin/users/parent-1/login-invite", (route) =>
      fulfillJson(route, { sent_at: "2026-09-10T15:05:00Z" }),
    );
    await page.route("**/api/v2/admin/users/parent-1", (route) =>
      fulfillJson(route, {
        user_id: "parent-1", display_name: "Sahaya V.", email: "sahaya@example.com",
        phone: "+15551234567", role: "parent", roles: ["parent"], status: "active",
        linked_student_count: 1, session_count: 0,
        login_invite: { status: "not_needed", sent_at: null, error: null },
      }),
    );
  ```
  Playwright resolves routes **last-registered-first**, so register the specific `/login-invite` pattern *after* the generic `…/parent-1` one (as written above). Confirm with `--trace=on` that the POST and the PATCH each hit their own stub.

- [ ] Create `frontend/e2e/specs/admin-families-list.spec.ts`. Verified: `admin-family-billing.spec.ts` is the **only** existing `*famil*` spec, so model the stubbing on it (its imports at lines 1-11 confirm every helper named below exists):
  ```ts
  import { test, expect } from "@playwright/test";

  import { installTenantGuard } from "../fixtures/tenant-isolation";
  import { ACADEMY_A, ADMIN_USER_A, fulfillJson, stubAcademy, stubMe, stubMemberships } from "../fixtures/saas-stubs";

  const ROW = {
    parent_id: "parent-1", parent_name: "Ana Cruz", parent_email: "ana@example.com", parent_phone: "+15551234567",
    students: [{ student_id: "s1", full_name: "Priya Cruz" }],
    registration_state: "card_on_file", card_label: "Visa", card_last4: "4242",
    autopay_active_count: 1, autopay_eligible_count: 0, outstanding_balance_cents: 0,
    has_login_account: true, login_invite_sent_at: "2026-09-01T00:00:00Z",
  };

  test("Families list shows the login column and filters by login state", async ({ page }) => {
    await installTenantGuard(page, ACADEMY_A);
    await stubMe(page, ADMIN_USER_A);
    await stubAcademy(page, ACADEMY_A);
    await stubMemberships(page, ACADEMY_A, [ADMIN_USER_A]);
    await page.route("**/api/v2/admin/families?*", (route) =>
      fulfillJson(route, {
        rows: [ROW],
        summary: { families_total: 1, families_registered: 1, families_no_card: 0, outstanding_total_cents: 0 },
        next_cursor: null,
      }),
    );
    await page.goto("/admin/families");
    await expect(page.getByTestId("family-link-parent-1")).toBeVisible();
    await expect(page.getByText("ACTIVE")).toBeVisible();
  });
  ```
  Add a second test that proves the filters are **server-side** — this is the regression the client-side version would have hidden:
  ```ts
  test("login-state and has-balance filters go to the server", async ({ page }) => {
    const urls: string[] = [];
    await installTenantGuard(page, ACADEMY_A);
    await stubMe(page, ADMIN_USER_A);
    await stubAcademy(page, ACADEMY_A);
    await stubMemberships(page, ACADEMY_A, [ADMIN_USER_A]);
    await page.route("**/api/v2/admin/families?*", (route) => {
      urls.push(route.request().url());
      return fulfillJson(route, {
        rows: [ROW],
        summary: { families_total: 1, families_registered: 1, families_no_card: 0, outstanding_total_cents: 0 },
        next_cursor: null,
      });
    });
    await page.goto("/admin/families");
    await expect(page.getByTestId("family-link-parent-1")).toBeVisible();

    await page.getByRole("button", { name: "Never invited" }).click();
    await page.getByTestId("admin-families-has-balance").check();
    await page.getByTestId("admin-families-needs-attention").click();

    await expect
      .poll(() => urls.at(-1))
      .toMatch(/login_state=never_invited.*has_balance=true.*sort=needs_attention|sort=needs_attention/);
  });
  ```
  Match `stubMe`/`stubAcademy`/`stubMemberships`/`fulfillJson`/`ACADEMY_A`/`ADMIN_USER_A` call signatures exactly as `admin-family-billing.spec.ts` uses them (all are exported from `frontend/e2e/fixtures/saas-stubs.ts`; `installTenantGuard` comes from `../fixtures/tenant-isolation`). Note "Never invited" is an ambiguous accessible name — it appears both as a login filter button and as a billing filter label ("Not invited" is the billing one, so the two do not actually collide, but re-check with `--trace=on` if the locator is strict-mode-violating and scope it to the login filter group).

- [ ] Run the new and updated specs:
  ```
  cd frontend && pnpm exec playwright test admin-shell admin-family-billing admin-families-list --project=chromium-desktop --project=chromium-mobile
  ```

- [ ] Commit (the two manifest entries were already committed alongside their pages in Tasks 9 and 10; if either was missed, add it here):
  ```
  git add frontend/e2e/specs/admin-shell.spec.ts frontend/e2e/specs/admin-family-billing.spec.ts frontend/e2e/specs/admin-families-list.spec.ts
  git commit -m "test(families): cover login badge, login invite, edit contact and redirects

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 13: Parity check script (spec §7 step 2)

**Files:**
- Create: `scripts/dev/families_parity_check.py`

**Interfaces:** none — a one-off operator script, not imported by the app.

Spec §7 gates the second PR (redirects + pill removal) on proving that every parent visible in the Users directory shows up in Families with the same email/phone/invite state. Without this, the redirect ships blind: `GET /admin/users?role=parent` lists parents from the `users` collection, while `GET /admin/families` derives its roster from `students.parent_id` via `ListAdminStudents` — **a parent with no student rows is in the first list and absent from the second.** That divergence is exactly what this check has to surface before parents lose their directory.

Steps:

- [ ] Write `scripts/dev/families_parity_check.py`: take a base URL, a bearer token and an academy id; fetch every page of `GET /api/v2/admin/users?role=parent` and every page of `GET /api/v2/admin/families`; join on `parent_id`/`user_id`; print three sections — **only in Users** (the childless-parent case above), **only in Families**, and **field mismatches** (email, phone, login state). Exit non-zero if any section is non-empty so it can gate the second PR. Follow the argparse/`httpx` shape of the existing scripts in `scripts/dev/` (read one first, e.g. `scripts/dev/release_notes_check.py`, for the house CLI conventions).

- [ ] Run it against local or staging and record the output in the PR description. If "only in Users" is non-empty, **stop and raise it with the owner** before shipping Task 10's redirects.

  **OPEN QUESTION (owner):** the spec assumes the two lists are equivalent, but the Families roster is student-derived. What should happen to a parent with zero students — appear in Families as a childless row, or stay reachable only via `/admin/users/[userId]`? The answer decides whether `_FamiliesRosterAdapter.list_parents` needs a `users`-collection union before the redirect can ship.

- [ ] Commit:
  ```
  git add scripts/dev/families_parity_check.py
  git commit -m "chore(families): add a Users↔Families parity check for the redirect rollout

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Task 14: Release note

**Files:**
- Create: `docs/release-notes/2026-09-10-families-directory-consolidation.md`

Steps:

- [ ] Write the release note. `scripts/dev/release_notes_check.py` requires exactly the three headings `## What changed`, `## Deploy notes`, `## Risk / rollback`, each with a non-empty body, plus a `PR: #<number>` line whose number matches the real PR (`find_existing_note` greps for the literal `PR: #<n>`). House style puts the `PR:` line directly under the H1 — see `docs/release-notes/2026-09-10-absence-notice-706.md`:
  ```markdown
  # Families directory consolidation

  PR: #<real number — fill in immediately after `gh pr create`, before pushing this commit>

  ## What changed

  `/admin/families` is now the one place to find a parent: the list folds in
  login state (never invited / invited / active) alongside the existing
  billing state, and gains search by name, email, phone or child name, a
  login-state filter, a "has balance" filter and a "Needs attention" sort.
  The family detail header now shows the parent's email (mailto), phone
  (tel), login badge, and three actions — send/resend invite, send a
  password reset, and edit name/phone — reusing the existing `/admin/users`
  invite and edit endpoints. `/admin/parents` and `/admin/users?role=parent`
  now redirect to `/admin/families`; the Users directory drops its Parents
  pill and the "Add parent" flow moves to the Families list.

  ## Deploy notes

  No migration and no new collections — the families list is powered by a
  second, families-scoped wiring of the existing Billing Setup read model
  (`composition/families.py`), so `composition/admin.py` is untouched. No
  feature flag; both the old `/admin/billing/setup` route (unused by the
  frontend after this change but left in place) and the new
  `GET /admin/families` route stay live.

  ## Risk / rollback

  Low risk: every backend change is additive (new optional fields/params on
  `BillingSetupRow`/`ListBillingSetup`, a new route) and the old
  `/billing/setup` route's existing callers are unaffected. Rollback is a
  revert of this PR; the redirect changes are the only user-visible
  behavior change to a URL a bookmark might target, and the old
  `/admin/parents` → `/admin/users?role=parent` redirect chain still exists
  in git history if a fast partial revert is ever needed.
  ```

- [ ] Verify the note passes the gate locally before pushing:
  ```
  python3 scripts/dev/release_notes_check.py --help   # confirm the flag names, then run the check for this PR number
  ```
  A `PR: #<placeholder>` will make the "Release Notes Gate" report the notes as missing — the number must be the real one.

- [ ] Commit:
  ```
  git add docs/release-notes/2026-09-10-families-directory-consolidation.md
  git commit -m "docs(release-notes): add release note for families directory consolidation

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  ```

## Self-review

| Spec section | Covered by |
|---|---|
| §1 Purpose (one place for parents) | Tasks 3, 4, 8, 9 |
| §2 Owner decisions (parents removed from Users; no new Family model; identity folded into FamilyHeader; Add-parent dialog moves) | Tasks 7, 8, 9, 10 |
| §3 Families list — columns (Family/Contact/Login/Billing/Autopay/Outstanding) | Task 9 |
| §3 Families list — server-side search on name/email/phone/child name | Tasks 1, 4, 9 |
| §3 Families list — filters: login state, billing state, has balance (all server-side) | Tasks 1, 4, 9 |
| §3 Families list — default name sort + one-click "Needs attention" sort (server-side) | Tasks 1, 4, 9 |
| §3 Families list — row actions: Open, **Send invite when applicable** | Task 9 (`FamilyTableRow`, gated on `!has_login_account`) |
| §3 Backend — `q`/`login_state`/pagination, login facts from the `users`/membership documents, wiring in `composition/families.py` not `admin.py` | Tasks 1, 2, 3, 4 |
| §4 Family detail page — mailto/tel, login badge, kids count, registration chip | Tasks 5, 6, 7 |
| §4 Family detail page — **Send / resend invite** (identity login invite) and **Send password reset** | Task 7 — one button whose label follows login state; deliberately always rendered, since a never-invited parent is precisely who needs it |
| §4 Family detail page — **Edit contact details** (name, phone only; email edit stays on `/admin/users/[userId]` with its warning) | Task 7 (`EditContactDialog` has no email field) |
| §4 Roles not editable from the family page | No task needed — `RolesPanel` is only on `/admin/users/[userId]`; the family header adds no role control |
| §4 StudentsPanel rows link to the student page | **Already true on main** — verified `StudentsPanel.tsx:23` (`studentHref`) links every row; no work required |
| §5 Users directory (drop Parents pill, drop `fixedRole="parent"`, user detail pointer + hidden invite panel for parent-only users) | Tasks 8, 11 |
| §5 Nav: "Users" stays, "Families" already exists | No task needed — verified `screen-meta.ts:57,73`; there is no Parents nav item to remove |
| §6 What this unblocks | **Deferred** — explicitly named as follow-on specs (Spec 4's `ChangeParentPanel` removal + "Move child to another family", Spec 1's enrollment rows on the family page). Not built here; `POST /students/{id}/change-parent` is left unmodified so the follow-on can wire it later. **Cross-plan contract:** plan 4 (`docs/superpowers/plans/2026-09-10-student-page-single-view.md`, Task 11) gates its `ChangeParentPanel` removal on `grep -rn "Move child to another family" frontend/app/\(admin\)/admin/families` matching. Because this plan does not add that control, plan 4's Task 11 is skipped on the first pass; whichever follow-on builds it on the family page must use the exact label `Move child to another family` (relocating `ChangeParentPanel` from `frontend/app/(admin)/admin/students/[studentId]/StudentEditForm.tsx`) so that gate opens. |
| §7 Rollout step 1+3 (2-PR sequence: list+header first, then redirects+pill+Add-parent move) | Tasks 1-7 + 9 are PR 1 (additive; old pages untouched); Tasks 8, 10, 11 are PR 2. The split is real, not optional: Task 13's parity check gates PR 2. |
| §7 Rollout step 2 (parity script comparing the two endpoints) | Task 13 — **and it carries an open question**: the Families roster is derived from `students.parent_id`, so a parent with no students is in `/admin/users?role=parent` and absent from `/admin/families`. That must be answered before PR 2 ships. |
| §8 Out of scope (second guardian, merging duplicate parents, coach/admin directory changes) | **Deferred per spec** — nothing built toward `co_guardians`; `AdminUsersDirectory` changes are limited to removing the Parents pill. |
| §9 Testing — backend search on child name and email, login-state filter | Task 1 |
| §9 Testing — tenant scoping (parent outside the tenant is absent, **never 403**) | Task 4 (`test_list_families_is_404_for_coach`, `test_list_families_scopes_to_the_caller_academy`) |
| §9 Testing — e2e redirects, invite updates the login badge, parent pointer, QA inventory manifest | Task 12 (both manifest entries; four inventory audit tests) |

## Verification checklist before opening the PR

- [ ] `cd backend && pytest v2/tests -q` — the whole suite, not just touched files (`CustomerFacts` and `FamilyHeader` both gained required-ish fields).
- [ ] `cd backend && lint-imports` — Rule 7 (`composition-is-outermost`) and Rule 4 (interfaces must not import infrastructure/domain directly; `families_routes.py` may only reach into `application/`).
- [ ] `cd backend && ruff check . && ruff format --check .`
- [ ] `cd frontend && pnpm typecheck && pnpm lint`
- [ ] `cd frontend && pnpm exec playwright test admin-shell admin-family-billing admin-families-list --project=chromium-desktop --project=chromium-mobile`
- [ ] `composition/admin.py` still shows 4318 lines (`wc -l backend/v2/composition/admin.py`) — this plan must not touch it.
- [ ] The release note carries the real PR number.
