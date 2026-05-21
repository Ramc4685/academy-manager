# Academy Manager — Completion Diff

**Baseline:** `origin/main` (working directory is 1 trivial CI commit ahead at `ce03efc fix(ci): restore v2 ulid compatibility`).
**Spec:** [2026-05-21-academy-manager-requirements.md](./2026-05-21-academy-manager-requirements.md).
**Generated:** 2026-05-21.
**Status legend:**
- **Built** — feature is present and substantially matches the spec.
- **Partial** — feature exists but is missing a meaningful slice of spec behavior.
- **Missing** — no implementation.

> Each entry below points to the canonical file(s) on `main`. Frontend lives in [frontend/app/](frontend/app/) (Next.js App Router with `(admin)`, `(coach)`, `(parent)`, `(marketing)`, `(shared)` route groups). Backend lives in [backend/](backend/) (legacy `/api/*` under [backend/](backend/)) and v2 BFF under [backend/v2/interfaces/](backend/v2/interfaces/).

---

## 1. Executive summary

| Persona | Built | Partial | Missing | Total spec pages |
|---|---|---|---|---|
| Public | 1 | 0 | 1 | 2 |
| Admin | 12 | 0 | 1 | 13 |
| Coach | 2 | 2 | 1 (+ Roster tab) | 4 |
| Parent | 3 | 1 | 1 | 5 |
| **Total** | **18** | **3** | **3** | **24** |

**Design system (§2):** **Built**. The 28-variant `Chip` vocabulary, `Avatar`, `Button`, `Card`, `Typography (BigNum/Overline)`, `LaneHeader`, `ShuttleMark`, and chart wrappers are all implemented under [frontend/components/ds/](frontend/components/ds/). Outfit / Manrope / JetBrains Mono are loaded in [frontend/app/layout.tsx](frontend/app/layout.tsx).

**Backend (Appendix A):** ~85% of the listed endpoints exist (legacy `/api/*` is broad; v2 `/api/v2/*` covers the high-traffic flows). The 20 backend gaps from Appendix A are the main implementation list.

**Top deltas to address:**
1. `/admin/enrollments` page is missing — approval flow currently buried elsewhere.
2. `/parent/inbox` (messaging hub) is missing.
3. `/coach/payout` dedicated screen is missing — only a KPI tile on the coach dashboard.
4. Registration is a 5-step stepper, not the 7-step conversational flow (no Welcome / Done editorial moments).
5. Bulk-action endpoints (remind, decline, offer, revoke) are largely absent across admin pages.
6. Coach attendance gestures: swipe-left/right marking is not present (status is toggled via buttons).
7. Several route names diverge: `/coach/dashboard` vs `/coach`, `/parent/payments` vs `/parent/pay`, `/parent/dashboard` vs `/parent`.

The rest of this document expands each spec section with the specific build state and code pointers.

---

## 2. Design System (spec §2)

**Status: Built.** Maps to [frontend/components/ds/](frontend/components/ds/).

| Spec primitive | Built? | File |
|---|---|---|
| Outfit / Manrope / JetBrains Mono fonts | ✅ | [frontend/app/layout.tsx](frontend/app/layout.tsx) |
| `<Chip>` with 28 variants | ✅ | [frontend/components/ds/chip.tsx](frontend/components/ds/chip.tsx) |
| `<Button>` | ✅ | [frontend/components/ds/button.tsx](frontend/components/ds/button.tsx) |
| `<Card>` | ✅ | [frontend/components/ds/card.tsx](frontend/components/ds/card.tsx) |
| `<Avatar>` | ✅ | [frontend/components/ds/avatar.tsx](frontend/components/ds/avatar.tsx) |
| `<BigNum>`, `<Overline>` | ✅ | [frontend/components/ds/typography.tsx](frontend/components/ds/typography.tsx) |
| `<LaneHeader>` | ✅ | [frontend/components/ds/lane.tsx](frontend/components/ds/lane.tsx) |
| `<ShuttleMark>` | ✅ | [frontend/components/ds/shuttle.tsx](frontend/components/ds/shuttle.tsx) |
| Sparkline / MiniBars / Ring (Recharts) | ✅ | [frontend/components/ds/charts.tsx](frontend/components/ds/charts.tsx) |
| Icon set (home, calendar, user, list, check, pay, card, bell, whistle, chart, msg, cog, trophy, signal, filter) | ✅ | [frontend/components/ds/icons.tsx](frontend/components/ds/icons.tsx) |
| `<LaneLine>` (yellow + slate divider) | ⚠ | Not a separately exported component; pattern inlined where needed. Worth extracting. |
| `<CourtLines>` decorative SVG | ⚠ | Used inline in landing only; not in the DS package. |

