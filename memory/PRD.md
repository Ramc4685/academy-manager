# Badminton Academy Manager — PRD & Roadmap

> **Owner:** BLno Badminton Academy
> **Stack:** FastAPI + MongoDB Motor + JWT (httpOnly cookies) · React 19 + Tailwind + shadcn/ui + Recharts · Stripe SDK · Resend (transactional email)
> **Status:** Phase 1+2+3 shipped. Phase 4 production-readiness baseline partially shipped; remaining Phase 4+ documented below.

---

## 0. Architecture & Conventions

- **Backend:** `/app/backend/server.py` mounts a single `/api`-prefixed router that includes:
  - `auth_routes` — auth, invites, users (admin edit + reset password), public registration
  - `sessions_routes` — sessions CRUD, students, enrollments, transfer, pause-month, parent pause requests, move-log, approve
  - `finance_routes` — payments (incl. undo-paid, generate-monthly, discount), expenses, payout rules, coach payouts (calc/approve/pay + undo)
  - `coaching_routes` — attendance (bulk), lesson plans, progress notes
  - `comms_routes` — `/messages/contacts` (role-scoped), messages, notifications
  - `dashboard_routes` — admin / coach / parent dashboards, CSV reports, audit logs
  - `extras_routes` — dues followup w/ WhatsApp, coach payslip, pending approvals
  - `settings_routes` — academy settings singleton, payout basis per coach
  - `billing_routes` — Stripe Checkout, Stripe Billing subscriptions, Customer Portal, status + webhook
  - `email_routes` — Resend test email, welcome, bulk dues reminders
  - `waitlist_routes` — waitlist listing, parent/admin join, admin conversion to enrollment

- **Roles:** `admin`, `coach`, `parent`, `student` (Phase 4)

- **Cookies:** `access_token` (12h) + `refresh_token` (7d), `httponly secure samesite=none` so they work cross-origin under the preview ingress

- **Frontend layout:** `/app/frontend/src/components/Layout.jsx` renders the dark `slate-900` sidebar with role-specific nav + glassy header with notifications

- **Design system:** Outfit (display) + Manrope (body) fonts, blue (`#2563EB`) + yellow (`#FACC15`) + slate accents, no purple/violet gradients, card-based with subtle hover-lift

- **MongoDB collections:**
  `users, students, coach_profiles, sessions, enrollments, attendance, payments, expenses, payout_rules, coach_payouts, lesson_plans, progress_notes, messages, notifications, invites, audit_logs, move_log, payment_transactions, pause_requests, academy_settings, login_attempts, password_reset_tokens, waitlist, waiver_acceptances`

- **All mutating endpoints write to `audit_logs`** via `auth.log_audit()`.

- **Soft delete:** every core entity has `is_deleted: bool`. Status fields (`pending|active|paid|approved|cancelled|completed|paused`) are also distinct from deletion.

---

## 1. Data Model (current)

### users
`_id, email, password_hash, name, phone, role, status, must_change_password, created_at, updated_at`

### students
`_id, parent_user_id, first_name, last_name, dob, age, skill_level, emergency_contact_{name,phone}, medical_notes, t_shirt_size, previous_experience, waiver_accepted, waiver_date, waiver_accepted_at, waiver_version, waiver_text_hash, waiver_accepted_by, status, is_deleted, created_at`

### sessions
`_id, name, skill_level, age_group, start_date, end_date, days_of_week[], start_time, end_time, location, max_students, reserved_seats, monthly_price, coach_id, status, is_deleted, created_at`

### enrollments
`_id, session_id, student_id, parent_user_id, billing_type ("Standard"|"NoCharge"|"Waived"), approval_status ("pending_payment"|"pending"|"approved"), status, payment_mode ("manual"|"autopay_pending"|"autopay"), subscription_status, stripe_customer_id, stripe_subscription_id, skip_periods[] (YYYY-MM list), session_overrides{period: session_id}, enrolled_at, is_deleted`

### payments
`_id, parent_user_id, student_id, enrollment_id, session_id, period (YYYY-MM), amount, discount, final_amount, status ("pending"|"paid"|"failed"|"partially_refunded"|"refunded"), payment_date, payment_method, marked_by, notes, payment_type, invoice_number, invoice_created_at, stripe_invoice_id, stripe_subscription_id, stripe_payment_intent, refunded_amount, refund_status, refunds[], is_deleted, created_at`

### expenses
`_id, category, description, amount, date, paid_to, status, notes, is_deleted, created_by, created_at`

