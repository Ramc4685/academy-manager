# Backend and API Rules

Use this file for FastAPI, MongoDB, Firebase Auth, Stripe, Resend, scheduler, backend tests, and v2 BFF/API changes.

---

## Commands

Backend:

```bash
cd backend
source .venv/bin/activate
pytest
uvicorn backend.v2.main:app --host 127.0.0.1 --port 8001 --reload
```

Focused v2 tests:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/interface
pytest v2/tests/contract
```

Run the v2 app directly:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests
uvicorn backend.v2.main:app --reload --port 8001
```

---

## Retired Legacy Source Rules

- Legacy backend routers/services/models are no longer present on main and are
  not the runtime entry point.
- Do not recreate `backend/routers/`, `backend/services/`, or legacy `/api/*`
  handlers for new work.
- Keep any remaining compatibility adapters isolated inside v2 and compatible
  with existing single-academy launch behavior.
- Preserve httpOnly cookie behavior.
- Preserve explicit CORS origins. Do not use wildcard origins with credentials.

---

## v2 Backend Rules

- `backend.v2.main:app` is the production backend runtime.
- Keep `/api/v2/*` paths persona-first: `/api/v2/coach/*`, `/api/v2/parent/*`, `/api/v2/admin/*`.
- Interfaces must call application use cases.
- Application use cases must use ports/protocols.
- Infrastructure owns MongoDB and external providers.
- Tenant or academy scoping must be applied consistently through the v2 repository layer when present.
- Add or update v2 tests alongside each v2 workflow.

---

## MongoDB Rules

- Use Motor/PyMongo APIs already established in the repo.
- Create indexes through startup/index helpers or v2 migrations, not ad hoc shell changes.
- Avoid destructive collection operations unless the user explicitly asks.
- Do not change production data shape without a migration or compatibility plan.
- Integration tests should clean up their own test data when possible.

### Tenant-scope guard test: what a new collection must do

`backend/v2/tests/test_no_raw_tenant_mongo_access.py` is a static ratchet over
every `*.py` under `v2/` (tests and migrations excluded). For a new
per-academy collection:

1. **Declare it on the repository.** `class FooRepo(TenantScopedRepository)`
   with a literal `collection_name = "foos"`. Every write on `self.collection`
   (`update_one`, `update_many`, `replace_one`, `delete_one`, `delete_many`,
   `find_one_and_*`) inside that class is then checked: it must carry a scoping
   signal or the test fails. No registration is needed for this check; the
   only way to opt a collection out is to list it in `GLOBAL_COLLECTIONS` with
   a rationale, and that is for genuinely cross-academy data only (`users`,
   `academies`, ...).
2. **Register it as tenant-owned** in `TENANT_OWNED_COLLECTIONS`. This adds
   the second check: any literal `db["foos"]` access anywhere in `v2/` (a
   report, a composition root, another repo reaching across) must also carry a
   scoping signal.
3. **Scope every write one of two ways:**
   - Request path: use the `TenantScopedRepository` helpers (`_find_one`,
     `_update_one`, `_delete_one`, `_find_one_and_update`, ...) or wrap the
     filter in `self._scoped({...})`. These inject `academy_id` from the tenant
     ContextVar.
   - Scheduler / cron path, where no request set the ContextVar: take
     `academy_id` as an explicit parameter (first, matching `try_claim`) and
     filter on `{"academy_id": academy_id, "<id>": ...}` by hand. This is the
     `coach_digest_sends` / `parent_digest_sends` / `*_notice_sends` pattern
     (issue #880). Never call `_scoped()` from a cron path; it would silently
     depend on a ContextVar nobody set.
4. **Prove it with two tests**, copying the existing ones:
   - A fake-fidelity test: the in-memory fake's `mark_*`/`delete` must ignore a
     call whose `academy_id` does not match the stored row, exactly as Mongo's
     no-match update is a no-op (`test_send_coach_daily_digest.py::
     test_fake_mark_calls_from_another_academy_are_no_ops`).
   - A mongomock test: claim under academy A, mutate with academy B's id and
     A's row id, assert A's row is unchanged
     (`infrastructure/test_digest_send_repo_mongo.py::
     test_mark_from_another_academy_leaves_the_row_untouched`).
5. **Index the scoped lookup.** The per-academy unique index from the
   migration must use a `{"<id>": {"$gt": ""}}` partial filter (never
   `$type`), and if the lookup is on a hot path add it to `HOT_LOOKUPS` in
   `contract/test_partial_index_planner_usability.py` so a real `mongod`
   confirms the planner serves it.

The visitor's own behaviour is pinned by the `tmp_path` tests at the bottom of
the guard file; extend those when you extend the visitor.

---

## Auth Rules

Production auth uses Firebase Authentication plus MongoDB app roles.

- Firebase token verification belongs in backend auth infrastructure.
- JWT/Firebase identity proves who the user is; app role and academy access still come from MongoDB/app records.
- Legacy password endpoints are removed from the v2-only backend; do not add new `/api/auth/*` password routes.
- Email verification is enforced server-side for password-provider Firebase users.
- Never store Firebase service account JSON in git.

---

## Stripe and Billing Rules

- Stripe API and webhook secrets must come from environment variables.
- Webhook handling must be idempotent.
- Do not undo Stripe-paid payments manually unless the code path explicitly supports refund/adjustment semantics.
- Local Stripe webhook testing uses:

```bash
stripe listen --forward-to 127.0.0.1:8001/api/v2/parent/webhooks/stripe
```

---

## Email Rules

- Local/test email delivery is safety-blocked.
- Do not enable live email in local/test.
- Production sending requires `APP_ENV=production` and `EMAIL_DELIVERY_ENABLED=true`.
- Resend failures should be surfaced as provider status, not hidden as successful sends.

---

## API Error Rules

- Return structured errors.
- Keep status codes meaningful.
- Do not leak cross-persona data existence.
- Keep auth failures and permission failures consistent with existing route behavior.

---

## OpenAPI Rules

When v2 OpenAPI generation is present:

- Regenerate frontend types after changing v2 response/request shapes.
- Commit generated types only if the project convention requires it.
- Treat OpenAPI drift as a real contract failure.