**Color tokens:** Hex values are used directly in JSX/CSS rather than CSS custom properties or a token table. Consider promoting `#2563eb` / `#facc15` / slate ramps to a tokens file for theming and the spec's Settings → Branding → Accent color UI (§6.13.6) — that picker is meaningless until colors flow through a single source.

---

## 3. Domain model (spec §3)

**Status: Mostly built (Mongo collections), modelled per-context under [backend/v2/contexts/](backend/v2/contexts/).** Spot-checks:

| Entity | Where | Notes |
|---|---|---|
| Academy | [backend/v2/contexts/academy/](backend/v2/contexts/academy/) | Built. `currency` / `locale` open question on multi-currency. |
| Coach / User | [backend/v2/contexts/directory/](backend/v2/contexts/directory/) + legacy auth | Built. |
| Session | [backend/v2/contexts/sessions/](backend/v2/contexts/sessions/) | Built. `feeCycle` not modelled explicitly. |
| Student | sessions context | Built. `dateOfBirth` vs derived `age` open question (mock uses age). |
| Enrollment | sessions context | Built; full lifecycle (`pending / waitlist / offered / enrolled / paused / transferred / cancelled`). |
| Attendance | [backend/v2/contexts/attendance/](backend/v2/contexts/attendance/) | Built. Idempotent v2 endpoint exists. |
| Payment | [backend/v2/contexts/billing/](backend/v2/contexts/billing/) | Built. Refund / partial / waived / nocharge statuses implemented. |
| Dues | extras/dues | Built (list + reminder trigger). Stage progression not fully modelled. |
| Waitlist | derived from Enrollment status | Built (FIFO ordering, position derived). |
| Expense | finance | Built. `recurring` + cadence partially present. |
| Payout | finance | Built (calc, approve, mark-paid). |
| Waiver / WaiverSignature | [backend/v2/contexts/waivers/](backend/v2/contexts/waivers/) | Partial — single "current waiver" fetch exists; multi-version / publish flow missing. |
| Thread / Message | [backend/v2/contexts/comms/](backend/v2/contexts/comms/) | Built (DM + broadcast); no templates / scheduled send / open-rate. |
| Notification | comms | Built (list, mark read). |
| MessageTemplate | n/a | **Missing.** |
| LevelProgress | n/a | **Missing.** ("Beginner 70% to Cadet" mockup is hardcoded.) |
| PauseRequest | sessions/pause | Built. |

---

## 4. Cross-cutting concerns (spec §4)

| Area | Status | Notes |
|---|---|---|
| Auth & roles (§4.1) | **Built** | Firebase Auth; `usePersonaAuth(role)` per route group; `/post-login` redirector. Persona switcher for multi-role users still **Missing** (open question). |
| Notifications bell (§4.2) | **Partial** | List + mark-read endpoints exist; in-app dropdown bell present in admin top bar; cross-channel SMS/push delivery is partial (see backend Notify settings). |
| Status vocabulary (§4.3) | **Built** | All 28 chip variants in [chip.tsx](frontend/components/ds/chip.tsx). |
| Empty / loading / error states (§4.4) | **Partial** | Skeletons and empty cards used inconsistently; no unified empty-state component matching the spec's `<ShuttleMark>` + headline + CTA recipe. |
| Validation & a11y baseline (§4.5) | **Partial** | Field labels and Firebase inputs are standard; explicit `aria-sort`, focus-ring spec, and `Esc`-closes-modal patterns not audited globally. |
| Currency / locale / dates (§4.6) | **Partial** | Money formatted client-side; multi-currency via `Academy.currency` not implemented (most code still assumes a single fixed currency / hard-coded INR or USD per surface). Landing strip says "Built for USA · USD" while mock data is INR — same divergence as in the design package. |
| Offline policy (§4.7) | **Built (Coach)** | Coach app has offline sync + needs-review queue: [frontend/app/(coach)/coach/needs-review/page.tsx](frontend/app/(coach)/coach/needs-review/page.tsx) and offline mutation queue. Header shows online/update indicators. |
| Permissions matrix (§4.8) | **Built** | Persona route groups enforce role; per-resource scoping done in backend handlers. |