### payout_rules
`_id, coach_id, rule_type ("revenue_percentage"|"fixed_per_class"|"fixed_monthly"|"per_student"), value, basis ("collected"|"expected"), is_active, created_at`

### coach_payouts
`_id, coach_id, period, session_ids[], rule_type, rule_value, calculated_amount, status ("calculated"|"approved"|"paid"), approved_{by,at}, paid_{by,at}, notes, is_deleted, created_at`

### attendance
`_id, session_id, student_id, enrollment_id, date (YYYY-MM-DD), status ("present"|"absent"|"late"|"excused"|"make_up"), notes, marked_by, marked_at`

### lesson_plans
`_id, session_id, coach_id, date, objective, warmup, skill_drill, game_activity, fitness_activity, homework, coach_notes, created_at`

### progress_notes
`_id, student_id, coach_id, session_id, note, created_at`

### messages
`_id, thread_id, from_user_id, to_user_id, body, read, created_at`

### notifications
`_id, user_id, type, title, message, related_entity, read, created_at`

### move_log
`_id, student_id, enrollment_id, from_session_id, to_session_id, effective_month, permanent, note, moved_by, moved_at`

### academy_settings (singleton, _id="singleton")
`name, zelle_handle, reminder_template, currency, default_capacity, beginner_price, intermediate_price, advanced_price`

### payment_transactions (Stripe trail)
`_id, session_id, payment_id, enrollment_id, type, user_id, user_email, amount, currency, payment_status, status, stripe_payment_intent, stripe_subscription_id, metadata, created_at, updated_at`

### pause_requests
`_id, enrollment_id, parent_user_id, student_id, session_id, period, reason, status ("pending"|"approved"|"declined"), payment_mode, subscription_status, decision_note, decided_by, decided_at, stripe_pause_status, created_at, updated_at`

### waitlist
`_id, session_id, student_id, parent_user_id, status ("waiting"|"offered"|"enrolled"|"expired"), requested_by, requested_at, offered_at, offer_expires_at, enrolled_at, enrollment_id, is_deleted`

### waiver_acceptances
`_id, student_id, parent_user_id, accepted_by_user_id, waiver_version, waiver_text_hash, waiver_text, accepted_at`

### audit_logs
`_id, user_id, user_email, role, action, entity_type, entity_id, summary, created_at`

---

## 2. API Surface (current)

> All routes prefixed `/api`. ✅ = shipped.

### Auth & users
| Method | Path | Role | Notes |
|---|---|---|---|
| ✅ POST | `/auth/register` | public | parent self-signup |
| ✅ POST | `/auth/register-full` | public | parent + child + optional enrollment or waitlist; selected-session registration creates a pending registration payment |
| ✅ GET | `/auth/public-sessions` | public | list registration sessions with capacity fields |
| ✅ POST | `/auth/login` | public | |
| ✅ POST | `/auth/logout` | any | |
| ✅ GET | `/auth/me` | any | |
| ✅ POST | `/auth/refresh` | any | refresh cookie |
| ✅ POST | `/auth/forgot-password` | public | sends reset link by email when Resend is configured; response stays generic |
| ✅ POST | `/auth/reset-password` | public | |
| ✅ POST | `/invites` | admin | invite coach/parent |
| ✅ GET | `/invites` | admin | |
| ✅ DELETE | `/invites/{token}` | admin | |
| ✅ GET | `/invites/info/{token}` | public | for accept page |
| ✅ POST | `/invites/accept/{token}` | public | |
| ✅ GET | `/users[?role=...]` | admin | |
| ✅ GET/PATCH/DELETE | `/users/{id}` | admin | edit name, email, phone, status |
| ✅ POST | `/users/{id}/reset-password` | admin | |

