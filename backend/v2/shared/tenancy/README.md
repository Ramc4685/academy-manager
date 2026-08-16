# shared/tenancy

Tenant scoping per [ADR-0006](../../../../docs/adr/0006-tenant-ready-single-tenant-shipped.md).

## Rule

**Application code never references `academy_id` directly.** Repositories carry it. If a use case wants tenant-scoped data, it calls a repository method — the repository pulls `academy_id` from the ContextVar.

## How it works

1. **Auth middleware** (`shared/auth/`) verifies the Firebase token, builds `AuthClaims`, and calls `set_academy_id(claims.academy_id)` on the ContextVar.
2. **Repositories** extend `TenantScopedRepository`. Every query/insert/update calls `current_academy_id()` from `context.py` and threads it into the Mongo filter/document.
3. **Background tasks** (event handlers, scripts) that need to act on a specific tenant use `with tenant_scope(academy_id): ...`.
4. **Lint** rule (P0-21) bans `academy_id` literals outside this package and `*/infrastructure/`.

## Wrong

```python
# ❌ Application code passing academy_id around.
async def list_sessions_for_coach(academy_id: str, coach_id: str): ...


# ❌ Repository filtering by hand.
await db.sessions.find({"academy_id": "...", "coach_id": ...})


# ❌ Background handler reading academy_id from the event.
@handler(event=AttendanceMarked)
async def something(event):
    repo = SessionRepository(db)
    set_academy_id(event.academy_id)  # wrong — use tenant_scope context manager
    ...
```

## Right

```python
# ✅ Use case takes only domain inputs.
async def list_sessions_for_coach(coach_id: str): ...


# ✅ Repository inherits scoping.
class MongoSessionRepository(TenantScopedRepository):
    collection_name = "sessions"

    async def for_coach_on_date(self, coach_id: str, date: date) -> list[Session]:
        cursor = self._find_many({"coach_id": coach_id, "start_at": ...})
        ...


# ✅ Background handler uses tenant_scope.
@handler(event=AttendanceMarked)
async def some_handler(event):
    with tenant_scope(event.academy_id):
        await some_use_case(event.session_id)
```