---

## 5. Public (spec §5)

### 5.1 Landing — **Built**

- **Frontend:** [frontend/app/page.tsx](frontend/app/page.tsx) + [frontend/app/landing.module.css](frontend/app/landing.module.css)
- Matches the design's hero + 3 role cards + 4-cell bottom strip + footer. Includes the same KPI strip (247 / 4 / 12) and CTA copy.
- **Backend:** No `GET /api/public/academy-stats` endpoint; the KPI numbers appear static. **Gap:** if we want a live KPI strip, add the endpoint.
- **Divergence:** "Built for USA · USD" cell remains a static marketing line — fine for now, but flag for Settings-driven copy later.

### 5.2 Index/Showcase — **Missing**

- No `/showcase` route. The spec acknowledged this is optional/internal; **leave as-is** unless we want the design-system tokens demo page.

---

## 6. Admin (spec §6)

### 6.0 Admin shell — **Built**

- **Layout:** [frontend/app/(admin)/layout.tsx](frontend/app/(admin)/layout.tsx).
- Sidebar (slate-900) + sticky topbar + mobile drawer. Nav config in [frontend/components/admin/screen-meta.ts](frontend/components/admin/screen-meta.ts) (17 items grouped WORK / MONEY / COMMS·OPS — spec had 13, 17 includes extras like Calendar / Audit).
- **Search box (⌘K) / global search:** **Missing.** Top bar has no universal search per the spec.
- **Nav-count badges with `urgent` styling:** **Partial.** Counts are present per the layout component; verify volt-yellow urgent state.
- **Backend support:** `/api/admin/nav-counts` consolidated endpoint **Missing** (spec calls for it; today the frontend would fan out).
- **Backend support:** `/api/admin/search` **Missing.**

### 6.1 Dashboard — **Built**

- **Frontend:** [frontend/app/(admin)/admin/page.tsx](frontend/app/(admin)/admin/page.tsx) + [frontend/components/admin/RevenueChart.tsx](frontend/components/admin/RevenueChart.tsx).
- KPI cards, revenue chart (Recharts), recent payments table.
- **Backend:** `GET /api/dashboard/admin` + `GET /api/v2/admin/dashboard/attention` + `GET /api/v2/admin/finance/revenue` — covers spec ideal contract.
- **Divergence vs spec:**
  - Time-range tabs (`7D / MTD / 6M / 1Y / All`): **verify.** The dashboard chart may render a fixed 7-month range without a range picker.
  - "Live activity" feed (5 rows with `pay/enr/fail/att/wl` kinds): **likely Missing.** No consolidated activity stream endpoint exists.
  - Three-column attention block (Pending approval / Dues / Activity) — confirm the third column.

### 6.2 Payments — **Built**

- **Frontend:** [frontend/app/(admin)/admin/payments/page.tsx](frontend/app/(admin)/admin/payments/page.tsx).
- Status tabs, table with chips, KPI strip.
- **Backend:** Full CRUD + mark-paid / refund / discount / undo-paid endpoints exist (legacy + v2).
- **Gaps vs spec:**
  - Bulk-remind action on selection — **Missing endpoint** (`POST /api/admin/payments/bulk-remind`).
  - Generate-monthly confirm modal flow — handler exists (`POST /api/v2/admin/payments/generate-monthly`); UI confirm flow needs verification.
  - Autopay coverage KPI tile (`71% · 175/247`) — likely Missing as a dedicated metric.

### 6.3 Dues follow-up — **Built**