### Sessions & enrollment
| Method | Path | Role | Notes |
|---|---|---|---|
| ✅ GET/POST | `/sessions` | varied | includes capacity snapshot fields |
| ✅ GET/PATCH/DELETE | `/sessions/{id}` | admin | |
| ✅ POST | `/sessions/{id}/cancel` | admin | |
| ✅ POST/GET | `/students` | varied | with t-shirt + previous experience; admin gets `enrollments[]` per student |
| ✅ GET/PATCH/DELETE | `/students/{id}` | varied | |
| ✅ POST/GET | `/enrollments[?session_id,student_id]` | varied | parent-created = `approval_status: pending`; full sessions return a waitlist entry |
| ✅ POST | `/enrollments/{id}/cancel` | varied | |
| ✅ POST | `/enrollments/{id}/approve` | admin | |
| ✅ POST | `/enrollments/{id}/transfer` | admin | permanent or single-month override |
| ✅ POST | `/enrollments/{id}/pause-month?period=YYYY-MM` | admin | |
| ✅ POST | `/enrollments/{id}/resume-month?period=YYYY-MM` | admin | |
| ✅ GET/POST | `/pause-requests` | admin/parent | parent creates own pause request; admin lists all |
| ✅ POST | `/pause-requests/{id}/approve` | admin | adds enrollment skip period; pauses current-month Stripe collection when applicable |
| ✅ POST | `/pause-requests/{id}/decline` | admin | |
| ✅ GET | `/enrollments/pending-approval` | admin | |
| ✅ GET | `/move-log` | admin/coach | |
| ✅ GET/POST | `/waitlist` | admin/parent | admin lists all; parent lists own or joins child to waitlist |
| ✅ POST | `/waitlist/{id}/enroll` | admin | converts waiting/offered entry into enrollment |

### Attendance & coaching
| ✅ POST | `/attendance/bulk` | coach/admin | statuses incl. `make_up` |
| ✅ GET | `/attendance` | varied | |
| ✅ GET/POST/PATCH/DELETE | `/lesson-plans` | coach/admin | |
| ✅ GET/POST/DELETE | `/progress-notes` | varied | |

### Finance
| ✅ GET/POST | `/payments` | varied | parent sees own only |
| ✅ POST | `/payments/generate-monthly` | admin | skips paused months, non-Standard billing, and active auto-pay subscriptions |
| ✅ PATCH | `/payments/{id}/mark-paid` | admin | |
| ✅ PATCH | `/payments/{id}/apply-discount` | admin | |
| ✅ DELETE | `/payments/{id}` | admin | soft delete |
| ✅ POST | `/payments/{id}/undo-paid` | admin | reverts paid → pending |
| ✅ POST | `/payments/{id}/refund` | admin | records refund; uses Stripe refund when a Stripe payment intent exists |
| ✅ GET/POST/PATCH/DELETE | `/expenses` | admin | |
| ✅ GET/POST | `/payout-rules` | admin | |
| ✅ POST | `/coach-payouts/calculate` | admin | honors `rule.basis` |
| ✅ GET | `/coach-payouts[?period]` | varied | |
| ✅ POST | `/coach-payouts/{id}/approve` | admin | |
| ✅ POST | `/coach-payouts/{id}/mark-paid` | admin | also creates auto-expense |
| ✅ POST | `/coach-payouts/{id}/undo-paid` | admin | reverts + soft-deletes auto-expense |
| ✅ POST | `/coach-payouts/{id}/undo-approve` | admin | |
| ✅ GET | `/coach-payouts/{coach_id}/payslip?period=YYYY-MM` | admin/coach | returns expected_revenue + collected_revenue + payout |

### Dashboard, reports, settings
| ✅ GET | `/dashboard/{admin|coach|parent}` | role-gated | admin returns expected/collected/waived, utilization, profitability |
| ✅ GET | `/reports/{revenue|profit|attendance|pending-payments|coach-payouts|waivers}.csv` | admin | |
| ✅ GET | `/audit-logs?limit=N` | admin | |
| ✅ GET/PATCH | `/settings` | admin | academy singleton |
| ✅ POST | `/settings/payout-basis` | admin | per-coach |

### Communications
| ✅ GET | `/messages/contacts` | any | role-scoped recipient list |
| ✅ GET | `/messages/threads` | any | |
| ✅ GET | `/messages/thread/{user_id}` | any | marks received as read |
| ✅ POST | `/messages` | any | also creates notification |
| ✅ GET | `/notifications` | any | |
| ✅ PATCH | `/notifications/{id}/read` | any | |
| ✅ POST | `/notifications/read-all` | any | |

### Extras
| ✅ GET | `/dues-followup` | admin | returns parents + total_due + WhatsApp link |
| ✅ POST | `/billing/checkout-session` | parent/admin | Stripe Checkout |
| ✅ POST | `/billing/subscription-checkout` | parent/admin | Stripe Billing monthly auto-pay for an approved enrollment |
| ✅ POST | `/billing/customer-portal` | parent/admin | Stripe Customer Portal for saved cards/subscription management |
| ✅ GET | `/billing/checkout-status/{session_id}` | any | falls back to local txn state if Stripe lookup fails |
| ✅ POST | `/webhook/stripe` | public | Stripe webhook → flips one-time payments to paid; records subscription invoices; tracks failed/cancelled subscriptions |
| ✅ POST | `/email/test` | admin | sends a probe via Resend |
| ✅ POST | `/email/send-dues-reminders` | admin | bulk to all parents with pending; reports sent/failed/skipped |
| ✅ POST | `/email/welcome/{parent_id}` | admin | returns 503 if provider is skipped/failed |
| ✅ GET | `/health` | public | container/platform health check |

