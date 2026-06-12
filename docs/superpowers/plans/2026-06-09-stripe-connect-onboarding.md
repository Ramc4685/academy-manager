# Stripe Connect Express Onboarding — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each academy admin connect their own Stripe Express account via a "Connect with Stripe" button in Settings → Gateway, so new tenants self-serve without manual backend intervention.

**Architecture:** Backend implements a 3-route OAuth flow: `POST /connect-link` returns the Stripe authorize URL, `GET /callback` (public, state-secured with HMAC-SHA256) exchanges the code and saves the connected account ID to the academy doc, and `DELETE /connect` removes it. Frontend adds Connect / Disconnect buttons and reflects CONNECTED status. State is signed with the webhook secret so the callback is safe without Firebase auth.

**Tech Stack:** Python 3.12, FastAPI, `stripe` SDK (`stripe.OAuth`), Pydantic v2, Motor/MongoDB, Next.js 14 App Router, React Query v5, TypeScript.

---

## Chunk 1: Backend Core

### Task 1: Add `stripe_connect_client_id` to settings and `RealStripeGateway`

**Files:**
- Modify: `backend/v2/shared/config/settings.py` (add field at line 69, fallback at line 115)
- Modify: `backend/v2/contexts/billing/infrastructure/stripe_gateway.py` (update `__init__` at line 17)
- Modify: `backend/v2/main.py` (update `_build_stripe` at line 316)

- [ ] **Step 1: Add the setting**

In `settings.py`, add after line 68 (`stripe_webhook_secret`):

```python
stripe_connect_client_id: str | None = Field(default=None)
```

In `apply_legacy_deploy_fallbacks`, add after the `stripe_webhook_secret` block:
```python
if "V2_STRIPE_CONNECT_CLIENT_ID" not in os.environ:
    self.stripe_connect_client_id = os.environ.get(
        "STRIPE_CONNECT_CLIENT_ID", self.stripe_connect_client_id
    )
```

- [ ] **Step 2: Update `RealStripeGateway.__init__` to accept `connect_client_id`**

In `stripe_gateway.py`, change line 17:
```python
# Before:
def __init__(self, *, api_key: str, webhook_secret: str) -> None:
# After:
def __init__(self, *, api_key: str, webhook_secret: str, connect_client_id: str | None = None) -> None:
```
Add after `self._webhook_secret = webhook_secret`:
```python
self._connect_client_id = connect_client_id
```

- [ ] **Step 3: Update `_build_stripe` in `main.py` to pass the client ID**

Find the `_build_stripe` function. Change the `RealStripeGateway(...)` call to:
```python
return RealStripeGateway(
    api_key=settings.stripe_api_key,
    webhook_secret=settings.stripe_webhook_secret,
    connect_client_id=settings.stripe_connect_client_id,
)
```

- [ ] **Step 4: Verify existing tests still pass**

```bash
cd backend && python -m pytest v2/tests/ -x -q 2>&1 | tail -5
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/v2/shared/config/settings.py backend/v2/contexts/billing/infrastructure/stripe_gateway.py backend/v2/main.py
git commit -m "feat(settings): add stripe_connect_client_id setting and wire to RealStripeGateway"
```

---

### Task 2: Add Connect methods to StripeGateway port and both implementations

**Files:**
- Modify: `backend/v2/contexts/billing/application/ports.py`
- Modify: `backend/v2/contexts/billing/infrastructure/stripe_gateway.py`
- Modify: `backend/v2/contexts/billing/infrastructure/fake_stripe_gateway.py`
- Create: `backend/v2/tests/unit/test_stripe_connect_gateway.py`

- [ ] **Step 1: Write failing test**

Create `backend/v2/tests/unit/test_stripe_connect_gateway.py`:

```python
"""Unit tests for Stripe Connect gateway methods."""
from __future__ import annotations
import pytest
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway


def test_fake_create_connect_link_returns_url():
    gw = FakeStripeGateway()
    url = gw.create_connect_link(redirect_uri="https://example.com/cb", state="abc123")
    assert "abc123" in url


@pytest.mark.anyio
async def test_fake_exchange_connect_code_returns_account_id():
    gw = FakeStripeGateway()
    account_id = await gw.exchange_connect_code("test_code_123")
    assert account_id.startswith("acct_fake_")
```

Run: `cd backend && python -m pytest v2/tests/unit/test_stripe_connect_gateway.py -v`
Expected: FAIL (AttributeError: FakeStripeGateway has no create_connect_link)