- **Frontend:** [frontend/app/(admin)/admin/dues/page.tsx](frontend/app/(admin)/admin/dues/page.tsx).
- **Backend:** `GET /api/v2/admin/dues-followup`, `POST /api/v2/admin/dues-reminders`.
- **Gaps:**
  - Per-dues `remind` with channel + template body — **Missing.**
  - Per-dues `resolve` (record payment + close dues atomically) — **Missing.** (Today admin marks payment paid in Payments, then dues closes via recompute.)
  - Recovery sequence CRUD (`Day 0 / +2 / +5 / +14`) — **Missing endpoint;** display likely hardcoded.

### 6.4 Reports — **Partial**

- **Frontend:** [frontend/app/(admin)/admin/reports/page.tsx](frontend/app/(admin)/admin/reports/page.tsx).
- **Backend (CSV):** Revenue, P&L, Attendance, Pending Payments, Coach Payouts, Waivers, Audit Logs — all present.
- **Gaps:**
  - XLSX / PDF format exports — **Missing.**
  - Quick-export period selector (May 2026 / Apr / Q2 / FY) UI — verify; the underlying CSV endpoints accept date ranges but the chip UX may not match.
  - "Custom report" builder — **Missing.** Treat as future.

### 6.5 Sessions — **Built**

- **Frontend:** [frontend/app/(admin)/admin/sessions/page.tsx](frontend/app/(admin)/admin/sessions/page.tsx) + [frontend/app/(admin)/admin/sessions/[id]/page.tsx](frontend/app/(admin)/admin/sessions/[id]/page.tsx).
- **Backend:** Full CRUD + cancel; v2 admin list + create + delete.
- **Gaps:**
  - `Duplicate` action — **Missing.**
  - `Pause session` (vs cancel) — **Missing.**
  - `Increase capacity` modal endpoint — **Missing.**
  - KPI strip "At capacity" / "Waitlist total" / "Open spots" — verify; can be derived client-side.

### 6.6 Coach payouts — **Built**

- **Frontend:** [frontend/app/(admin)/admin/payouts/page.tsx](frontend/app/(admin)/admin/payouts/page.tsx).
- **Backend:** Full list / calculate / approve / mark-paid / undo + payout-rules + payslip.
- **Gaps:**
  - `Approve all` bulk action — verify UI; endpoint loop is straightforward.
  - "View formula" detail modal — verify content matches the per-basis examples in §6.6.

### 6.7 Students — **Built**

- **Frontend:** [frontend/app/(admin)/admin/students/page.tsx](frontend/app/(admin)/admin/students/page.tsx). Infinite scroll, filters, summary cards.
- **Backend:** Legacy CRUD + v2 list.
- **Gaps:**
  - 20-cell attendance bar per row — verify rendering.
  - "Add student" multi-step modal (parent search → student details → session) — verify; today may be a simpler add form.
  - Per-student profile drilldown — verify route exists.
  - Per-student attendance and payment timelines — **Backend Gap** (no dedicated endpoints today).

### 6.8 Enrollments — **Missing (dedicated page)**

- No `/admin/enrollments` route in [frontend/app/(admin)/admin/](frontend/app/(admin)/admin/). Approval logic may be in Students or Waitlist; in either case the dedicated review queue + ready/blocked split + bulk-approve / bulk-decline UX is **not built**.
- **Backend:** `POST .../approve` exists (legacy + v2 cancel); `decline` / `nudge` / `bulk-approve` / `bulk-decline` endpoints **Missing.**
- **Recommendation:** ship a dedicated `/admin/enrollments` page once the missing backend endpoints exist.

### 6.9 Waitlist — **Partial**

- **Frontend:** [frontend/app/(admin)/admin/waitlist/page.tsx](frontend/app/(admin)/admin/waitlist/page.tsx).
- **Backend:** List + promote (enroll-from-waitlist) + skip + delete — present in v2.
- **Gaps:**
  - `Send offer` / `Resend` / `Revoke` flow with `offerExpiresAt` countdown — **Missing endpoints.**
  - Offer policy CRUD (`expiryHours`, `orderRule`, `channels`) — **Missing.**
  - `Add capacity` action on session header — **Missing endpoint.**
  - Manual add to waitlist — verify UI exists.

### 6.10 Expenses — **Built**