---

## 3. Frontend Pages (current)

```
Public
  /login                       — demo-fill buttons, link to /register-student
  /register                    — legacy parent-only signup (kept)
  /register-student            — NEW 3-step public form (replaces Google Form)
  /accept-invite/:token        — coach/parent invite landing
  /forgot-password, /reset-password

Admin
  /admin/dashboard             — Collected, Expected, Waived, Payouts, Pending, Net Profit + 6-mo profit chart + session utilization table
  /admin/sessions              — create/edit/cancel/delete
  /admin/students              — Enrolled/Not enrolled filter, pending pause request queue, Pause/Resume/Move buttons per enrollment
  /admin/waitlist              — waitlist entries and admin enrollment conversion
  /admin/users                 — Tabs: coaches / parents / pending invites — Edit modal (name, email, phone, status)
  /admin/payments              — Generate monthly, discount, mark paid, invoice number, **Undo paid**, refund
  /admin/dues                  — 28+ parents, WhatsApp wa.me link + Copy message
  /admin/expenses              — categories, soft delete
  /admin/payouts               — Tabs: Payouts (calc + approve + pay + **Undo**), Rules
  /admin/coach-payslip         — per-coach × month: Expected | Collected | Payout (with formula)
  /admin/reports               — 6 CSV downloads, including waiver acceptances
  /admin/audit-logs            — last 500 mutating actions
  /admin/settings              — Tabs: Academy info / Payout Basis / Email
  /messages                    — universal threaded chat

Coach
  /coach/dashboard
  /coach/sessions              — assigned sessions cards
  /coach/sessions/:id          — Tabs: Attendance grid (P/A/L/E + Make-up) / Lesson plans / Progress notes
  /coach-payslip               — own only

Parent
  /parent/dashboard
  /parent/children             — register child, enroll in session
  /parent/payments             — **Pay now (Stripe)**, monthly auto-pay setup, billing portal, pause requests + history
  /parent/attendance, /parent/progress
```

---

## 4. Test Credentials (auto-seeded on startup)

```
admin@badminton.app    / Admin@12345    (role: admin)
coach@badminton.app    / Coach@12345    (role: coach — demo)
parent@badminton.app   / Parent@12345   (role: parent — demo)
```

After BLno spreadsheet import (`/app/backend/scripts/import_blno.py`):
```
gowtham@blno.academy   / Coach@12345
kishore@blno.academy   / Coach@12345
<any imported parent email>  / Parent@12345
```

---

## 5. Implemented (history)

- **2026-02 — Phase 1 MVP:** Auth + 4 roles, admin/coach/parent dashboards, sessions CRUD, student registration, payment tracking, coach assignment + payout rules, attendance, expenses, profit chart, in-app messaging + notifications, lesson plans, progress notes, CSV reports, audit logs, soft delete everywhere.

- **2026-02 — Phase 2 BLno data + 8 features:** imported the actual BLno-Badminton-Training.xlsx (4 sessions, 42 parents, 46 students, 46 enrollments, Apr+May payments+expenses, attendance), added billing_type (Standard/NoCharge/Waived), session transfer + move_log, make-up attendance status, t-shirt size + previous experience, Dues Followup page with WhatsApp generator, Coach Payslip per coach×month, Expected/Collected/Waived KPIs + utilization%, admin edit user (name/email/phone/status) + reset password, enrollment approval workflow.

- **2026-02 — Phase 3 Power-user + Self-pay:**
  - Admin Settings page (academy info, per-coach payout basis collected|expected, reminder template, default prices, email test, bulk dues email)
  - Undo paid for student payments + coach payouts (auto-expense reversed)
  - Undo approve for coach payouts
  - Public student registration `/register-student` — 3-step form, replaces Google Form, creates parent+child+optional enrollment (pending), auto-login
  - **Stripe Checkout** integration via the official Stripe SDK
  - Stripe webhook + status polling with local-state fallback
  - **Resend email** integration: test email, welcome, bulk dues reminders
  - Pause-month + Resume-month on enrollments — handles "kid in Apr, not May, back in June"
  - Pay-now button on parent payments page

