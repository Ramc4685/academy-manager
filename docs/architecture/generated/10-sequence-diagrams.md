# 10 — Sequence Diagrams

**Confidence: Medium–High** (transport/auth and billing flows High; some intermediate
use-case steps condensed — see per-diagram notes)

All diagrams below are grounded in the routes and use cases identified in
[04-backend-architecture.md](04-backend-architecture.md), [07-auth-identity-flow.md](07-auth-identity-flow.md),
and [08-billing-stripe-flow.md](08-billing-stripe-flow.md).

## 1. Admin login

```mermaid
sequenceDiagram
    autonumber
    participant A as Admin browser
    participant FB as Firebase Auth
    participant FE as Worker (UI + proxy)
    participant BE as Backend /api/v2
    A->>FB: signInWithEmail / Google
    FB-->>A: ID token (email_verified)
    A->>FE: GET /api/v2/me (Bearer token via proxy)
    FE->>BE: forward + Authorization
    BE->>BE: TenancyMiddleware resolves tenant + LoadAuthClaims
    BE-->>FE: {user_id, academy_id, roles:[admin]}
    FE-->>A: homeForRoles -> redirect /admin
    A->>FE: GET /admin/* (usePersonaAuth("admin"))
```

Note: `/me` returns roles; client `homeForRoles` routes admins to `/admin`. Backend
`require_persona("admin")` guards admin routes.

## 2. Parent registration

```mermaid
sequenceDiagram
    autonumber
    participant P as Parent browser
    participant FB as Firebase Auth
    participant BE as Backend
    participant DB as MongoDB
    P->>FB: create account (email/password or Google)
    FB-->>P: ID token
    P->>FB: verify email (password provider)
    P->>BE: POST /api/v2/register/parent (Bearer token)
    BE->>BE: RegisterPublicParent (require verified email)
    BE->>DB: create users + academy_membership(parent)
    alt failure mid-flight
        BE->>FB: delete Firebase user (rollback)
    end
    BE-->>P: parent created
    P->>BE: submit onboarding application (child, session, waiver)
    BE->>DB: onboarding_applications(status=pending)
```

Note: registration route is public (no tenant requirement). Admin later reviews/approves
the application (creates `Student` + `Enrollment`).

## 3. Parent payment / autopay

```mermaid
sequenceDiagram
    autonumber
    participant P as Parent
    participant BE as Parent BFF
    participant ST as Stripe
    participant DB as MongoDB
    P->>BE: POST /parent/checkout/start (application_id)
    BE->>ST: create_checkout_session (metadata)
    ST-->>BE: session_id + redirect_url
    BE->>DB: Payment(status=pending)
    BE-->>P: redirect_url
    P->>ST: pay
    ST-->>BE: webhook checkout.session.completed
    BE->>DB: record ledger_payment + allocate (idempotent)
    Note over P,BE: autopay variant -> create_subscription_checkout_session,<br/>Subscription(incomplete) -> active on webhook
```

## 4. Stripe webhook processing

```mermaid
sequenceDiagram
    autonumber
    participant ST as Stripe
    participant WR as POST /parent/webhooks/stripe
    participant Q as stripe_webhook_events
    participant JOB as Scheduler (60s)
    participant H as HandleWebhookEvent
    participant L as Ledger (Mongo)
    ST->>WR: event + signature
    WR->>WR: verify signature
    WR->>Q: store_received
    WR-->>ST: 200
    JOB->>H: process_next (claim oldest)
    H->>H: validate livemode + academy_id
    alt mismatch or already paid
        H->>Q: mark_quarantined
    else ok
        H->>L: record_payment + allocate
        H->>Q: mark processed
    end
```

## 5. Coach session attendance

```mermaid
sequenceDiagram
    autonumber
    participant C as Coach (mobile)
    participant BE as Coach BFF
    participant DB as MongoDB
    C->>BE: GET /coach/today?date=YYYY-MM-DD
    BE->>DB: sessions + occurrences for coach
    BE-->>C: today's agenda + roster
    C->>BE: POST /coach/sessions/{id}/attendance (per-student status)
    BE->>DB: upsert attendance (occurrence-based)
    C->>BE: POST /coach/sessions/{id}/attendance (coach presence)
    BE->>DB: coach_attendance (unique academy+occurrence+coach)
    BE-->>C: saved (drives payroll payable occurrences)
```

Note: coach app supports offline auto-sync (frontend `startAutoSync`).

## 6. Monthly invoice generation

```mermaid
sequenceDiagram
    autonumber
    participant A as Admin
    participant BE as Admin BFF
    participant R as MongoPaymentRepository
    participant DB as MongoDB
    A->>BE: POST /admin/payments/generate-monthly {period}
    BE->>R: generate_monthly_payments(YYYY-MM)
    loop each active/paused enrollment
        R->>R: skip existing / autopay / paused / no-charge
        R->>R: compute charge (proration or full)
        R->>DB: insert billing_invoice_keys (unique)
        alt duplicate key
            R->>DB: recover orphan invoice (idempotent)
        else new
            R->>DB: create LedgerInvoice
        end
    end
    R-->>A: created / skipped counts
```

## Sources inspected

- Routes & use cases per docs 04 / 07 / 08 and their cited files.

## Gaps / Unknowns

- Registration approval → student/enrollment promotion steps are summarized; exact admin-review use case (`admin_registration_review.py`) internals not expanded.
- Monthly generation trigger is admin-initiated; scheduled trigger "needs verification".