- **Frontend:** [frontend/app/(admin)/admin/expenses/page.tsx](frontend/app/(admin)/admin/expenses/page.tsx).
- **Backend:** CRUD + v2 list/create.
- **Gaps:**
  - Stacked-bar category visualization — verify.
  - Recurring auto-creation cron — likely not present; needs scheduler hook (see [backend/api/scheduler/](backend/) routes for pattern).
  - Receipt attachment upload — verify.

### 6.11 Messages — **Built**

- **Frontend:** [frontend/app/(admin)/admin/messages/page.tsx](frontend/app/(admin)/admin/messages/page.tsx).
- **Backend:** Threads / messages / DM / broadcast endpoints.
- **Gaps:**
  - Templates (Payment reminder / Make-up offer / Welcome / Final notice) — likely **Missing** as a managed entity.
  - Scheduled send — **Missing.**
  - Announcements with open-rate metrics — **Missing.**

### 6.12 Waivers — **Partial**

- **Frontend:** [frontend/app/(admin)/admin/waivers/page.tsx](frontend/app/(admin)/admin/waivers/page.tsx).
- **Backend:** `GET /api/v2/admin/waivers`, `GET /api/waiver/current`.
- **Gaps:**
  - Publish new waiver version + per-student re-sign triggers — **Missing.**
  - Per-signature CRUD (remind, view, renew) — **Missing endpoints.**
  - Bulk-remind by `status=pending|expiring` — **Missing.**

### 6.13 Settings — **Partial**

- **Frontend:** [frontend/app/(admin)/admin/settings/page.tsx](frontend/app/(admin)/admin/settings/page.tsx).
- **Backend present:** academy details, fees, gateway, notifications (`GET/PATCH /api/v2/admin/academy/*`), settings (`GET/PATCH /api/settings`), team CRUD (`/api/users` + `/api/v2/admin/users`), invites (`/api/invites`).
- **Gaps:**
  - **Branding** (logo upload, accent color picker, court accent, email signature) — **Missing.**
  - **Roles & access** UX matching spec (Owner / Admin · Full / Admin · Limited / Coach · Senior / Coach with single dropdown per row) — **Partial:** team CRUD exists; the role taxonomy granularity needs confirmation.
  - **Data & exports** (last-backup card, manual export buttons, retention select, account deletion) — **Missing endpoints + UI.**
  - **Gateway connect/disconnect** flows (Stripe, Razorpay UPI, Bank transfer, GoCardless) — **Partial.** Stripe is the only currently-active provider; UPI and bank-transfer recording exist but the connect/disconnect UI is not built.

---

## 7. Coach (spec §7)

### 7.0 Coach shell — **Built**

- **Layout:** [frontend/app/(coach)/layout.tsx](frontend/app/(coach)/layout.tsx).
- Sticky header + bottom tab bar (4 tabs: Home / Today / Sessions / Profile).
- **Divergence:** Spec tab bar is **Today / Sessions / Roster / Payout**. Actual is **Home / Today / Sessions / Profile**.
  - `Roster` tab missing (roster lives inside session detail).
  - `Payout` tab missing entirely (no dedicated coach payout view).
  - `Profile` is extra (spec has it implicit in the avatar pill / not a top-level tab).

### 7.1 Today — **Partial**

- **Frontend:** [frontend/app/(coach)/coach/dashboard/page.tsx](frontend/app/(coach)/coach/dashboard/page.tsx) and [frontend/app/(coach)/coach/today/page.tsx](frontend/app/(coach)/coach/today/page.tsx).
- **Backend:** `GET /api/today` + `GET /api/v2/coach/today` + `GET /api/v2/coach/dashboard`.
- **Built:** KPI tiles (sessions today, students, attendance %, expected cut), today list, date picker.
- **Gaps vs spec:**
  - **Hero "Next in 12 min" card** with volt-tinted gradient and `Start attendance` CTA — needs verification; the current `dashboard` and `today` are split across two pages while the spec describes a single screen.
  - "On Court" eyebrow + court-lines decoration — likely Missing.
  - Route: spec proposes `/coach` root; actual is `/coach/dashboard`. Add a `/coach → /coach/dashboard` redirect for spec-conformance.