- **2026-05 — Phase 4 production-readiness baseline:**
  - Centralized capacity reservation with `reserved_seats`, public capacity fields, and shared enrollment creation rules
  - Public registration and parent enrollment now respect capacity; full sessions create waitlist entries instead of overbooking
  - Waitlist collection, admin waitlist page, admin conversion flow, and first waiting entry promotion when a seat opens
  - Registration payment gating: selected-session public registration creates `pending_payment` enrollment plus registration payment; paid webhook/manual paid advances to pending approval
  - Coach and messaging authorization fixes: coaches are scoped to assigned sessions/students; message send/thread access is restricted to allowed contacts
  - Invoice metadata and refund records on payments; admin refund action; Stripe refund call when a Stripe payment intent is available
  - Waiver version/hash tracking with immutable `waiver_acceptances` export
  - Forgot/reset password UI and reset email flow; reset tokens are no longer printed to backend logs
  - Email routes now surface skipped/failed delivery instead of returning success-shaped responses
  - Deployment baseline: backend health endpoint, Dockerfiles, docker-compose, nginx SPA config, `.dockerignore`, and `DEPLOYMENT.md`
  - Resend sending domain verified for `academy.courtmastr.com`; local test email accepted by Resend
  - Stripe test checkout validated end-to-end with Stripe CLI webhook forwarding; webhook marked a test payment paid
  - Stripe Billing auto-pay foundation: parent subscription checkout, Customer Portal link, webhook handling for paid/failed invoices and subscription status, parent pause requests, admin approval queue

---

## 6. Phase 4 Backlog (next up)

Prioritized. Each item is sized so it can be picked up independently.

