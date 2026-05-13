# Badminton Academy Manager — PRD

## Original Problem Statement
Build a multi-role web app to manage a badminton academy: classes, students, parents, coaches, payments, coach payouts, expenses, profit, attendance, progress, lesson plans, messages, and notifications.

Roles: **Admin, Coach, Parent, Student**. Style: premium sports SaaS, blue/white/black/yellow.

## User Personas
- **Admin (Owner)** — Manages everything, financial visibility, approves payouts.
- **Coach** — Sees assigned sessions, marks attendance, writes lesson plans + progress notes, messages parents.
- **Parent** — Registers children, enrolls in sessions, pays fees, views attendance/progress, messages coaches.
- **Student** — Read-only view of their schedule, attendance, progress (Phase 2 deep view; Phase 1 minimal).

## Tech Stack
- Backend: FastAPI + Motor (MongoDB async) + JWT (httpOnly cookies) + bcrypt
- Frontend: React 19 + Tailwind + shadcn/ui + Recharts + Phosphor Icons + Outfit/Manrope fonts

---

## Database Schema (MongoDB Collections)

### users
`{ _id, email (unique), password_hash, name, phone, role (admin|coach|parent|student), status (active|invited|suspended|deleted), invited_by, must_change_password, created_at, updated_at }`

### students
`{ _id, parent_user_id, first_name, last_name, dob, age, skill_level, emergency_contact_name, emergency_contact_phone, medical_notes, waiver_accepted, waiver_date, status (active|inactive), is_deleted, created_at }`

### coach_profiles
`{ _id, user_id, bio, specialties[], created_at }`

### sessions
`{ _id, name, skill_level, age_group, start_date, end_date, days_of_week[], start_time, end_time, location, max_students, monthly_price, coach_id, status (active|cancelled|completed), is_deleted, created_at }`

### enrollments
`{ _id, session_id, student_id, parent_user_id, status (active|cancelled|completed), enrolled_at, is_deleted }`

### attendance
`{ _id, session_id, student_id, enrollment_id, date (YYYY-MM-DD), status (present|absent|late|excused), notes, marked_by, marked_at }`

### payments
`{ _id, parent_user_id, student_id, enrollment_id, session_id, period (YYYY-MM), amount, discount, final_amount, status (pending|paid|failed), payment_date, payment_method, marked_by, notes, is_deleted, created_at }`

### expenses
`{ _id, category, description, amount, date, paid_to, status (paid|pending), notes, is_deleted, created_by, created_at }`

### payout_rules
`{ _id, coach_id, rule_type (revenue_percentage|fixed_per_class|fixed_monthly|per_student), value, is_active, created_at }`

### coach_payouts
`{ _id, coach_id, period (YYYY-MM), session_ids[], rule_type, calculated_amount, status (calculated|approved|paid), approved_by, approved_at, paid_at, paid_by, notes, is_deleted, created_at }`

### lesson_plans
`{ _id, session_id, coach_id, date, objective, warmup, skill_drill, game_activity, fitness_activity, homework, coach_notes, created_at }`

### progress_notes
`{ _id, student_id, coach_id, session_id, note, created_at }`

### messages
`{ _id, thread_id (sorted pair), from_user_id, to_user_id, body, read, created_at }`

### notifications
`{ _id, user_id, type, title, message, related_entity, read, created_at }`

### invites
`{ _id, email, role, token (unique), invited_by, status (pending|accepted|expired), expires_at, created_at }`

### audit_logs
`{ _id, user_id, role, action, entity_type, entity_id, summary, created_at }`

### login_attempts, password_reset_tokens (auth support)

---

## API Endpoints

### /api/auth
- POST `/register` (parent self-signup)
- POST `/login`
- POST `/logout`
- GET `/me`
- POST `/refresh`
- POST `/forgot-password`, `/reset-password`

### /api/invites (admin)
- POST `/` invite coach or parent
- GET `/` list pending
- POST `/accept/{token}` (public, sets password)

### /api/users (admin)
- GET `/` list with role filter
- GET/PATCH/DELETE `/{id}`

### /api/sessions
- GET `/` (role-scoped)
- POST `/` (admin)
- GET/PATCH/DELETE `/{id}` (admin)
- POST `/{id}/cancel`

### /api/students
- POST `/` (parent creates child)
- GET `/` (admin: all; parent: own; coach: by session)
- GET/PATCH/DELETE `/{id}`

### /api/enrollments
- POST `/`
- GET `/`
- POST `/{id}/cancel`

### /api/attendance
- POST `/bulk` (coach: mark for session+date)
- GET `/` (filters)

### /api/payments
- GET `/`
- POST `/` (admin manual)
- POST `/generate-monthly` (admin bulk)
- PATCH `/{id}/mark-paid`, `/{id}/apply-discount`
- DELETE `/{id}`

### /api/expenses
- GET/POST/PATCH/DELETE

### /api/payout-rules
- GET/POST/PATCH

### /api/coach-payouts (admin)
- POST `/calculate?period=YYYY-MM`
- GET `/`
- POST `/{id}/approve`, `/{id}/mark-paid`