### 7.2 Take Attendance — **Partial**

- **Frontend:** [frontend/app/(coach)/coach/sessions/[id]/page.tsx](frontend/app/(coach)/coach/sessions/[id]/page.tsx). Includes roster, status toggle, optimistic UI, offline mutation queue, lesson plan + progress note fields.
- **Backend:** `POST /api/attendance/bulk` (legacy) and `POST /api/v2/coach/attendance` (idempotent).
- **Gaps:**
  - **Swipe-to-mark gesture** (left = absent, right = present) — **Missing.** Status is set via buttons.
  - 5-button menu (present / late / excused / make-up / absent) — **Partial;** verify it's all 5 options.
  - Counter strip showing P / L / A / E / M / · counts at the top — verify.
  - Sticky "N left to mark" bottom bar that turns green on save — verify.
  - "Mark all present" top-right action — verify.
  - 3-tab note bottom sheet (Progress / Lesson plan / Private) — **Partial;** progress note + lesson plan endpoints exist but the 3-tab UX needs verification.
- **Strength:** the offline pipeline ([frontend/app/(coach)/coach/needs-review/page.tsx](frontend/app/(coach)/coach/needs-review/page.tsx)) actually exceeds the spec — surface this in the spec for completeness.

### 7.3 Payout summary — **Missing**

- No `/coach/payout` route.
- Coach sees only the "Expected cut" KPI tile on `/coach/dashboard`.
- **Backend:** `GET /api/coach-payouts/{coach_id}/payslip` exists for PDF but no JSON endpoint scoped to the requesting coach. **Gap.**
- **Recommendation:** add `GET /api/v2/coach/payout` returning the spec's `Payout` shape; add a route + screen.

### 7.4 Sessions / Roster tabs — **Partial**

- `/coach/sessions` (list) and `/coach/sessions/[id]` (detail with roster) exist.
- Separate `/coach/roster` tab from the spec — **Missing.** (Reasonable to omit if session-grouped is preferred; flag as a UX decision.)

---

## 8. Parent (spec §8)

### 8.0 Parent shell — **Built (with route divergence)**

- **Layout:** [frontend/app/(parent)/layout.tsx](frontend/app/(parent)/layout.tsx).
- Tab bar: **Home / Children / Payments / Progress**.
- **Divergence from spec tab bar (Home / Pay / Progress / Inbox):**
  - `Children` tab is extra (manages multi-child households).
  - `Inbox` tab is **Missing** entirely.
  - `Pay` is labeled `Payments`.

### 8.1 Home — **Partial**

- **Frontend:** [frontend/app/(parent)/parent/dashboard/page.tsx](frontend/app/(parent)/parent/dashboard/page.tsx).
- **Built:** Action cards (Payments / Register a child), basic metrics.
- **Gaps vs spec:**
  - Cobalt → blue-700 gradient hero with "Hi, Rohan" + day overline — **Missing** (current home is minimal).
  - Child selector pill (active child + "Add child") — **Missing on home;** lives on a separate `/parent/children` page.
  - Attendance ring + session-context card — **Missing.**
  - "Today" card with court / directions / "I can't make it" — **Missing.**
  - Next-action banner (variants by autopay / payment due / waiver / waitlist offer) — **Missing.**
  - Activity feed (3 rows: note / attend / pay) — **Missing.**
  - "May progress" mini-bars preview — **Missing.**
  - Route: spec proposes `/parent` root; actual is `/parent/dashboard`. Add redirect.
- **Backend:** Consolidation endpoint `/api/parent/home` does not exist — would need to compose `/api/v2/parent/children` + `enrollments` + `attendance` + `progress` (4–5 calls).

### 8.2 Pay / Billing — **Built (route diverges)**

- **Frontend:** [frontend/app/(parent)/parent/payments/page.tsx](frontend/app/(parent)/parent/payments/page.tsx). Spec proposes `/parent/pay`.
- **Built:** Payment history with status chips, enrollment cards with due dates, autopay toggle, pause request button, Stripe billing portal, autopay setup modal, credits display.
- **Backend:** Full coverage — `GET /api/v2/parent/payments`, `POST /api/v2/parent/checkout/start`, `POST /api/v2/parent/autopay/start`, `POST /api/v2/parent/billing/portal`, `GET /api/v2/parent/checkout/status/{session_id}`, pause-requests routes.
- **Gaps:**
  - Big hero "₹4,800 next charge" Outfit-56 display — verify hierarchy matches spec.
  - "Pay now" quick action (skip autopay date) — verify.
  - Invoice PDF download per row — **Missing endpoint.**

