# CourtMastr Academy Manager

**The all-in-one operating system for sports academies.**
Run sessions, enrollments, attendance, billing, coach payouts, and parent
communication from one place — on the web, on the court, and on your phone.

> Proprietary software. Copyright (c) 2024-2026 Marvy Labs. All rights reserved.
> Access to this repository does **not** grant a license to use, copy, or
> redistribute the software. See [LICENSE](LICENSE).

---

## Product

CourtMastr Academy Manager is a hosted SaaS platform for badminton, tennis,
and racquet-sports academies. It replaces the spreadsheets, group chats, and
manual receipts that academies usually run on with a single, role-aware
system for owners, coaches, and parents.

### What it does

| Area | Capabilities |
|---|---|
| **Scheduling** | Recurring sessions, court allocation, coach assignment, calendar views, conflict detection |
| **Enrollments** | Programs, batches, waitlists, trial classes, capacity rules, prorated joins |
| **Attendance** | Coach mobile check-in, makeups, absentee tracking, retention reports |
| **Billing** | Stripe-backed invoices, monthly tuition, one-off charges, refunds, failed-payment recovery |
| **Coach Payouts** | Per-session rates, hours worked, automated payout statements |
| **Parents** | Self-serve portal, payment history, child progress, push/email notifications |
| **Admin** | Multi-academy ready, role-based access, audit logs, exportable reports |
| **Auth** | Firebase Authentication — Google sign-in, email/password, server-enforced email verification |

### Who it's for

- **Academy owners** who want a clean P&L without chasing receipts.
- **Head coaches** who need a single source of truth for who shows up,
  who paid, and who's owed.
- **Parents** who want one app for schedules, payments, and progress instead
  of three group chats.

### Live Service

- **Web app:** <https://academy.courtmastr.com>
- **API:** <https://api.academy.courtmastr.com>
- **Status / health:** `GET https://api.academy.courtmastr.com/api/v2/healthz`

---

## Architecture

CourtMastr Academy Manager runs as a managed, multi-region cloud service.
The codebase in this repository powers the hosted product — it is not
intended for self-hosting.

```
┌────────────────────────────────────────────────────────────────────┐
│  Browsers / PWA   ──►  Cloudflare Edge + Next.js Worker            │
│                              │                                     │
│                              ▼                                     │
│  Frontend (Next.js App Router, PWA)                                │
│                              │                                     │
│                              ▼                                     │
│  Backend API (FastAPI, Python 3.12) on Fly.io — region `ord`       │
│        │                │                │              │          │
│        ▼                ▼                ▼              ▼          │
│  MongoDB Atlas    Firebase Auth      Stripe        Resend Email    │
└────────────────────────────────────────────────────────────────────┘
```

### Production stack

| Layer | Technology | Where it runs |
|---|---|---|
| Web | Next.js 15 / React 19 (App Router, PWA) | Cloudflare Workers project `academy-next` |
| API | FastAPI + Uvicorn (Python 3.12) | Fly.io app `courtmastr-academy-api` (region `ord`) |
| Database | MongoDB (Atlas) | Managed |
| Auth / identity | Firebase Authentication | Project `academy-courtmastr` |
| Payments | Stripe (live mode) | Webhook at `/api/v2/parent/webhooks/stripe` |
| Transactional email | Resend | Verified `courtmastr.com` sender domain |
| Scheduler timezone | `America/Chicago` | Set on backend |

The `academy-next` Cloudflare Worker owns `academy.courtmastr.com/*` directly
through a Worker Route.
The legacy CRA app has been removed from the canonical source tree.

### Deployment pipeline

`.github/workflows/production.yml` is the single GitHub Actions control plane:

1. **Validate** — backend compile/tests, v2 DDD boundary checks, and Next.js
   typecheck/lint/build/E2E.
2. **Production approval** — manual gate (GitHub `production` environment).
3. **Backend deploy** — `flyctl deploy --remote-only --app courtmastr-academy-api`.
4. **Frontend deploy** — publish `frontend/` to the Next/Cloudflare Worker.
5. **Smoke** — `scripts/smoke/production_smoke.sh` against the live URLs.

See [DEPLOYMENT.md](DEPLOYMENT.md) for the operator runbook —
environment variables, secret rotation, Stripe webhook configuration,
email verification, backups, and rollback procedure.

---

## Security & Compliance

- **HTTPS-only.** Strict transport, secure cookies, force-https at the edge.
- **HttpOnly cookies + Firebase ID tokens.** Server-side token revocation
  takes effect on the next request — disabling a user in the Firebase
  console immediately revokes access.
- **Email verification enforced.** Password-provider tokens must be
  email-verified server-side at every authenticated request.
- **Explicit CORS allow-list.** No wildcard origins.
- **Atomic invite acceptance.** Mid-flight registration failures roll back
  the Firebase user via the Admin SDK.
- **Local/test email is hard-blocked** — production email requires
  `APP_ENV=production`, a verified Resend sender, and an explicit enable
  flag, so non-prod environments cannot accidentally email real parents.
- **Backups.** Managed MongoDB snapshots + documented restore drill
  cadence in `DEPLOYMENT.md`.
- **Audit logs.** Authentication, admin role changes, and payment events
  are recorded for review.

---

## Pricing & Access

CourtMastr Academy Manager is sold as a subscription. Pricing scales by
active student count and academy locations. Onboarding includes data import
from your existing spreadsheets and CRM.

- **Sales / demos:** ramchand4685@gmail.com
- **Support:** ramchand4685@gmail.com
- **Security disclosure:** ramchand4685@gmail.com (subject line:
  `SECURITY DISCLOSURE`)

Parent self-registration is open through Firebase Auth and the v2 parent
onboarding flow. New academy tenants are still onboarded by the CourtMastr
team.

---

## Repository

This repository is the production source tree for the hosted service.
It is **not** an open-source project.

- **No external contributions** are accepted via pull request without a
  signed contributor agreement.
- **No license** to use, fork, mirror, redistribute, host, or train models
  on this code is granted by virtue of its visibility. See
  [LICENSE](LICENSE).
- **Issues and security reports** from authorized reviewers should be sent
  privately to the contact above.

### Layout (for internal contributors)

```
backend/        FastAPI service, deployed to Fly.io
backend/v2/     Clean-architecture backend (in-process during Phase 0)
frontend/       Next.js 15 app (single frontend target, PWA)
edge/           Retired Cloudflare Worker router kept for historical reference
docs/           ADRs, tickets, security matrix, event rules
scripts/        Smoke tests, importers, ops utilities
```

Internal engineering notes live in [AGENTS.md](AGENTS.md) and
[`docs/`](docs/). Production operations and rollout phases are tracked in
[DEPLOYMENT.md](DEPLOYMENT.md) and `docs/tickets/`.

### Trademarks

"Academy Manager", "CourtMastr", the CourtMastr logo, and related product
names or marks are trademarks or service marks of Marvy Labs. All other marks
belong to their respective owners.