### P0 — Polish on shipped flows
1. **Email deliverability monitoring** — `academy.courtmastr.com` is verified in Resend; monitor bounces/complaints and keep `SENDER_EMAIL=noreply@academy.courtmastr.com`
2. **Stripe recurring payment live validation** — one-time Checkout is tested; still run a full subscription Checkout card test and verify `invoice.paid` creates the monthly payment record
3. **Pending-payment and waitlist expiry scheduler** — release abandoned `pending_payment` seat holds and expire offered waitlist seats after their deadline
4. **Waitlist notifications** — email parent/admin when a waitlist offer is created, expiring, accepted, or expired
5. **Invoice/receipt artifacts** — generate PDF/email receipts or hosted invoice views from the current invoice metadata
6. **`payments` undo-paid guardrail** — prevent silent undo of Stripe-paid payments without using the refund workflow or an explicit admin override
7. **`coach-payouts.undo-paid`** — instead of regex match on notes, store `coach_payout_id` as first-class field on the auto-expense and match by that (testing agent's recommendation)
8. **Pause scheduler for future auto-pay months** — approval skips app billing immediately; future-month Stripe collection pauses need a scheduled job at the start of the paused month
9. **Production monitoring and backups** — connect platform uptime checks, error logging, Mongo backup retention, and a restore drill to the documented deployment runbook
10. **CORS production verification** — verify canonical production/preview hosts against `FRONTEND_URL` and `CORS_ORIGINS`

### P1 — High-value features
11. **Scheduled automation:** APScheduler job that on the 1st of each month
   - runs `payments/generate-monthly`
   - then emails dues reminders via Resend
   - then sends WhatsApp reminders via Twilio (requires Twilio credentials)
   *Implementation:* new file `/app/backend/jobs/monthly.py`, start scheduler in `server.py` startup event
12. **Twilio WhatsApp auto-send** — replaces the manual "click wa.me" loop on Dues Followup. Requires Twilio Account SID + Auth Token + WhatsApp-enabled From number
13. **Calendar view** — parent read-only child schedule; coach can update their assigned session calendar; admin sees all. Support iOS/Android by exposing `.ics` feeds first, then optional PWA calendar UI. Backend: `GET /api/calendar/events?from=...&to=...`
14. **Announcements** — admin can post academy-wide; coaches can post only to their assigned sessions (a new collection `announcements` + frontend feed on each role dashboard)
15. **App roster views** — spreadsheet roster sync is no longer the goal; coaches need an in-app roster per assigned session with payment/pause/enrollment status visible where appropriate

### P2 — Deeper coaching tools
16. **Structured progress scoring** — deferred until the academy defines why it is needed; keep free-text notes for now
17. **Student deep portal** — deferred; current parent/student pages are enough unless separate student logins become a clear need
18. **Match results & tournament fees** — new income category + per-student match record + leaderboard
19. **Equipment loans / shop** — track rackets, shuttles, jerseys lent out vs sold

### P3 — Growth & analytics
20. **Marketing landing page** at `/` (currently redirects to dashboard) — features, pricing, parent testimonials, "Register now" CTA
21. **Referral program** — parents get $20 credit per referred parent (auto-applied as discount)
22. **Cohort retention analytics** — % of kids in May who are still enrolled in Aug, etc.
23. **Multi-location / multi-court** — add `location` entity, sessions reference it, dashboards filterable
24. **Coach 1-on-1 booking** — private lesson slot system + Stripe per-slot payment
25. **Push notifications (web + mobile PWA)** — currently in-app only

### P4 — Mobile
26. **PWA with offline-first attendance** — coach can mark attendance even without signal, syncs when back online
27. **Native wrap** with Capacitor for App Store / Play Store presence

---

## 7. Tech debt & known issues

- **Waitlist offers and pending-payment holds need scheduled expiry** — current backend can create offers/holds but does not yet run a background job to expire and release them automatically.
- **Future-month Stripe pause requests need a scheduler** — approving a pause immediately updates app billing; current-month Stripe subscriptions are paused until the next month, but future pauses need a job to apply the pause when that month starts.
- **Waitlist notification delivery is manual/incomplete** — offer creation does not yet email/SMS parents automatically.
- **Invoice records are metadata only** — no PDF receipt or hosted invoice artifact exists yet.
- **Refund workflow does not replace undo-paid completely** — `undo-paid` still exists for manual correction and should be guarded for Stripe-paid payments.
- **Frontend ESLint warnings** about `useEffect` exhaustive-deps — harmless but should add `eslint-disable-next-line` comments or refactor
- **Background email task** in `auth_routes.register_full` uses `asyncio.create_task` — may be cancelled when response completes. Refactor to FastAPI `BackgroundTasks`
- **No DB migration system** — schema changes are applied via `ensure_indexes()` at startup. For production, add Alembic-style migrations or at least version the schema
- **No rate limiting** on auth endpoints beyond brute-force lockout — add slowapi if exposed to public traffic

---

## 8. Environment variables

```bash
# backend/.env
APP_ENV=development
MONGO_URL="mongodb://127.0.0.1:27017"
DB_NAME="academy_manager_local"
CORS_ORIGINS="http://localhost:3000,http://127.0.0.1:3000"
JWT_SECRET="<random-256-bit-hex>"
ADMIN_EMAIL="admin@badminton.app"
ADMIN_PASSWORD="Admin@12345"
COOKIE_SECURE=false
FRONTEND_URL="http://localhost:3000"
STRIPE_API_KEY="sk_test_..."
STRIPE_WEBHOOK_SECRET="whsec_..."
RESEND_API_KEY="re_..."
SENDER_EMAIL="noreply@academy.courtmastr.com"
TWILIO_ACCOUNT_SID="AC..."
TWILIO_AUTH_TOKEN="..."
TWILIO_WHATSAPP_FROM="whatsapp:+1..."

# frontend/.env
REACT_APP_BACKEND_URL="http://127.0.0.1:8001"
```

---

## 9. Running locally / continuing on another platform

1. **MongoDB:** `mongod --dbpath /tmp/academy-manager-mongo-local --bind_ip 127.0.0.1 --port 27017`
2. **Backend:** `cd backend && source .venv/bin/activate && uvicorn server:app --host 127.0.0.1 --port 8001 --reload`
3. **Frontend:** `cd frontend && yarn start` — listens on `:3000`
4. **Reimport BLno data:** `cd backend && BLNO_XLSX="/Users/ramc/Downloads/BLno-Badmintion-Training.xlsx" python scripts/import_blno.py`
5. **Run pytest:** `cd backend && pytest` — iteration tests live in `backend/tests/iter*_test.py`

---

## 10. Quick wins if you only have 1 hour

- Verify `blno.academy` domain at Resend → set `SENDER_EMAIL=noreply@blno.academy` → real email to all parents starts working
- In Stripe Dashboard or Stripe CLI: add/forward to `https://<host>/api/webhook/stripe`, copy `whsec_...`, set `STRIPE_WEBHOOK_SECRET`, then restart the backend
- Add `data-testid="..."` audit on every new interactive element (current coverage is good but not exhaustive)