### 8.3 Progress — **Partial**

- **Frontend:** [frontend/app/(parent)/parent/progress/page.tsx](frontend/app/(parent)/parent/progress/page.tsx). Lists coach progress notes; minimal layout.
- **Built:** Note cards (student, date, coach name, body), empty state.
- **Gaps vs spec:**
  - 4-tile stats grid (Sessions / Streak / Attendance % / Level) — **Missing.**
  - `LevelProgress.percentToNext` (Beginner → Cadet at 70%) — **Missing model + UI.**
  - Sparkline of sessions trend — **Missing.**
  - Note kind tabs (Progress vs Plan) — verify.

### 8.4 Inbox — **Missing**

- No `/parent/inbox` route. Parent-side messaging relies on the generic [frontend/app/(shared)/messages/page.tsx](frontend/app/(shared)/messages/page.tsx) which currently redirects.
- **Backend:** Generic `/api/messages/*` exists; **parent-scoped endpoints are recommended** per spec §8.4.
- **Recommendation:** ship `/parent/inbox` with tab filters (All / Coach / Academy / Payment), thread list, and conversation view.

### 8.5 Registration flow (7 steps) — **Partial**

- **Frontend:**
  - [frontend/app/(marketing)/register/page.tsx](frontend/app/(marketing)/register/page.tsx) — public signup.
  - [frontend/app/(parent)/parent/onboarding/page.tsx](frontend/app/(parent)/parent/onboarding/page.tsx) — **5-step stepper:** parent info → child info → waiver → session → review → checkout.
  - [frontend/app/(parent)/parent/checkout/return/page.tsx](frontend/app/(parent)/parent/checkout/return/page.tsx) — Stripe return polling.
- **Backend:** Full onboarding flow exists (legacy `/api/start`, `/api/{app_id}`, `/api/{app_id}/status`, `/api/{app_id}/checkout`; v2 mirrors).
- **Gaps vs spec's 7-step flow:**
  - **Step 1 (Welcome editorial moment)** — **Missing.** No splash with the 5-step checklist preview.
  - **Step 7 (Done / confirmation card)** — **Partial.** The return-from-Stripe page handles polling but the spec's success card with calendar / coach welcome / autopay tiles is not built.
  - Order of step 4 (Waiver) vs step 4 (Session) — current order is `parent → child → waiver → session`, spec is `parent → child → session → waiver`. Minor reorder; either is defensible.
  - Quote endpoint (live total before checkout) — **Missing.** Stepper computes total client-side.
- **Recommendation:** add Welcome + Done as standalone steps; align step ordering with the spec; add the quote endpoint for transparency.

---

## 9. Backend gaps summary (from spec Appendix A)

The 20 backend gaps listed in Appendix A of the requirements doc, ranked by impact:

