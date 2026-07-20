# MT4 — Extend the structural tenancy test to composition and infrastructure

Status: TODO
Size: S · Depends on: C4 (do after — the tightened test should pass when added, not carry new exemptions) · Tracker: ../TRACKER.md

## Problem

A structural guard against raw Mongo access to tenant-owned collections **already exists** — `backend/v2/tests/test_no_raw_tenant_mongo_access.py` — but it has two blanket holes that neutralize it exactly where the risk lives:

1. `_is_approved_path` exempts **all** of `contexts/*/infrastructure/` unconditionally (any path with both `contexts` and `infrastructure` parts) — a repo class there can do `db["students"].find(...)` without tenant scoping and the test stays green.
2. `APPROVED_COMPOSITION_EXCEPTIONS` exempts `composition/admin.py`, `composition/coach.py`, `composition/parent.py` wholesale ("Transitional ... while Agent A/B replace default-academy wiring") plus `interfaces/admin/progress_routes.py`. The composition root is where the audit found raw tenant queries (audit Critical #4 / C4).

## Current behavior (verified 2026-07-20)

- Test location: `backend/v2/tests/test_no_raw_tenant_mongo_access.py` (v2/tests root, as suspected).
- Mechanism: AST walk over every `*.py` under `V2_ROOT` (`rglob`), `_RawMongoAccessVisitor` flags `<db>["<name>"].<method>` where `<name>` ∈ `TENANT_OWNED_COLLECTIONS` (~50 names incl. skill-pathway collections) and `<method>` ∈ `MONGO_METHODS` (find/insert/update/delete/aggregate/…). Also tracks assigned aliases (`visit_Assign`). Self-test `test_raw_mongo_guard_reports_tenant_owned_direct_access` proves detection.
- Companion tests already ratchet specific functions: `test_hardened_admin_composition_paths_use_request_tenant_not_default` (8 admin closures must use `current_academy_id` and not `settings.default_academy_id`) and `test_parent_composition_requires_explicit_academy_id` (`compose_parent*` must take `academy_id: str` + `_require_academy_id`).
- `TenantScopedRepository` (`backend/v2/shared/tenancy/repository.py`): subclasses set `collection_name`; helpers `_find_one/_find_many/_insert_one/...` inject `academy_id` from the `current_academy_id()` ContextVar; `_find_many_in_collection` covers cross-collection reads. `shared/tenancy/repository.py` itself is exempted by path (correct — it's the enforcement point).
- **List discrepancy to resolve:** the test's `TENANT_OWNED_COLLECTIONS` currently *includes* `users`, `academies`, `academy_memberships` — but these are global/cross-tenant (a user spans academies; `academies` is the tenant registry; memberships map users↔academies). Treating them as tenant-owned forces false exemptions. Global collections that must be exempt from the tenant-scoping requirement: `users`, `academies`, `academy_memberships`, tenant lifecycle/bootstrap collections (grep `interfaces/platform/` + onboarding for names, e.g. `academy_domains`, `onboarding_applications` — decide per collection: `academy_domains` docs carry `academy_id` but are looked up globally by hostname), and Stripe webhook dedup (grep `shared` + billing infrastructure for the event-dedup collection name, e.g. `stripe_events`/`webhook_events` — check `grep -rn "stripe.*event" backend/v2 --include='*.py' -l | grep -v tests` for the store).

## Proposed change

Tighten rather than rewrite:

1. Split the collection list into `TENANT_OWNED_COLLECTIONS` (must be tenant-scoped) and `GLOBAL_COLLECTIONS` (documented, allowed raw): move `users`, `academies`, `academy_memberships`, lifecycle/bootstrap, and stripe-dedup names into the global list with a one-line rationale each.
2. Replace the blanket `contexts/*/infrastructure` exemption with a real rule: a class in infrastructure touching a tenant-owned collection must either (a) extend `TenantScopedRepository` (AST: any class whose bases include the name `TenantScopedRepository` is trusted — its raw `self.collection.<method>` calls are assumed scoped via `_scoped`; still flag `db["..."]` subscripts for *other* tenant-owned collections inside it unless the method source references `current_academy_id` or an explicit `academy_id` parameter), or (b) for non-subclass code, the enclosing function must reference `current_academy_id(` or take/use an explicit `academy_id` kwarg in the query dict.
3. Extend the same (b) rule to `composition/` — after C4 lands, delete `composition/parent.py` and `composition/coach.py` from `APPROVED_COMPOSITION_EXCEPTIONS`; keep `composition/admin.py` only until MT1 Phase B/E drains it (shrink to a per-function allowlist if a blanket file entry hides regressions).

## Implementation steps

1. Sequence check: confirm C4 is DONE in ../TRACKER.md. If not, stop — this test must land green with **no new** exemptions.
2. Derive the definitive global-collection list: read `backend/v2/shared/tenancy/repository.py` subclass usages (`grep -rn "TenantScopedRepository" backend/v2/contexts --include='*.py' -l` and each `collection_name`), plus `grep -rn 'db\[' backend/v2 --include='*.py' | grep -v .venv | grep -v tests` for raw accesses; classify every collection name that appears.
3. Edit `backend/v2/tests/test_no_raw_tenant_mongo_access.py`:
   - Add `GLOBAL_COLLECTIONS` frozenset + move the global names out of `TENANT_OWNED_COLLECTIONS`.
   - In `_is_approved_path`, drop the `contexts`+`infrastructure` blanket branch.
   - Extend `_RawMongoAccessVisitor` (or add a second visitor) to record the enclosing `ClassDef`/`FunctionDef` for each access; suppress the violation when: enclosing class bases include `TenantScopedRepository`, OR enclosing function source contains `current_academy_id(`, OR the access's filter dict literally contains an `academy_id` key fed from a parameter (cheap approximation: function has an `academy_id` parameter AND the string `"academy_id"` appears in the call's source segment via `ast.get_source_segment`). Keep the heuristic conservative and documented — false positives get an explicit per-line allowlist entry, never a path blanket.
   - Update `APPROVED_COMPOSITION_EXCEPTIONS` per Proposed change #3; keep `test_composition_exceptions_are_explicit_and_documented` honest (rationale must say what removes the exception, with the tracker id).
   - Add self-tests (mirroring the existing tmp_path pattern): unscoped infra class → flagged; `TenantScopedRepository` subclass → clean; function with `current_academy_id` in the query → clean; global collection raw access → clean.
4. Run the suite; for each new violation surfaced, either fix the call site (preferred, if trivially adding `academy_id` from an existing kwarg) or file it under the explicit allowlist with a tracker reference — do not grow path-level exemptions.

## Files to change

- `backend/v2/tests/test_no_raw_tenant_mongo_access.py` (the whole change, plus self-tests)
- Possibly a handful of `backend/v2/contexts/*/infrastructure/*.py` / `backend/v2/composition/*.py` call sites surfaced by the tightened rule (fix or allowlist)

## Tests & verification

- `cd backend && pytest v2/tests/test_no_raw_tenant_mongo_access.py -v` — all pass, including the new self-tests.
- Full `pytest v2/tests` stays green (2,429 today).
- Mutation check: temporarily add `db["students"].find_one({})` to any infrastructure file → test fails with a `path:line` message; revert.
- Confirm the AGENTS.md promise of a structural tenancy test now matches reality (update AGENTS.md wording if it describes the old scope).

## Risks / rollback

- AST heuristics can over-approve (e.g. `academy_id` parameter present but not used in the query). Accept the approximation — this is a ratchet against *accidental* raw access, not a security boundary; C4's behavioral tests cover correctness.
- Over-flagging legitimately global reads → resolved by the split list, not by exemptions.
- Rollback: single test file revert; no production code path affected.

## PR checklist

- [ ] Release note (per AGENTS.md `docs/release-notes/` — test-only PRs: note "why not applicable" if skipped)
- [ ] TRACKER.md updated
- [ ] Plan Status flipped to DONE