- [ ] **Step 2: Add methods to StripeGateway Protocol in `ports.py`**

Find the `StripeGateway` Protocol class. Add at the end of its body:
```python
def create_connect_link(self, *, redirect_uri: str, state: str) -> str:
    """Return Stripe OAuth authorize URL for Express onboarding."""
    ...

async def exchange_connect_code(self, code: str) -> str:
    """Exchange OAuth code for stripe_user_id (connected account ID)."""
    ...
```

- [ ] **Step 3: Implement on `FakeStripeGateway`**

In `fake_stripe_gateway.py`, add to `__init__`:
```python
self.connect_links: list[dict[str, str]] = []
self.connect_codes: list[str] = []
```

Add methods:
```python
def create_connect_link(self, *, redirect_uri: str, state: str) -> str:
    self.connect_links.append({"redirect_uri": redirect_uri, "state": state})
    return f"https://fake-stripe-connect.example.com/oauth?state={state}&redirect_uri={redirect_uri}"

async def exchange_connect_code(self, code: str) -> str:
    self.connect_codes.append(code)
    return f"acct_fake_{code}"
```

- [ ] **Step 4: Implement on `RealStripeGateway`**

Add after `resume_subscription_collection`:

```python
def create_connect_link(self, *, redirect_uri: str, state: str) -> str:
    if not self._connect_client_id:
        raise ValueError("STRIPE_CONNECT_CLIENT_ID is not configured")
    return self._stripe.OAuth.authorize_url(  # type: ignore[attr-defined]
        response_type="code",
        scope="read_write",
        redirect_uri=redirect_uri,
        state=state,
        client_id=self._connect_client_id,
    )

async def exchange_connect_code(self, code: str) -> str:
    def _exchange() -> str:
        response = self._stripe.OAuth.token(  # type: ignore[attr-defined]
            grant_type="authorization_code",
            code=code,
        )
        return str(response["stripe_user_id"])

    return await asyncio.to_thread(_exchange)
```

- [ ] **Step 5: Run tests**

```bash
cd backend && python -m pytest v2/tests/unit/test_stripe_connect_gateway.py -v
```
Expected: 2 PASSED.

- [ ] **Step 6: Commit**

```bash
git add backend/v2/contexts/billing/application/ports.py backend/v2/contexts/billing/infrastructure/stripe_gateway.py backend/v2/contexts/billing/infrastructure/fake_stripe_gateway.py backend/v2/tests/unit/test_stripe_connect_gateway.py
git commit -m "feat(billing): add create_connect_link and exchange_connect_code to StripeGateway"
```

---

### Task 3: Write `stripe_connect.py` use cases with HMAC state

**Files:**
- Create: `backend/v2/contexts/identity/application/use_cases/stripe_connect.py`
- Create: `backend/v2/tests/unit/test_stripe_connect_use_cases.py`

- [ ] **Step 1: Write failing tests**

Create `backend/v2/tests/unit/test_stripe_connect_use_cases.py`:

```python
"""Unit tests for Stripe Connect use cases."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.v2.contexts.identity.application.use_cases.stripe_connect import (
    StartStripeConnectUseCase,
    CompleteStripeConnectUseCase,
    DisconnectStripeUseCase,
    _build_state,
    _verify_state,
)

SECRET = "test-webhook-secret"


def test_build_and_verify_state_roundtrip():
    state = _build_state("acad-123", SECRET)
    academy_id = _verify_state(state, SECRET)
    assert academy_id == "acad-123"


def test_verify_state_rejects_tampered_signature():
    state = _build_state("acad-123", SECRET)
    tampered = state[:-4] + "XXXX"
    with pytest.raises(ValueError):
        _verify_state(tampered, SECRET)


def test_verify_state_rejects_wrong_secret():
    state = _build_state("acad-123", SECRET)
    with pytest.raises(ValueError):
        _verify_state(state, "wrong-secret")


@pytest.mark.anyio
async def test_start_returns_url():
    gw = MagicMock()
    gw.create_connect_link.return_value = "https://connect.stripe.com/oauth?state=x"
    uc = StartStripeConnectUseCase(
        gateway=gw,
        webhook_secret=SECRET,
        redirect_uri="https://api.example.com/cb",
    )
    out = await uc.execute("acad-abc")
    assert out.url.startswith("https://connect.stripe.com")
    gw.create_connect_link.assert_called_once()


@pytest.mark.anyio
async def test_complete_saves_account_id():
    gw = MagicMock()
    gw.exchange_connect_code = AsyncMock(return_value="acct_real_123")
    repo = MagicMock()
    repo.update_by_id = AsyncMock(return_value=None)

    state = _build_state("acad-xyz", SECRET)
    uc = CompleteStripeConnectUseCase(gateway=gw, repo=repo, webhook_secret=SECRET)
    academy_id = await uc.execute(code="auth_code_abc", state=state)

    assert academy_id == "acad-xyz"
    repo.update_by_id.assert_called_once_with("acad-xyz", {"stripe_account_id": "acct_real_123"})


@pytest.mark.anyio
async def test_complete_rejects_bad_state():
    gw = MagicMock()
    repo = MagicMock()
    uc = CompleteStripeConnectUseCase(gateway=gw, repo=repo, webhook_secret=SECRET)
    with pytest.raises(ValueError):
        await uc.execute(code="auth_code", state="totally-invalid-state")


@pytest.mark.anyio
async def test_disconnect_clears_account_id():
    repo = MagicMock()
    repo.update_by_id = AsyncMock(return_value=None)
    uc = DisconnectStripeUseCase(repo=repo)
    await uc.execute("acad-abc")
    repo.update_by_id.assert_called_once_with("acad-abc", {"stripe_account_id": None})
```