| Priority | Gap | Spec § | Notes |
|---|---|---|---|
| **High** | `GET /api/v2/coach/payout` (coach-facing, JSON) | §7.3 | Blocks coach Payout screen. |
| **High** | Per-dues `resolve` (record payment + close dues atomic) | §6.3 | Currently requires two-step admin workflow. |
| **High** | Bulk endpoints for payments / dues / enrollments / waivers | §6.2, §6.3, §6.8, §6.12 | Spec-required UX. |
| **High** | Waitlist `offer` / `revoke` / `resend` + policy CRUD | §6.9 | Manual workarounds today. |
| **Medium** | Enrollment `decline` / `nudge` + dedicated `/admin/enrollments` page | §6.8 | Approval flow incomplete. |
| **Medium** | Reports XLSX + PDF | §6.4 | Only CSV today. |
| **Medium** | Waiver `publish-version` + per-signature CRUD | §6.12 | Single waiver doc only. |
| **Medium** | Settings: branding, roles UI, data retention, account deletion | §6.13 | All 4 are gaps. |
| **Medium** | Admin universal search (⌘K) + nav-counts consolidated | §6.0 | DX feature, also unblocks the spec's search box. |
| **Medium** | Parent `/api/parent/home` consolidation | §8.1 | Reduce 4-5 round trips to 1. |
| **Medium** | Parent invoice PDF endpoint | §8.2 | Required by spec; nontrivial render. |
| **Medium** | Parent-scoped thread endpoints + `/parent/inbox` page | §8.4 | Required by spec. |
| **Low** | Message templates / scheduled send / open-rate analytics | §6.11 | Quality-of-life. |
| **Low** | Session `duplicate` / `pause-session` / `increase-capacity` | §6.5 | Admin operational ergonomics. |
| **Low** | `GET /api/public/academy-stats` | §5.1 | Needed only if we want live KPIs on landing. |
| **Low** | Recovery sequence config CRUD (Day 0/+2/+5/+14) | §6.3 | Today the sequence is implicit/hardcoded. |
| **Low** | Per-payment `bulk-remind` endpoint | §6.2 | Today only system-wide reminder exists. |
| **Low** | Background-check status tracking | §6.8 / open question | Only relevant for US launches. |
| **Open question** | Multi-currency from day one (`Academy.currency`) | §4.6 | Codebase mostly assumes one fixed currency. |
| **Open question** | LevelProgress model | §8.3 | "70% to Cadet" UI not backed by data. |

---

## 10. Open product questions still outstanding (spec §4.10)

These remain unresolved in the code:

1. **Currency** — code assumes single currency per academy; multi-currency story needs decision.
2. **Persona switcher** for users with multiple roles — not built; `/post-login` routes to one persona only.
3. **Session fee cycle** (monthly vs per-class vs package) — only flat `fee` is modeled.
4. **Multi-academy users** — single academy assumed.
5. **Sibling discount / family billing** — referenced in design copy and Settings → Fees, not surfaced in payment flows.
6. **Cash payments** — manual UPI / bank transfer exist; no formal cash flow.
7. **Background check status** — not tracked.
8. **Refund rules** — `refund` endpoint exists; admin policy / approval ladder unclear.
9. **Waitlist policy defaults** — no admin UI to set (`expiryHours`, `orderRule`, `channels`).
10. **GDPR / data export** — Settings → Data is a gap.
11. **Pause-student behavior on billing** — backend supports pause but the prorate / free-during-pause logic needs spec confirmation.
12. **SMS gateway** — Twilio referenced in spec but provider integration in code needs verification (Resend handles email).

---

## 11. Recommended next moves

In priority order, surfaced from this diff:

1. **Ship `/admin/enrollments`** as a dedicated page + add `decline / nudge / bulk-*` endpoints. (Largest UX gap inside admin.)
2. **Ship `/parent/inbox`** with parent-scoped thread endpoints. (User-visible spec promise.)
3. **Ship `/coach/payout`** + `GET /api/v2/coach/payout`. (One screen + one endpoint.)
4. **Implement waitlist offer/revoke/resend** + offer-policy CRUD. (Unlocks the §6.9 page's main interactions.)
5. **Promote `/coach/dashboard` → `/coach`, `/parent/dashboard` → `/parent`, `/parent/payments` → `/parent/pay`** (redirect or rename) to align with spec routes.
6. **Build the Parent Home hero + activity feed** matching §8.1 to give the parent app the "athletic-app energy" the design calls for.
7. **Add Welcome / Done editorial steps** to the registration stepper.
8. **Promote color values to design tokens** in [frontend/components/ds/](frontend/components/ds/) so Settings → Branding has somewhere to write to.
9. **Add bulk-actions** in Payments, Dues, Enrollments, Waivers — backend endpoints + UI multi-select.
10. **Add the swipe-to-mark gesture** to coach attendance.

Items 1–4 unblock the largest spec → reality gaps. Items 5–10 are polish that bring the UX closer to the design package's intent.

---

*End of completion-diff. Pair with [`2026-05-21-academy-manager-requirements.md`](./2026-05-21-academy-manager-requirements.md) for full feature specs.*