### /api/lesson-plans (coach RW)
- GET/POST/PATCH/DELETE

### /api/progress-notes (coach RW)
- GET/POST/DELETE

### /api/messages
- GET `/threads`
- GET `/thread/{other_user_id}`
- POST `/`

### /api/notifications
- GET `/`
- PATCH `/{id}/read`
- POST `/read-all`

### /api/dashboard
- GET `/admin`, `/coach`, `/parent`

### /api/reports (admin)
- GET `/revenue.csv`, `/profit.csv`, `/attendance.csv`, `/pending-payments.csv`, `/coach-payouts.csv`

### /api/audit-logs (admin)
- GET `/`

---

## Role Permission Matrix

| Resource         | Admin | Coach        | Parent       | Student |
|------------------|-------|--------------|--------------|---------|
| Users            | RW    | -            | -            | -       |
| Sessions         | RW    | R (assigned) | R (active)   | R       |
| Students         | RW    | R (assigned) | RW (own)     | R (self)|
| Enrollments      | RW    | R (assigned) | RW (own)     | R (self)|
| Attendance       | R     | RW (assigned)| R (child)    | R (self)|
| Payments         | RW    | -            | R (own)      | -       |
| Expenses         | RW    | -            | -            | -       |
| Payout Rules     | RW    | R (own)      | -            | -       |
| Coach Payouts    | RW(*) | R (own)      | -            | -       |
| Lesson Plans     | R     | RW (assigned)| R (child)    | R       |
| Progress Notes   | R     | RW (assigned)| R (child)    | R (self)|
| Messages         | RW    | RW           | RW           | -       |
| Notifications    | R own | R own        | R own        | R own   |
| Reports          | R     | -            | -            | -       |
| Audit Logs       | R     | -            | -            | -       |

(*) Coach payouts require admin approval before marking paid.

---

## Pages
**Public:** /login, /register, /forgot-password, /reset-password, /accept-invite/:token

**Admin:** /admin/dashboard, /sessions, /students, /users, /payments, /expenses, /payouts, /reports, /audit-logs, /messages

**Coach:** /coach/dashboard, /coach/sessions/:id, /messages

**Parent:** /parent/dashboard, /parent/children, /parent/payments, /parent/attendance, /parent/progress, /messages

---

## User Flows (Critical)
1. **Onboarding:** Admin logs in → invites coach via email → coach accepts → coach sets password.
2. **Parent registration:** Parent signs up → adds child → enrolls in session → admin records payment.
3. **Coach attendance:** Coach login → opens assigned session → marks attendance grid (P/A/L/E) → adds lesson plan.
4. **Monthly billing:** Admin runs "Generate Monthly Payments" → reviews list → applies discounts → marks paid.
5. **Payout cycle:** Admin runs "Calculate Payouts" for period → reviews → approves → marks paid.

---

## Admin Dashboard Wireframe
- **Header bar** (sticky, glassmorphism): logo + month switcher + profile dropdown
- **Row 1 (4 KPI cards):** Monthly Income | Expenses | Coach Payouts | Net Profit
- **Row 2 (4 smaller cards):** Total Students | Active Sessions | Pending Payments | Attendance %
- **Row 3 (col-span-2 chart + col-span-2 list):** Profit trend (line, last 6 months) | Upcoming classes (next 7 days)
- **Row 4 (full-width table):** Session profitability (revenue, payout, net)

---

## Phase 1 Implementation Plan (current)
1. Auth + roles + invites + admin seed + audit log
2. User/coach/parent management
3. Sessions CRUD + enrollments + assignment
4. Student registration + waiver + medical
5. Attendance bulk marking
6. Manual payments + discounts + monthly generation
7. Payout rules + payout calculation + approval workflow
8. Expenses CRUD
9. Admin dashboard KPIs + charts
10. Coach + Parent dashboards
11. Messaging (1:1)
12. In-app notifications
13. Basic lesson plans + progress notes
14. CSV exports for reports
15. Audit logs viewer
16. Soft delete + status fields everywhere

## Phase 2 (Backlog)
- Stripe real payments + receipts
- Email + push notifications (Resend/SendGrid + FCM)
- Calendar (FullCalendar)
- Announcements + session-level posts
- Advanced progress scoring (10 skill metrics)
- Profitability per session/coach drill-downs
- Student portal deep view
- Search/filter polish + pagination tuning

## Implemented (Date stamps grow with iteration)
- 2026-02 — Phase 1 MVP build
- 2026-02 — Iteration 2: Imported real BLno spreadsheet data (4 sessions, 42 parents, 46 students, 46 enrollments, Apr+May payments + expenses, 8 attendance records, 2 real coaches). Added: billing_type (Standard/NoCharge/Waived), session transfer (permanent + single-month override) with move_log, make-up attendance, t-shirt size + previous experience on students, Dues Followup page with WhatsApp link generator, Coach Payslip page (per coach × month), Expected/Collected/Waived KPIs + utilization% on admin dashboard, admin edit coach/parent + reset password, enrollment approval workflow.

## Test Credentials
See `/app/memory/test_credentials.md`.