Run: `cd backend && python -m pytest v2/tests/unit/test_stripe_connect_use_cases.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 2: Implement `stripe_connect.py`**

Create `backend/v2/contexts/identity/application/use_cases/stripe_connect.py`:

```python
"""Stripe Connect Express onboarding use cases."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Any, Protocol


class _AcademyRepo(Protocol):
    async def update_by_id(
        self, academy_id: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None: ...


class _StripeConnectGateway(Protocol):
    def create_connect_link(self, *, redirect_uri: str, state: str) -> str: ...
    async def exchange_connect_code(self, code: str) -> str: ...


def _build_state(academy_id: str, secret: str) -> str:
    nonce = secrets.token_hex(16)
    payload = f"{academy_id}:{nonce}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _verify_state(state: str, secret: str) -> str:
    """Return academy_id or raise ValueError."""
    try:
        padded = state + "=" * (-len(state) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        parts = raw.rsplit(":", 2)
        if len(parts) != 3:
            raise ValueError("wrong part count")
        academy_id, nonce, sig = parts
        payload = f"{academy_id}:{nonce}"
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise ValueError("bad signature")
        return academy_id
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"invalid state: {exc}") from exc


@dataclass(frozen=True)
class StartStripeConnectOutput:
    url: str


class StartStripeConnectUseCase:
    def __init__(
        self,
        *,
        gateway: _StripeConnectGateway,
        webhook_secret: str,
        redirect_uri: str,
    ) -> None:
        self._gateway = gateway
        self._secret = webhook_secret
        self._redirect_uri = redirect_uri

    async def execute(self, academy_id: str) -> StartStripeConnectOutput:
        state = _build_state(academy_id, self._secret)
        url = self._gateway.create_connect_link(
            redirect_uri=self._redirect_uri,
            state=state,
        )
        return StartStripeConnectOutput(url=url)


class CompleteStripeConnectUseCase:
    def __init__(
        self,
        *,
        gateway: _StripeConnectGateway,
        repo: _AcademyRepo,
        webhook_secret: str,
    ) -> None:
        self._gateway = gateway
        self._repo = repo
        self._secret = webhook_secret

    async def execute(self, *, code: str, state: str) -> str:
        """Returns academy_id. Raises ValueError if state is invalid."""
        academy_id = _verify_state(state, self._secret)
        stripe_account_id = await self._gateway.exchange_connect_code(code)
        await self._repo.update_by_id(academy_id, {"stripe_account_id": stripe_account_id})
        return academy_id


class DisconnectStripeUseCase:
    def __init__(self, *, repo: _AcademyRepo) -> None:
        self._repo = repo

    async def execute(self, academy_id: str) -> None:
        await self._repo.update_by_id(academy_id, {"stripe_account_id": None})
```

- [ ] **Step 3: Run tests**

```bash
cd backend && python -m pytest v2/tests/unit/test_stripe_connect_use_cases.py -v
```
Expected: 7 PASSED.

- [ ] **Step 4: Commit**

```bash
git add backend/v2/contexts/identity/application/use_cases/stripe_connect.py backend/v2/tests/unit/test_stripe_connect_use_cases.py
git commit -m "feat(identity): add Stripe Connect use cases with HMAC state signing"
```

---

## Chunk 2: Backend Routes

### Task 4: Views, deps wiring, routes, composition

**Files:**
- Modify: `backend/v2/interfaces/admin/views.py` (add `AdminGatewayConnectLinkView` after `AdminGatewayView`)
- Modify: `backend/v2/interfaces/admin/deps.py` (add 3 use case fields to `AdminUseCases`)
- Modify: `backend/v2/interfaces/admin/academy_routes.py` (add 3 new routes)
- Modify: `backend/v2/composition/admin.py` (wire up 3 new use cases)
- Create: `backend/v2/tests/interface/test_admin_gateway_connect.py`

- [ ] **Step 1: Add view model to `views.py`**

After the `AdminGatewayView` class, add:
```python
class AdminGatewayConnectLinkView(BaseModel):
    url: str
```

- [ ] **Step 2: Add use case fields to `AdminUseCases` in `deps.py`**

Add these imports near the other identity use case imports:
```python
from backend.v2.contexts.identity.application.use_cases.stripe_connect import (
    CompleteStripeConnectUseCase,
    DisconnectStripeUseCase,
    StartStripeConnectUseCase,
)
```

In the `AdminUseCases` dataclass, add after `get_academy_gateway_use_case`:
```python
start_stripe_connect_use_case: StartStripeConnectUseCase
complete_stripe_connect_use_case: CompleteStripeConnectUseCase
disconnect_stripe_use_case: DisconnectStripeUseCase
```

- [ ] **Step 3: Wire use cases in `composition/admin.py`**

Add imports at the top:
```python
from backend.v2.contexts.identity.application.use_cases.stripe_connect import (
    CompleteStripeConnectUseCase,
    DisconnectStripeUseCase,
    StartStripeConnectUseCase,
)
```

In `compose_admin`, after `get_academy_gateway_use_case = ...`:
```python
_stripe_callback_uri = (
    "https://api.academy.courtmastr.com/api/v2/admin/academy/gateway/stripe/callback"
)
start_stripe_connect_use_case = StartStripeConnectUseCase(
    gateway=stripe_gw,
    webhook_secret=settings.stripe_webhook_secret or "",
    redirect_uri=_stripe_callback_uri,
)
complete_stripe_connect_use_case = CompleteStripeConnectUseCase(
    gateway=stripe_gw,
    repo=academy_repo,
    webhook_secret=settings.stripe_webhook_secret or "",
)
disconnect_stripe_use_case = DisconnectStripeUseCase(repo=academy_repo)
```

Add to the `AdminUseCases(...)` constructor:
```python
start_stripe_connect_use_case=start_stripe_connect_use_case,
complete_stripe_connect_use_case=complete_stripe_connect_use_case,
disconnect_stripe_use_case=disconnect_stripe_use_case,
```

- [ ] **Step 4: Add 3 routes to `academy_routes.py`**

Add these imports if not present:
```python
from fastapi import Query
from fastapi.responses import RedirectResponse
from backend.v2.interfaces.admin.views import AdminGatewayConnectLinkView
from backend.v2.shared.config import get_settings
```

Add after the existing `get_academy_gateway` route:

```python
@router.post("/academy/gateway/stripe/connect-link", response_model=AdminGatewayConnectLinkView)
async def start_stripe_connect(
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminGatewayConnectLinkView:
    out = await use_cases.start_stripe_connect_use_case.execute(claims.academy_id)
    return AdminGatewayConnectLinkView(url=out.url)


@router.get("/academy/gateway/stripe/callback")
async def stripe_connect_callback(
    code: str = Query(),
    state: str = Query(),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> RedirectResponse:
    settings = get_settings()
    try:
        await use_cases.complete_stripe_connect_use_case.execute(code=code, state=state)
    except ValueError:
        return RedirectResponse(
            url=f"{settings.frontend_url}/admin/settings?panel=gateway&stripe=error",
            status_code=302,
        )
    return RedirectResponse(
        url=f"{settings.frontend_url}/admin/settings?panel=gateway&stripe=connected",
        status_code=302,
    )


@router.delete("/academy/gateway/stripe/connect", status_code=204)
async def disconnect_stripe(
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> None:
    await use_cases.disconnect_stripe_use_case.execute(claims.academy_id)
```

> **Note:** The callback route has no Firebase auth — the HMAC-signed state is self-authenticating. `get_admin_use_cases` reads from `request.app.state.admin` and is always available.

- [ ] **Step 5: Verify app boots**

```bash
cd backend && python -c "from backend.v2.main import app; print('boot ok')"
```
Expected: `boot ok`

- [ ] **Step 6: Write interface tests**

Create `backend/v2/tests/interface/test_admin_gateway_connect.py`:

```python
"""Admin Stripe Connect route tests."""
from __future__ import annotations
import pytest
from urllib.parse import urlparse, parse_qs


def test_connect_link_returns_url(admin_client):
    r = admin_client.post("/api/v2/admin/academy/gateway/stripe/connect-link")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "url" in body
    assert body["url"].startswith("https://")


def test_connect_link_wrong_persona_404(coach_on_admin_client):
    r = coach_on_admin_client.post("/api/v2/admin/academy/gateway/stripe/connect-link")
    assert r.status_code == 404


def test_callback_bad_state_redirects_to_error(client):
    r = client.get(
        "/api/v2/admin/academy/gateway/stripe/callback",
        params={"code": "test_code", "state": "invalid-state"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "stripe=error" in r.headers["location"]


def test_callback_valid_state_redirects_to_success(admin_client, client):
    link_r = admin_client.post("/api/v2/admin/academy/gateway/stripe/connect-link")
    assert link_r.status_code == 200
    url = link_r.json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]

    r = client.get(
        "/api/v2/admin/academy/gateway/stripe/callback",
        params={"code": "test_auth_code", "state": state},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "stripe=connected" in r.headers["location"]


def test_disconnect_returns_204(admin_client):
    r = admin_client.delete("/api/v2/admin/academy/gateway/stripe/connect")
    assert r.status_code == 204


def test_disconnect_wrong_persona_404(coach_on_admin_client):
    r = coach_on_admin_client.delete("/api/v2/admin/academy/gateway/stripe/connect")
    assert r.status_code == 404


def test_get_gateway_shows_connected_after_connect(admin_client, client):
    link_r = admin_client.post("/api/v2/admin/academy/gateway/stripe/connect-link")
    url = link_r.json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    client.get(
        "/api/v2/admin/academy/gateway/stripe/callback",
        params={"code": "auth_code_xyz", "state": state},
        follow_redirects=False,
    )
    r = admin_client.get("/api/v2/admin/academy/gateway")
    assert r.status_code == 200
    body = r.json()
    assert body["stripe_connected"] is True
    assert "acct_fake_" in (body["stripe_account_id_masked"] or "")
```

Run: `cd backend && python -m pytest v2/tests/interface/test_admin_gateway_connect.py -v`
Expected: all PASSED.

- [ ] **Step 7: Commit**

```bash
git add \
  backend/v2/interfaces/admin/views.py \
  backend/v2/interfaces/admin/deps.py \
  backend/v2/interfaces/admin/academy_routes.py \
  backend/v2/composition/admin.py \
  backend/v2/tests/interface/test_admin_gateway_connect.py
git commit -m "feat(admin): add Stripe Connect OAuth routes (connect-link, callback, disconnect)"
```

---

## Chunk 3: Frontend

### Task 5: Update API client and `GatewayPanel`

**Files:**
- Modify: `frontend/lib/api/admin.ts` (add type + 2 new functions after `getAdminGateway`)
- Modify: `frontend/components/admin/settings/gateway-panel.tsx` (full rewrite)

- [ ] **Step 1: Add type and API functions to `admin.ts`**

Find `AdminGatewayView` interface and add after it:
```typescript
export interface AdminGatewayConnectLinkView {
  url: string;
}
```

Find `getAdminGateway` and add after it:
```typescript
export function startStripeConnect(): Promise<AdminGatewayConnectLinkView> {
  return apiFetch<AdminGatewayConnectLinkView>(
    "/admin/academy/gateway/stripe/connect-link",
    { method: "POST" },
  );
}

export function disconnectStripe(): Promise<void> {
  return apiFetch<void>("/admin/academy/gateway/stripe/connect", {
    method: "DELETE",
  });
}
```

- [ ] **Step 2: Rewrite `gateway-panel.tsx`**

Replace the full file contents with:

```tsx
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  disconnectStripe,
  getAdminGateway,
  startStripeConnect,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Overline } from "@/components/ds/typography";

export function GatewayPanel() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const [connectError, setConnectError] = useState<string | null>(null);

  const stripeParam = searchParams.get("stripe");
  const justConnected = stripeParam === "connected";
  const connectFailed = stripeParam === "error";

  const query = useQuery({
    queryKey: queryKeys.admin.gateway(),
    queryFn: getAdminGateway,
  });
  const gateway = query.data;

  const connectMutation = useMutation({
    mutationFn: startStripeConnect,
    onSuccess: (data) => {
      window.location.href = data.url;
    },
    onError: () => {
      setConnectError("Could not start Stripe Connect. Try again.");
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: disconnectStripe,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.gateway() });
      const params = new URLSearchParams(searchParams.toString());
      params.delete("stripe");
      router.replace(`?${params.toString()}`);
    },
    onError: () => {
      setConnectError("Could not disconnect Stripe account. Try again.");
    },
  });

  return (
    <section data-testid="admin-settings-gateway" className="space-y-4">
      <Card p={24} className="max-w-3xl">
        <Overline>Gateway</Overline>

        {query.isLoading ? (
          <div className="mt-5 h-24 animate-pulse rounded-md bg-rally-paper" />
        ) : query.isError ? (
          <p role="alert" className="mt-4 text-sm font-medium text-red-700">
            Could not load gateway status.
          </p>
        ) : (
          <div className="mt-5 space-y-5">
            {justConnected && (
              <p className="rounded-md bg-green-50 px-3 py-2 text-sm font-medium text-green-700">
                Stripe account connected successfully.
              </p>
            )}
            {connectFailed && (
              <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
                Stripe Connect was not completed. Please try again.
              </p>
            )}
            {connectError && (
              <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
                {connectError}
              </p>
            )}

            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="font-display text-[18px] font-semibold text-rally-ink">
                  Stripe Connect
                </p>
                <p className="mt-1 text-sm text-rally-muted">
                  {gateway?.stripe_connected
                    ? `Connected — ${gateway.stripe_account_id_masked ?? "account linked"}`
                    : "Connect your Stripe account to enable card payments for parents."}
                </p>
              </div>
              <Chip
                variant={gateway?.stripe_connected ? "enrolled" : "waitlist"}
                label={gateway?.stripe_connected ? "CONNECTED" : "NOT CONNECTED"}
              />
            </div>

            {gateway?.stripe_connected ? (
              <button
                onClick={() => disconnectMutation.mutate()}
                disabled={disconnectMutation.isPending}
                className="rounded-md border border-red-200 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
              >
                {disconnectMutation.isPending ? "Disconnecting…" : "Disconnect Stripe"}
              </button>
            ) : (
              <button
                onClick={() => {
                  setConnectError(null);
                  connectMutation.mutate();
                }}
                disabled={connectMutation.isPending}
                className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50"
              >
                {connectMutation.isPending ? "Redirecting…" : "Connect with Stripe"}
              </button>
            )}

            <div>
              <p className="mb-2 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Manual methods
              </p>
              <div className="flex flex-wrap gap-2">
                {(gateway?.manual_methods ?? []).map((method) => (
                  <Chip key={method} variant="manual" label={method.toUpperCase()} />
                ))}
              </div>
            </div>
          </div>
        )}
      </Card>
    </section>
  );
}
```

- [ ] **Step 3: Check TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -i "gateway\|stripe\|error" | head -20
```
Expected: no errors for these files.

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/api/admin.ts frontend/components/admin/settings/gateway-panel.tsx
git commit -m "feat(frontend): Stripe Connect button and disconnect in gateway settings panel"
```

---

## Final: Fly Secret + Smoke Test

- [ ] **Step 1: Add `STRIPE_CONNECT_CLIENT_ID` to Fly secrets**

```bash
fly secrets set STRIPE_CONNECT_CLIENT_ID=ca_XXXX --app courtmastr-academy-api
```
Replace `ca_XXXX` with the client ID from Stripe Dashboard → Connect → Settings.

- [ ] **Step 2: Deploy**

```bash
fly deploy --app courtmastr-academy-api
```

- [ ] **Step 3: Smoke test**

1. Log in to `blno-academy.courtmastr.com/admin/settings?panel=gateway`
2. Confirm BLNO shows **CONNECTED** (their `stripe_account_id` is already in the DB)
3. Log into a second test tenant → Settings → Gateway → **Connect with Stripe**
4. Complete Stripe onboarding → confirm redirect back with `?stripe=connected`
5. Confirm gateway shows **CONNECTED** for that tenant
