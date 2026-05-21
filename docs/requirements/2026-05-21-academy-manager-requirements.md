# Academy Manager — Fresh Requirements Document

**Status:** Draft 1 (2026-05-21)
**Source design package:** `/Users/ramc/Downloads/Badminton Academy Manager/` (HTML + JSX mockups, shared `ds.jsx` design system, `mock.jsx` seed data).
**Purpose:** A from-scratch specification derived from the design markup, independent of what is currently implemented. A companion document — `2026-05-21-completion-diff.md` — will map each feature listed here to the current codebase as **Built / Partial / Missing** with file pointers.

> If you only have time to read three things in this doc, read **§2 (Design system)**, **§3 (Shared domain model)**, and **§4 (Cross-cutting concerns)** — every page spec inherits from them. The page specs in §5–§8 are then short because they don't repeat global rules.

---

## 0. Document Purpose & How to Read It

This document is a **specification**, not an implementation plan. For every page in the design package, it captures:

| Block | What it answers |
|---|---|
| Purpose | Why this page exists |
| User stories | What each persona needs to accomplish here |
| UI → Layout | Visible regions in document order |
| UI → Components | Each component, its props/states, copy, validation |
| UI → Data displayed | Every visible value → which domain entity field it comes from |
| UI → Interactions | Buttons, links, gestures, modals, navigations |
| UI → States | Empty, loading, error, partial, offline |
| UI → Responsive/A11y | Breakpoint + accessibility notes |
| Backend (ideal) → Endpoints | Method, path, query, request body, 200 response, error responses |
| Backend (ideal) → Side effects | Events, notifications, scheduled jobs |
| Backend (ideal) → Permissions | Which roles can call |
| Backend (ideal) → Validation | Server-side validation rules |
| Backend (ideal) → Data model touchpoints | Entities read / written, indexes implied |
| Edge cases | What could go wrong, what should happen |
| ↪ Current backend mapping | Footnote pointers to existing v2/legacy routes |

All page specs use the same template so the eventual completion diff is mechanical.

### Conventions
- **"Persona"** = end-user role: Admin, Coach, Parent, Public.
- **"Proposed route"** = the URL the page should live at. Treat as a suggestion if the codebase already commits to a different scheme; the completion-diff will reconcile.
- **Money** = Indian Rupees (`₹`) at the design layer. See §4.6 for the currency/locale open question.
- **Date / time** = `Asia/Kolkata` at the design layer. The current backend likely uses a per-academy timezone setting — see Settings (§6.13).
- **Identifiers** in prose use the mock IDs (`s1`, `c1`, `st3`, …). Real backend IDs are MongoDB ObjectIds or ULIDs depending on context.
- **API examples** use JSON.

---

## 1. Personas & Device Matrix

| Persona | Device | Frame | Auth | Notes |
|---|---|---|---|---|
| **Public** | Web (desktop + responsive) | Browser | Anonymous (sign-in CTA) | `landing.html`, `index.html` — marketing + design system showcase |
| **Admin** | Web (desktop ≥ 1280 px) | Browser-window mock | Authenticated, role `admin` | Left sidebar grouped WORK / MONEY / COMMS; 13 pages |
| **Coach** | Mobile (iOS frame: 402 × 874 px, light/dark hybrid) | iOS frame | Authenticated, role `coach` | Bottom tab bar; 4 tabs; PWA install target; offline-first |
| **Parent** | Mobile (iOS frame: 402 × 874 px) | iOS frame | Authenticated, role `parent` (or anonymous during registration) | Bottom tab bar; 4 base tabs + 7-step registration flow |

### Cross-persona expectations
- Admin is desktop-only in the design. There is no admin mobile/tablet view in scope.
- Coach and Parent are presented in an iOS frame but should be delivered as a responsive web app / PWA — no native app implied.
- Authentication is unified (the existing project uses Firebase Auth per `AGENTS.md`). The design assumes the user is already signed in for Admin / Coach / Parent screens, except the Parent registration flow which begins anonymous.
- An **academy** is the tenant; all data is scoped to one academy. Multi-tenant SaaS is not in scope from this design.

### Personas → roles (proposed)
- `admin` — full read/write on the academy.
- `coach` — read/write on sessions they coach, attendance for those sessions, their own payout. Read-only on academy KPIs.
- `parent` — read/write on their own children, their own enrollments / payments / messages. No view into other families.

---

## 2. Global Design System

The package ships a shared design system in `assets/ds.jsx`. Engineering should mirror it as a small component library (e.g. `frontend/lib/design/` or equivalent) so every page spec can refer to component names instead of re-describing visual primitives.

### 2.1 Typography

| Family | Weights | Usage |
|---|---|---|
| **Outfit** (display) | 400 / 500 / 600 / 700 / 800 | Headings, KPI numerics, page titles. Negative letter-spacing (-0.02em to -0.05em). |
| **Manrope** (body) | 400 / 500 / 600 / 700 | Body copy, table rows, form labels, buttons. Default UI font. |
| **JetBrains Mono** (mono) | 500 / 600 / 700 | Status chips, overlines, numeric codes (invoice IDs, dates), eyebrows, navigation tags. Uppercase, letter-spacing 0.12–0.25em. |

All three are loaded from Google Fonts. Numerics should use `font-variant-numeric: tabular-nums` so columns align.

### 2.2 Color

| Token | Hex | Usage |
|---|---|---|
| `slate-900` | `#0f172a` | Primary dark surface, dark mode background, primary text on light backgrounds, dark button bg |
| `slate-700` | `#334155` | Body text on light backgrounds |
| `slate-500` / `slate-400` | `#64748b` / `#94a3b8` | Muted text, secondary labels, mono eyebrows |
| `slate-200` / `slate-100` / `slate-50` | `#e2e8f0` / `#f1f5f9` / `#f8fafc` | Borders, dividers, alternating row, page bg |
| `blue-600` (Cobalt) | `#2563eb` | Primary action, links, focused state, primary chart series |
| `blue-700` / `blue-50` | `#1e40af` / `#eff6ff` | Pressed, autopay chip bg |
| `volt-400` (Volt yellow) | `#facc15` | Accent: lane-line, shuttle mark, active tab underline, "go" CTAs on dark surfaces, highlight bars |
| `volt-50` / `volt-700` | `#fef9c3` / `#854d0e` | Volt chip bg / fg |
| **Success** | `#10b981` (dot), `#065f46` (fg), `#ecfdf5` (bg) | PAID, ENROLLED, PRESENT, OPEN, APPROVED chips |
| **Warning** | `#f59e0b` (dot), `#92400e` (fg), `#fffbeb` (bg) | PENDING, LATE, NEEDS APPROVAL, CLOSING chips |
| **Danger** | `#ef4444` (dot), `#991b1b` (fg), `#fef2f2` (bg) | FAILED, OVERDUE, ABSENT, FULL chips |
| **Neutral** | `#64748b` (dot), `#334155` (fg), `#f1f5f9` (bg) | REFUNDED, PARTIAL, WAIVED, NO CHARGE, MANUAL, EXPIRED, PAUSED, TRANSFERRED, EXCUSED chips |

> **No purple. No gradients.** The only gradients in the design are the parent app hero (cobalt → blue-700) and the dashboard preview card (slate-900 → slate-800). Avoid introducing additional gradients.

### 2.3 Status chip vocabulary

All chips are **monospace, uppercase, with a leading colored dot**, 3 px radius, 10 px font, letter-spacing 0.08em. 22 variants defined in `ds.jsx`:

| Variant | Label | Domain |
|---|---|---|
| `paid` | PAID | Payment |
| `pending` | PENDING | Payment |
| `failed` | FAILED | Payment |
| `overdue` | OVERDUE | Payment / Dues |
| `refunded` | REFUNDED | Payment |
| `partial` | PARTIAL | Payment |
| `waived` | WAIVED | Payment |
| `nocharge` | NO CHARGE | Payment |
| `autopayOn` | AUTOPAY | Payment method |
| `autopayPend` | AUTOPAY PENDING | Payment method |
| `manual` | MANUAL | Payment method |
| `waitlist` | WAITLIST | Enrollment |
| `offered` | OFFER SENT | Waitlist |
| `expired` | EXPIRED | Offer / waiver |
| `enrolled` | ENROLLED | Enrollment |
| `approval` | NEEDS APPROVAL | Enrollment |
| `paused` | PAUSED | Student |
| `transferred` | TRANSFERRED | Student |
| `present` | PRESENT | Attendance |
| `absent` | ABSENT | Attendance |
| `late` | LATE | Attendance |
| `excused` | EXCUSED | Attendance |
| `makeup` | MAKE-UP | Attendance |
| `full` | FULL | Session capacity |
| `open` | OPEN | Session capacity |
| `closing` | CLOSING | Session capacity |
| `approved` | APPROVED | Generic |
| `draft` | DRAFT | Generic |

This vocabulary is the **only** way status is expressed visually. New states must be added here, not invented per page.

### 2.4 Component primitives (provided by `ds.jsx`)

Engineering should implement these as a library. Page specs reference them by name.

| Component | Signature (props from `ds.jsx`) | Notes |
|---|---|---|
| `<Chip variant label? dark? />` | One of the 22 variants above. | The only way to render status. |
| `<LaneLine label? dark? mt mb />` | Yellow + slate divider with optional mono caption. | Section separator. Used between major content blocks. |
| `<LaneHeader index? title action? dark? />` | Numbered section header (e.g. `01 · Choose your view`). | H3-equivalent. |
| `<ShuttleMark size color />` | SVG shuttlecock motif. | Decorative accent on KPI cards. |
| `<BigNum size color delta deltaTone>{value}</BigNum>` | Outfit 700, tabular numerics, optional ± delta. | KPIs. |
| `<Overline color>{text}</Overline>` | Mono 10 px caption, uppercase. | Eyebrows over headings/values. |
| `<Avatar name size square />` | 8 deterministic background palettes, initials. | Replace with photo if available. |
| `<Button variant size icon onClick full dark />` | Variants: `primary` (cobalt), `volt`, `dark`, `ghost`, `secondary`, `danger`. Sizes: `sm/md/lg/xl`. | All app buttons. |
| `<Card dark p accent>{children}</Card>` | Optional 3 px colored top border (`accent`). | Surfaces. |
| `Icon.*` | Phosphor-style inline SVGs: `arrow`, `arrowL`, `chevR`, `chevD`, `plus`, `check`, `x`, `search`, `bell`, `user`, `filter`, `dl`, `more`, `calendar`, `clock`, `card`, `msg`, `spark`, `pin`, `home`, `pay`, `attend`, `chart`, `whistle`, `list`, `cog`, `trophy`, `signal`. | The icon set is closed — no Heroicons / Lucide mixing. |
| `<Sparkline values w h color fill />` | Inline tiny line chart, last-point dot. | KPI cards. |
| `<MiniBars values w h color highlight />` | Inline bar chart. | KPI cards. |
| `<Ring value size stroke color bg label sub />` | Donut/ring progress (e.g. attendance %). | Parent home, KPI tiles. |
| `<CourtLines w h color opacity />` | Decorative court-line SVG. | Section ornaments. |

### 2.5 Layout primitives

| Primitive | Spec |
|---|---|
| **Page width (desktop)** | `max-width: 1280–1440 px`, padding `28–32 px` horizontal at large viewports, `20 px` at small. |
| **Card radius** | 12 px (large card), 10 px (medium), 8 px (button), 6 px (inline pill), 3 px (chip). |
| **Card border** | `1px solid slate-200` light, `1px solid slate-800` dark. |
| **Card padding** | 24 px default, 16 px compact. |
| **Section spacing** | 56 px between major sections; 24 px between cards within a section. |
| **Grid gutters** | 16–24 px. |
| **Mobile frame** | iOS-shaped, 402 × 874 px viewport, status bar at top (9:41 stub in mocks), home indicator at bottom. |
| **Lane divider** | Used at every major section boundary. Volt yellow (3 px) + slate (1 px) bars flanking an optional mono uppercase label. |

### 2.6 Motion

The design implies **micro-motion only**, not page transitions:
- Button press: `scale(0.985)` on mouse-down, 60 ms.
- Card hover: `translateY(-3px)`, box-shadow grows, 180 ms ease.
- Tab switch / nav: no slide, just instant content swap (single-page experience).
- Coach attendance swipe: physical card translation matching finger position, snap on release.
- Toast / success: fade-in 200 ms, auto-dismiss 4 s.

Engineering should not introduce route-level transitions or animated illustrations unless added to the design system.

### 2.7 Iconography rules

- Only icons from `Icon.*` in `ds.jsx`. If a new icon is needed, **add it to the design system** rather than importing ad-hoc.
- Stroke 2 px, line-cap round, line-join round, currentColor.
- Default size 16 px inside buttons, 18–20 px in nav, 24 px standalone.

---

## 3. Shared Domain Model

Entities below are derived from `mock.jsx` plus the screens that consume them. Field types are inferred and should be confirmed during the backend mapping pass. The model is **per academy**, so every entity carries an implicit `academyId` (or lives under a tenant-scoped collection) that is not repeated in the field lists.

### 3.1 `Academy`

| Field | Type | Example | Notes |
|---|---|---|---|
| `id` | string | — | Tenant id |
| `name` | string | `"Rally Academy"` | Display name |
| `tagline` | string | `"Indoor Badminton · Est. 2018"` | Marketing line, used on landing + admin header |
| `location` | string | `"Court 7 · Northside Sports Complex"` | Street/venue line |
| `city` | string | `"Bengaluru"` | City |
| `timezone` | string | `"Asia/Kolkata"` | IANA tz, used for date formatting |
| `currency` | string | `"INR"` | ISO 4217; affects symbol + formatting |
| `locale` | string | `"en-IN"` | BCP 47 |
| `logoUrl` | string? | — | Optional logo |
| `brandPrimary` / `brandAccent` | string? | — | Optional brand overrides (limited surface area) |

### 3.2 `Coach`

| Field | Type | Example |
|---|---|---|
| `id` | string | `"c1"` |
| `name` | string | `"Arjun Menon"` |
| `initials` | string (derived) | `"AM"` |
| `email` / `phone` | string? | — |
| `sessions` | int (derived count) | 6 |
| `students` | int (derived count) | 42 |
| `rate` | number | 18 (% if Revenue %, INR if Per class, INR if Per student) |
| `basis` | enum: `"revenue_pct"` \| `"per_class"` \| `"per_student"` | — |
| `tone` | string (hex) | `"#2563eb"` | Brand-stable color per coach; used in chips/avatars |
| `status` | enum: `"active"` \| `"inactive"` | — |
| `joinedAt` | datetime | — |

### 3.3 `Session` (= class / batch)

| Field | Type | Example |
|---|---|---|
| `id` | string | `"s3"` |
| `name` | string | `"Cadet Drill · U14"` |
| `coachId` | ref → Coach | `"c2"` |
| `days` | string[] (DOW codes) | `["mon", "wed", "fri"]` |
| `startTime` / `endTime` | time string | `"18:00"` / `"19:30"` |
| `level` | enum | `"Beginner"` \| `"Intermediate"` \| `"Advanced"` \| `"All levels"` \| `"Intermediate+"` |
| `capacity` | int | 14 |
| `enrolledCount` | int (derived) | 13 |
| `waitlistCount` | int (derived) | 1 |
| `fee` | number (per cycle, e.g. monthly) | 6200 |
| `feeCycle` | enum | `"monthly"` \| `"per_class"` \| `"package"` (assumed monthly; needs confirmation) |
| `status` | enum (derived) | `"open"` \| `"full"` \| `"closing"` \| `"paused"` \| `"cancelled"` |
| `description` | text? | — |
| `court` / `venueNote` | string? | `"Court A"` |

### 3.4 `Student` (= athlete)

| Field | Type | Example |
|---|---|---|
| `id` | string | `"st1"` |
| `name` | string | `"Aarav Sharma"` |
| `dateOfBirth` | date | — (mock stores `age: 9`) |
| `parentId` | ref → Parent | — |
| `sessionIds` | ref[] → Session | `["s1"]` (one or many) |
| `joinedAt` | date | `"2024-02"` |
| `payStatus` | enum: `"paid"` \| `"pending"` \| `"failed"` \| `"overdue"` (derived) | — |
| `attRate` | number 0–1 (derived, trailing period) | 0.94 |
| `level` | string | `"Beginner"` |
| `pause` | bool | false |
| `notes` | text? | — |

### 3.5 `Parent` (= account holder)

| Field | Type |
|---|---|
| `id` | string |
| `name` | string |
| `email` | string |
| `phone` | string |
| `childIds` | ref[] → Student |
| `authUserId` | string (Firebase UID) |
| `addedAt` | datetime |

### 3.6 `Enrollment`

| Field | Type | Notes |
|---|---|---|
| `id` | string | |
| `studentId` | ref → Student | |
| `sessionId` | ref → Session | |
| `parentId` | ref → Parent | |
| `status` | enum: `"pending"` \| `"waitlist"` \| `"offered"` \| `"enrolled"` \| `"paused"` \| `"transferred"` \| `"cancelled"` | |
| `submittedAt` | datetime | |
| `waiverSigned` | bool | |
| `waiverSignedAt` | datetime? | |
| `paymentStatus` | enum: `"pending"` \| `"paid"` \| `"failed"` | First-cycle payment |
| `firstPaymentId` | ref → Payment? | |
| `waitlistPosition` | int? | If `status = "waitlist"` or `"offered"` |
| `offeredAt` / `offerExpiresAt` | datetime? | If `status = "offered"` |
| `decidedAt` / `decidedBy` | datetime / user id? | Admin approval audit |

### 3.7 `Attendance`

One record per student-per-session-instance.

| Field | Type |
|---|---|
| `id` | string |
| `sessionId` | ref → Session |
| `sessionDate` | date |
| `studentId` | ref → Student |
| `status` | enum: `"present"` \| `"absent"` \| `"late"` \| `"excused"` \| `"makeup"` |
| `note` | text? |
| `markedBy` | ref → Coach |
| `markedAt` | datetime |
| `streakAfter` | int (derived) |

### 3.8 `Payment`

| Field | Type | Example |
|---|---|---|
| `id` | string | `"p1"` |
| `invoiceId` | string | `"INV-2026-0418"` |
| `parentId` | ref → Parent | — |
| `studentId` | ref → Student | — |
| `sessionId` | ref → Session | — |
| `cycleStart` / `cycleEnd` | date | `2026-05-01` / `2026-05-31` |
| `amount` | number (minor units recommended) | 4800 |
| `method` | enum: `"autopay"` \| `"manual_card"` \| `"upi"` \| `"bank_transfer"` \| `"cash"` \| `"refund_partial"` | |
| `methodDetail` | string | `"Visa •• 4242"` |
| `status` | enum: `"paid"` \| `"pending"` \| `"failed"` \| `"overdue"` \| `"refunded"` \| `"partial"` \| `"waived"` \| `"nocharge"` | |
| `processedAt` | datetime? | |
| `gateway` | enum: `"stripe"` \| `"upi_psp"` \| `"manual"` | |
| `gatewayRef` | string? | Charge/PaymentIntent id |
| `failureReason` | string? | |
| `refundedAmount` | number? | |

### 3.9 `Dues` (= active follow-up)

Derived from overdue payments but stored as its own row to track outreach state.

| Field | Type | Example |
|---|---|---|
| `id` | string | `"d1"` |
| `paymentId` | ref → Payment | — |
| `parentId` / `studentId` / `sessionId` | refs | — |
| `amount` | number | 6200 |
| `daysOverdue` | int (derived) | 4 |
| `stage` | enum: `"first-reminder"` \| `"second-reminder"` \| `"final-notice"` \| `"escalated"` \| `"resolved"` | — |
| `failedAttempts` | int | 1 |
| `lastContactAt` / `lastContactMethod` | datetime / enum: `"sms"` \| `"email"` \| `"call"` \| `"in_person"` | `"sms"` |
| `assignedTo` | ref → User? | Admin user |
| `resolvedAt` / `resolutionNote` | datetime / text? | |

### 3.10 `Waitlist` entry

Modeled as an `Enrollment` with `status ∈ {"waitlist", "offered"}` rather than a separate collection (preferred). UI views surface waitlist views through filtering.

| Derived field | Source |
|---|---|
| `position` | rank by `submittedAt` within `sessionId` |
| `offered` | bool: `status === "offered"` |
| `expires` | from `offerExpiresAt` |

### 3.11 `Expense`

| Field | Type | Example |
|---|---|---|
| `id` | string | |
| `date` | date | |
| `category` | enum: `"facility"` \| `"staff"` \| `"equipment"` \| `"marketing"` \| `"admin"` \| `"other"` | |
| `vendor` | string | |
| `amount` | number | |
| `recurring` | bool | |
| `recurringCadence` | enum: `"monthly"` \| `"quarterly"` \| `"yearly"`? | If `recurring` |
| `note` | text? | |
| `attachmentUrl` | string? | Receipt |
| `createdBy` | ref → User | |

### 3.12 `Payout` (coach)

| Field | Type | Example |
|---|---|---|
| `id` | string | |
| `coachId` | ref → Coach | |
| `period` | `"YYYY-MM"` | `"2026-05"` |
| `basis` | inherited from Coach at time of calc | |
| `rate` | number | 18 (%) |
| `students` | int | 42 |
| `classesHeld` | int | 24 |
| `expectedRevenue` | number | 196800 |
| `collectedRevenue` | number | 184200 |
| `expectedPayout` | number | 35424 |
| `collectedPayout` | number | 33156 |
| `approved` / `approvedBy` / `approvedAt` | bool / ref / datetime | |
| `paid` / `paidAt` / `paidVia` | bool / datetime / string | |

### 3.13 `Waiver`

| Field | Type |
|---|---|
| `id` | string |
| `version` | string (e.g. `"v3.2"`) |
| `title` | string |
| `body` | markdown / html |
| `publishedAt` | datetime |
| `publishedBy` | ref → User |
| `effectiveUntil` | datetime? |

### 3.14 `WaiverSignature`

| Field | Type |
|---|---|
| `id` | string |
| `waiverId` | ref → Waiver |
| `studentId` | ref → Student |
| `parentId` | ref → Parent |
| `signedAt` | datetime |
| `method` | enum: `"checkbox"` \| `"drawn_signature"` \| `"e_sign"` |
| `ipAddress` | string |
| `signatureSvg` | string? |
| `expiresAt` | datetime? |

### 3.15 `Message` / `Thread`

| Field | Type |
|---|---|
| `threadId` | string |
| `participants` | ref[] → User |
| `subject` | string? |
| `kind` | enum: `"coach_parent"` \| `"academy_parent"` \| `"payment"` \| `"internal_admin"` |
| `messages[]` | inline list of `{id, fromId, body, sentAt, readBy[]}` |
| `lastMessageAt` | datetime |
| `flagged` / `archived` | bool |

### 3.16 `Notification`

| Field | Type |
|---|---|
| `id` | string |
| `userId` | recipient |
| `kind` | enum: `"pay-failed"` \| `"pay-paid"` \| `"enrollment"` \| `"note"` \| `"attend"` \| `"offer"` \| `"message"` \| `"alert"` |
| `title` | string |
| `sub` | string |
| `relatedId` / `relatedType` | optional ref |
| `urgent` | bool |
| `readAt` | datetime? |
| `createdAt` | datetime |

### 3.17 `MessageTemplate`

| Field | Type |
|---|---|
| `id` / `name` / `subject` / `body` / `channels[]` (sms/email/push) / `variables[]` / `lastUsedAt` / `enabled` |

### 3.18 Aggregates / derived

| Aggregate | Source | Used by |
|---|---|---|
| `RevenueByMonth` | sum of Payment.amount grouped by month | Admin dashboard, reports |
| `RevenueByMonth.expenses` | sum of Expense.amount by month | Admin dashboard, reports |
| `TodayRoster` | for a Coach + session date, Attendance left-joined with Enrollment / Student | Coach Today, Take Attendance |
| `PayoutSummaryCurrent` | computed for current period from Payments + Sessions | Coach Payout, Admin Payouts |
| `DashboardKPIs` | active student count, sessions this week, MTD revenue, overdue count, etc. | Admin Dashboard |

---

## 4. Cross-cutting Concerns

These behaviors apply to every page unless explicitly overridden in the page spec.

### 4.1 Auth & roles

- All Admin / Coach / Parent screens require an authenticated session.
- Sign-in is via Firebase Auth (per existing project; the design only shows a `Sign in` CTA). The design does not include a sign-in screen — engineering should implement one consistent with the design system (`Card`, `Button variant=primary`, mono-uppercase eyebrow).
- Role determines persona shell:
  - `admin` → Admin desktop shell.
  - `coach` → Coach mobile shell.
  - `parent` → Parent mobile shell.
  - Users with multiple roles (e.g. an admin who is also a parent) see a persona switcher in the top bar (open question — see §4.10).
- Public pages (landing, index) need no auth.
- Anonymous user starting the parent registration flow does NOT yet need an account; the flow creates one at step 2 (Parent info) or step 6 (Payment) depending on implementation — see §8.5.

### 4.2 Notifications

- A persistent **notification bell** appears in every authenticated shell's top bar; tapping opens an inbox panel. Mock data (`NOTIFICATIONS`) lists kinds: `pay-failed`, `pay-paid`, `enrollment`, `note`, `attend`, `offer`, `message`, `alert`.
- Urgent notifications (`urgent: true`) bubble to a red badge with the count.
- Each notification deep-links to its source (e.g. a failed payment → Payments page filtered to that row; an offer → Enrollment detail).
- Cross-channel delivery (SMS, email, push) is owned by the backend per Settings (§6.13 → Notifications). The design surface is the in-app inbox.

### 4.3 Status vocabulary

The 28 chip variants in §2.3 are the **only** way state is shown visually. New states require adding to the design system + this table.

### 4.4 Empty / loading / error states (defaults)

| State | Treatment |
|---|---|
| **Empty (no data yet)** | A neutral `Card` with `ShuttleMark` icon, an Outfit 18 px headline ("No payments yet"), a 13 px Manrope subtitle ("New transactions appear here."), and a `Button variant="secondary"` CTA where relevant ("Record a payment"). |
| **Empty (filter has zero results)** | Same card minus CTA; subtitle reads `"No results for these filters. Clear filters to see everything."` with a `Button variant="ghost"` `Clear filters` action. |
| **Loading** | Skeleton blocks matching the layout; rows use a `slate-100` background with `1.6 s` shimmer. KPI cards show a 24 × 80 px skeleton in place of `BigNum`. Never use spinners on the main content; spinners are reserved for inline button submit. |
| **Error (fetch failed)** | A `Card` with a `Danger` chip "FAILED TO LOAD", error message, and a `Button variant="secondary"` `Retry`. |
| **Error (write failed)** | Inline error banner above the affected form/section. Form fields keep their values. |
| **Partial / stale data (e.g. coach offline)** | A mono uppercase pill at the top of the page "OFFLINE · LAST SYNCED 11:42 AM" with volt accent. Writes queue locally and sync when back online (see §4.7). |

### 4.5 Validation & accessibility baseline

- All form inputs have a `<label>` associated by `for`/`id`, never placeholder-only.
- Inline validation appears on blur and on submit, never on every keystroke. Format: a small mono 11 px `text-danger` line under the field.
- All interactive elements must be keyboard-reachable. Focus ring: 2 px solid `blue-600`, 2 px offset, on every focusable component.
- Color contrast ≥ 4.5:1 for text on background, 3:1 for large headings.
- Status chips include the textual label, not just color (already covered by the chip design).
- Modal dialogs trap focus; `Esc` closes them; the underlying page is `aria-hidden`.
- Tables have semantic `<th>` headers; sortable headers carry `aria-sort`.
- Numeric tables use `font-variant-numeric: tabular-nums` (already covered by typography).

### 4.6 Currency, locale, dates

- The design uses `₹` and lakh/crore-aware abbreviations (`₹5.68L`, `₹3.50L`). Engineering should:
  - Store money in **minor units** (`paise`) as integers.
  - Render using `Intl.NumberFormat(locale, { style: 'currency', currency })` driven by `Academy.currency` and `Academy.locale`.
  - Provide a separate compact formatter for KPI cards that produces the `L` (lakh) / `Cr` (crore) suffix when locale = `en-IN`.
- Dates in chip/eyebrow form: `"May 14"` (locale-aware short).
- Datetime in headers: `"Tuesday · Good morning"` style (locale-aware day name + time-of-day greeting).
- **Open question**: `landing.html` footer says "Built for USA · USD · Stripe · ACH-ready" while `index.html` + all mock data is INR / Bengaluru. Treat the app as **multi-currency from day one**, driven by `Academy.currency`. The landing footer copy is a marketing decision to defer.

### 4.7 Offline policy (Coach app only)

The design explicitly states "Works offline · Coach tool syncs when back online" on the landing page. Specifically:

- **Coach Today** + **Take Attendance** must work read-write while offline:
  - The roster for today's sessions is cached on first load.
  - Attendance marks (`present` / `absent` / `late` / `excused`), notes, and pause toggles are queued locally and pushed when network returns.
  - The header shows "OFFLINE · LAST SYNCED hh:mm" with `volt-400` accent while offline.
  - On reconnection, queued writes are flushed in order, and the user is informed via toast ("12 attendance marks synced").
- **Parent** and **Admin** apps are not required to work offline (network indicators only).

### 4.8 Permissions matrix (summary)

| Resource | Admin | Coach | Parent |
|---|---|---|---|
| Read all sessions | ✔ | ✔ (own) | ✔ (own kids') |
| Edit session | ✔ | — | — |
| Read all students | ✔ | ✔ (own sessions) | ✔ (own kids) |
| Edit student | ✔ | partial (notes, pause request) | partial (own kid profile) |
| Mark attendance | ✔ | ✔ (own sessions) | — |
| Read payments | ✔ | own payout summary only | own kid's payments |
| Refund / waive | ✔ | — | — |
| Approve enrollment | ✔ | — | — |
| Approve waitlist offer | ✔ | — | accept/decline own offer |
| Read all dues | ✔ | — | own kid's |
| Read coach payouts | ✔ | own only | — |
| Approve coach payout | ✔ | — | — |
| Edit expenses | ✔ | — | — |
| Send academy-wide msg | ✔ | — | — |
| Send message to coach | ✔ | ✔ | ✔ (own coach) |
| Manage waivers | ✔ | — | sign own |
| Edit settings | ✔ | — | — |

### 4.9 Telemetry / events (out of scope for this doc)

Page-level analytics events were excluded per the brainstorming decision. Engineering should add them as a separate concern once telemetry tooling is chosen.

### 4.10 Open product questions (collected across all pages)

This list will grow as we walk each page. Initial entries:

1. **Currency** — Multi-currency from day one (driven by `Academy.currency`) or hardcode INR until US launch? (See §4.6.)
2. **Persona switcher** — Should a user with multiple roles (admin + parent) see a switcher, or do they sign into separate shells?
3. **Session fee cycle** — `mock.jsx` only shows a flat `fee`. Is the cadence monthly, per-class, or per-package?
4. **Multi-academy users** — Is a single Firebase user always bound to one academy, or can a coach work at two?
5. **Sibling discount / family billing** — Implied by "sibling-friendly" copy on the landing page, but no rules in the mock.
6. **Cash payments** — Coach accepts cash on court? Or admin records cash after the fact? (See Payments §6.5.)
7. **Background check status** — Mentioned in the Enrollments page Explore output but not present in `mock.jsx`. Confirm whether US-mandated background checks are tracked.
8. **Refund rules** — Partial refund (`p12` in mock) exists, but the flow for triggering one isn't in the design.
9. **Waitlist policy controls** — Auto-accept, offer expiry window, "offer next on decline" rules — design shows the screen but not the defaults.
10. **GDPR / data export** — Listed in Settings but no concrete spec.
11. **Pause-student behavior** — Coach can mark a student paused. Does that affect billing? Free during pause vs prorated?
12. **Email & SMS gateway** — Resend (per AGENTS.md) for email; SMS provider undetermined.

---

<!-- §5 Landing & public, §6 Admin, §7 Coach, §8 Parent, §9 Glossary, Appendices follow -->

## 5. Landing & Public

The design ships two public/desktop pages:

- `landing.html` — the **product landing page** ("Academy Manager · v2.0", `Sign in` CTA).
- `index.html` — a **redesign showcase** ("Rally Academy · v2.0-rc1"), surfacing the same three prototypes plus the design system tokens.

They overlap heavily. The recommendation below treats `landing.html` as canonical for production and `index.html` as an internal/marketing demo page. We'll spec both.

---

### 5.1 Landing

**Persona / device / route (proposed):** Public · web (desktop + responsive down to 600 px) · `/` (root).
**Source (design):** `landing.html`.
**Purpose:** Public-facing homepage. Explains what Academy Manager is, gives each role a CTA into its prototype, surfaces three trust signals (active student count, coach count, sessions per week).

#### User stories
- As a **prospective admin / customer**, I can see what the platform does at a glance and reach a sign-in screen in one click.
- As an **existing user**, I can sign in from the public site.
- As a **prospective coach or parent**, I can see a role-tagged preview that previews what my surface of the app looks like.

#### UI — Layout (top to bottom)
1. **Topbar** — Brand mark + version pill ("v2.0 · Online") + `Sign in` button. Sticky? No (the design shows it scrolling).
2. **Hero** — Two-column on desktop, single-column ≤ 1024 px:
   - Left: `JetBrains Mono` eyebrow `[v2.0] Three roles · one operations platform` (blue-600), then a 104 px Outfit headline `Run your / badminton / academy.` with `badminton` highlighted with a 60%-from-bottom volt-yellow underline ribbon (`background: linear-gradient(180deg, transparent 60%, #facc15 60%)`) and `academy.` muted.
   - Right (`<aside class="hero-side">`): 17 px Manrope description, primary `Sign in` button (slate-900 bg, volt yellow circle-arrow icon, 14 × 22 px padding, drop shadow), secondary `See what's inside` button (white, slate-200 border), and a meta row above a top divider with three KPIs: `247 Active students`, `4 Coaches`, `12/wk Sessions` (each rendered as `<BigNum size={28}>` with mono `Overline`).
3. **Lane line divider** with mono uppercase label `01 · Choose your view`.
4. **Roles grid** — Three role cards, equal-width, min-height 420 px:
   - Each card has a 200 px preview hero, a label section (mono role tag, Outfit 24 px h3, 13.5 px Manrope desc), a bulleted feats list (3 items), and a CTA row with `Open <persona> →` mono link and a circle arrow that flips to volt yellow on hover.
   - **Admin card** preview: dark slate gradient, two KPI tiles ("Revenue ₹5.68L", "Profit ₹3.50L"), a tiny SVG revenue trend (volt yellow line, dashed slate line), a 4-row mini table (`A. Sharma 4.8K`, `K. Rao 4.8K`, `R. Kapoor 6.2K`, `D. Patel 4.8K`).
   - **Parent card** preview: cobalt → blue-700 gradient, "Tuesday · Good morning" mono caption, "Hi, Rohan" Outfit 19 px, white card with a 64 × 64 progress ring (94%) + meta `AARAV'S MAY 15/16`, and a dark "Next · May 28 / ₹4,800 / Autopay ✓" pill.
   - **Coach card** preview: `#06080d` background, mono "● ON COURT" label, "4:30 PM · TUE" timestamp, volt-tinted "NEXT IN 12 MIN / Junior Smash · U10 / Court A · 12 of 12" card, and 4 roster rows (Aarav S., Diya P., Kabir R., Ishita M.) — the last one is the "active" row with a volt "SWIPE →" indicator.
5. **Bottom strip** (`bot-strip`) — 4 cells, 1 px slate-100 dividers, each: mono overline + Outfit 26 px value + 12 px slate-500 sub:
   - "Built for" / `USA` / `USD · Stripe · ACH-ready` — **inconsistent with INR mock data, see §4.6 open question**.
   - "Works offline" / `Courtside` / `Coach tool syncs when back online`.
   - "Mobile-first" / `PWA` / `Install on home screen`.
   - "Self-hosted" / `Yours` / `One academy, one tenant`.
6. **Footer** — Mono uppercase, slate-400. Left: `© 2026 · Academy Manager · v2.0`. Right: `Privacy / Terms / Status / Sign in`.

#### UI — Components
- `<Topbar>` shared with index page (logomark = slate-900 rounded square + volt yellow horizontal bar accent + inline shuttle SVG).
- `<HeroEyebrow>` mono badge + label.
- `<BigNum>` × 3 in the hero meta row.
- `<LaneLine label="01 · Choose your view">`.
- `<RoleCard preview persona title desc features openHref>` — repeated 3 times.
- `<BottomStrip>` cells × 4.
- `<Footer>` mono links.

#### UI — Data displayed
| Visible value | Source |
|---|---|
| Active student count `247` | `count(Students where status = "active")` |
| Coaches count `4` | `count(Coaches where status = "active")` |
| Sessions/wk `12` | `count(Sessions where status ∈ {"open","full","closing"})` |
| Sample roster names (Aarav S., Diya P., Kabir R., Ishita M.) | **Static** — these are illustrative mocks; the landing page should not render real student names. |
| Sample KPIs `₹5.68L / ₹3.50L` | **Static** for marketing copy; do not render real revenue here. |
| `Hi, Rohan` greeting | **Static** illustrative mock. |

**Implication:** the landing page reads only the three KPI numbers as live data (and even those can be static if the academy isn't yet "live"). Everything inside role-card previews is static illustrative.

#### UI — Interactions & navigation
- `Sign in` (topbar + hero primary) → `/login`.
- `See what's inside` → in-page anchor `#roles`.
- Admin card → `/admin.html` (in the prototype) → `/admin` (in production).
- Parent card → `/parent` (in production).
- Coach card → `/coach` (in production).
- Footer links → static legal pages.

#### UI — States
- **Loading** — KPI numbers may render as skeleton 24 × 64 px blocks if fetched live.
- **Error fetching KPIs** — fall back to static defaults (`—` placeholder) without disrupting layout.
- **Offline / no JS** — page must render meaningful content from server-side HTML; the landing has no client-side interactivity beyond hover.

#### UI — Responsive & accessibility
- Breakpoints from the source CSS: `1024 px` (hero collapses to one column, hero `h1` drops to 76 px, roles grid → single column), `600 px` (page padding 20 px, `h1` 52 px, version pill hidden, footer stacks, CTA row stacks).
- Topbar `Sign in` button must remain visible at all breakpoints.
- All role-card previews are decorative; they must have `aria-hidden="true"`. The role card itself is a single `<a>` with `aria-label="Open admin dashboard"`.
- Hero h1 must have `text-wrap: balance` (already in source) but provide a fallback for browsers without support.
- Keyboard: tab order is `Sign in → primary CTA → secondary CTA → Admin → Parent → Coach → footer links`.

#### Backend (ideal)
- `GET /api/public/academy-stats` → `{ activeStudents: number, coaches: number, sessionsPerWeek: number, brand: { name, tagline, city } }` (lightly cached, public).
- No auth required.
- If the page is server-side rendered (recommended for SEO), the stats are inlined at render time.

#### Backend (ideal) — Permissions
- Anonymous read OK.
- The endpoint must not leak per-student data, parent names, payments, etc. Only the three counts + branding.

#### Backend (ideal) — Side effects
- None. Public read.

#### Edge cases & open questions
- An academy that just signed up has `activeStudents = 0`. Show `0`, not a placeholder.
- If the bottom strip claims "Built for USA / USD / Stripe" but the academy's `currency` is INR (current mocks), the strip becomes misleading. Make the strip **statically content-driven**, not data-driven; treat it as marketing copy.
- The role cards link directly to persona apps. If a user is not signed in and clicks "Open admin", the destination must redirect to `/login?next=/admin`. The landing itself does not check auth.

#### ↪ Current backend mapping
- No public stats endpoint currently exists. The closest is `GET /api/auth/public-sessions` (auth_routes.py:356) which returns session names pre-login — not the right shape. **New endpoint required.**
- See Appendix A.

---

### 5.2 Index / Showcase

**Persona / device / route (proposed):** Internal / marketing · web · `/showcase` (or kept as a static demo page outside production navigation).
**Source (design):** `index.html`.
**Purpose:** Internal redesign showcase. Surfaces the three persona prototypes more richly than the landing page, plus a **Design system tokens row** (typography, color, status chips, sport-DNA). Intended for stakeholders, not customers.

#### User stories
- As an **internal stakeholder**, I can review the three persona experiences and the design system tokens on a single page.
- As an **engineer**, I can confirm that my implementation matches the canonical tokens.

#### UI — Layout
1. **Topbar** — Brand `Rally Academy / Operations Platform · v2`. Right: `Production · 247 active` and a date ("May 17, 2026"). Difference vs landing: no sign-in CTA.
2. **Hero** — Eyebrow `[REDESIGN] Three roles · one operations platform`. h1 `Run a badminton academy like a team. / Not like a spreadsheet.` with `like a` italicized, `team` underlined with a 6 px blue-600 underbar, and the second line muted slate-500. Right column: 17 px Manrope description, three large stat tiles (`247 Active students`, `12 Sessions/wk`, `₹5.68L May revenue`).
3. **Lane line** `01 · Three Experiences`.
4. **Section header** with `EXP · 01—03` blue chip + h2 `Open a prototype`, and a top-right mono caption `All clickable · keyboard accessible`.
5. **Prototypes grid** — Three cards in a `1.4fr 1fr 1fr` columns, fixed height 540 px. Same persona content as landing but richer mini-dashboards (e.g. Admin preview adds an "Overdue · 4" KPI tile and per-row status chips `● PAID`, `● PEND`, `● FAIL`).
6. **Lane line** `02 · Design system`.
7. **Section header** `TOKENS / The system`.
8. **Tokens row** — 4 cards:
   - **Typography** — Sample `Aa Outfit`, body sample Manrope, mono `JETBRAINS MONO · 0123456789`.
   - **Color** — 4 swatches (Slate 900, Blue 600, Volt 400, Slate 50) with hex labels overlaid + description "Cobalt for action. Volt for accent and active states. Slate for surfaces. No purple, no gradients."
   - **Status chips** — Sample chips `PAID PENDING FAILED AUTOPAY WAITLIST` + caption "Monospace · uppercase · leading dot. One chip vocabulary across all roles — 22 variants total."
   - **Sport DNA** — Court-line SVG (volt-yellow + slate) + caption "Court-line dividers and shuttle marks. Used as section headers and KPI ornaments — never decorative noise."
9. **Footer** — Mono left `Rally Academy · Internal redesign · v2.0-rc1`, right `Outfit · Manrope · JetBrains Mono`.

#### UI — Components
- Same `<Topbar>` and prototype cards as Landing.
- `<TokensRow>` with 4 child cards using `<Card>`.
- Color swatches: `<Swatch hex labelColor />` × 4 in a flex row.
- Chip preview uses `<Chip>` directly.

#### UI — Data displayed
| Value | Source |
|---|---|
| `Production · 247 active` | live `activeStudents` |
| `May 17, 2026` | today's date, locale-formatted |
| `₹5.68L May revenue` | optional live MTD revenue, otherwise static |
| All prototype-card mock data | static illustrative |

#### UI — Interactions
- Three prototype cards link to `/admin`, `/parent`, `/coach` respectively.
- No other actions.

#### Backend (ideal)
- Same `GET /api/public/academy-stats` as §5.1; optionally extends with `mtdRevenueFormatted` for the hero stats tile.
- No auth required for the design-system rendering; if MTD revenue is shown, that endpoint must require admin auth.

#### Edge cases
- Showcase should be excluded from `robots.txt` if it lives at `/showcase` in production (internal-only).
- If the page is left up indefinitely, the date shown should be live, not hardcoded.

#### ↪ Current backend mapping
- No `/showcase` route exists today. The redesign showcase is purely a static asset right now. **Optional to ship** — it's primarily an internal artifact.

## 6. Admin (web/desktop)

**Persona:** `admin` role.
**Device:** desktop, browser. Min viewport 1280 px wide.
**Source files:** `admin.html`, `assets/admin-screens.jsx`, `assets/admin-ops-screens.jsx`, `assets/admin-comms-screens.jsx`.

The admin app is a single-page shell with a fixed left sidebar, a sticky top bar, and a content pane that swaps based on the active nav item. No URL routing is shown in the prototype, but engineering should implement deep links per page (e.g. `/admin/payments?filter=failed`).

### 6.0 Admin shell (sidebar + topbar)

The shell wraps every Admin page and is therefore specced once.

#### UI — Sidebar (`<AdminSidebar>`)

- **Width:** 240 px, fixed left, full viewport height, `sticky top: 0`, `overflow-y: auto`.
- **Background:** `#0a0f1c` (slightly darker than `slate-900`), right border `1px solid #1e293b`.
- **Brand block** (top, padding 20 × 18, bottom border `1px solid #1e293b`):
  - 32 × 32 rounded square logo (slate-900 bg, 1 px slate-800 border, volt-yellow horizontal bar through the middle, `<ShuttleMark size=18>` inside).
  - To the right: Outfit 15/700 `Rally Academy` (or the academy's display name) and mono 9/700 letter-spaced 0.18em `ADMIN · COURT 7` subtitle (sourced from `Academy.location` — a short context label).
- **Nav groups** — Three group headings:
  - `WORK`: Dashboard, Sessions (count = total active sessions = 7), Students (count = total = 247), Enrollments (count = pending = 3, **urgent** = true → volt-yellow badge), Waitlist (count = 4).
  - `MONEY`: Payments, Dues follow-up (count = 4, **urgent**), Expenses, Coach payouts (count = 4), Reports.
  - `COMMS`: Messages (count = 7 unread), Waivers, Settings.
  - Group heading: mono 9/700 letter-spaced 0.22em, color `#475569`.
  - Item button: 9 × 18 px padding, Manrope 13/500 (600 if active), left border 2 px transparent → `volt-400` when active, background `transparent` → `#1e293b` when active, color `#94a3b8` → `#fff` when active. Hover bg `#101a2e`.
  - Icon (16 px) on the left, color `#64748b` → `volt-400` when active.
  - Count badge: mono 10/700, 1 × 6 px padding, radius 3 px. Default bg `rgba(255,255,255,0.08)` / fg `#cbd5e1`. Urgent bg `volt-400` / fg `slate-900`.
- **User pill** (bottom, padding 14 px, top border `1px solid #1e293b`):
  - Bg `#101a2e`, radius 8 px, padding 10 × 12 px.
  - `<Avatar size=32>`, name (Manrope 13/600 white), mono `ADMIN · OWNER` subtitle.
  - `<Icon.more>` button on the right opens a context menu (sign out, switch academy if applicable, account settings).

#### UI — Topbar (`<AdminTopbar>`)

- **Position:** `sticky top: 0, z-index: 10`, full content-pane width.
- **Background:** `rgba(248,250,252,0.85)` with `backdrop-filter: blur(12px)`.
- **Border bottom:** `1px solid #e2e8f0`. **Padding:** 20 × 40 px.
- **Left:**
  - Optional breadcrumbs row (mono 10/700, last item `blue-600`, separators `/` in `#cbd5e1`).
  - Outfit 28/600 page title.
  - Optional 13 px Manrope subtitle.
- **Right (`actions`):**
  - **Universal search** — 280 × 38 px input with `Icon.search` and `⌘K` hint chip. Placeholder `Search students, sessions, payments…`. Hitting `⌘K` from anywhere opens the same search overlay. Searches across Students, Sessions, Payments, Enrollments, Waitlist.
  - **Notification bell button** — 38 × 38 white, slate-200 border. Red dot at top-right when there are unread notifications. Clicking opens a notification dropdown (see §4.2).
  - Page-specific actions slot (`actions` prop).

#### Backend (shell-level, ideal)

- `GET /api/admin/nav-counts` → `{ sessions: 7, students: 247, enrollments_pending: 3, waitlist: 4, dues_followup: 4, payouts_pending: 4, messages_unread: 7 }`. Polled every 30 s (or pushed via SSE / WebSocket). Drives the badges.
- `GET /api/admin/search?q=<query>&limit=20` → typed array of `{ kind: 'student'|'session'|'payment'|'enrollment'|'waitlist', id, displayName, sub, deepLink }`.
- `GET /api/notifications?role=admin&unreadOnly=false&limit=50`.

#### Permissions
- All shell endpoints require `admin` role.

#### ↪ Current backend mapping
- Search: no endpoint exists. **New.**
- Nav counts: no consolidated endpoint; today this would require multiple calls. **New consolidated endpoint recommended.**
- Notifications: `GET /api/notifications` exists (comms_routes.py:192) — reusable for the bell.
- See Appendix A.

---

### 6.1 Dashboard

**Persona / device / route (proposed):** Admin · desktop · `/admin` (default landing).
**Source (design):** `admin-screens.jsx → AdminDashboard()`.
**Purpose:** Single-screen academy health check — financial KPIs, performance trend, session capacity at a glance, and a triage block ("Needs your attention") for pending enrollments, overdue dues, and live activity.

#### User stories
- As an **admin**, I see the academy's financial pulse (revenue, profit, students, dues) above the fold.
- As an **admin**, I can spot capacity issues (full sessions, growing waitlists) without scrolling far.
- As an **admin**, I can jump from the dashboard to any item that needs a decision (enrollment, dues follow-up, payment alert) in one click.
- As an **admin**, I can change the time window for the revenue chart without leaving the page.

#### UI — Layout
1. **Topbar:** title `Dashboard`, subtitle `Today · Tuesday, May 17, 2026 · Asia/Kolkata`.
2. **KPI strip** — 4-column grid, 16 px gap. Each `<KpiCard>` (24 px padding, `accent` top border, optional `<ShuttleMark>` in the top-right corner):
   - **Revenue · MTD** · `₹5.68L` · delta `+7.5%` (pos, green) · sub `May 1 — May 17` · 84 × 24 sparkline of 7 months' revenue · accent `blue-600`.
   - **Net Profit** · `₹3.50L` · delta `+12.1%` (pos) · sub `61.6% margin` · sparkline of profit values · accent `#10b981`.
   - **Active Students** · `247` · delta `+18 this mo` · sub `across 7 sessions` · sparkline of growth · accent `volt-400`.
   - **Dues outstanding** · `₹26.6K` · delta `4 parents` (**neg**, red) · sub `2 over 7 days late` · sparkline · accent `#ef4444`.
3. **Main two-column row** (`2fr 1fr`, 24 px gap):
   - **Chart card** (`<Card p=28>`):
     - Header: mono overline `Revenue · Expense · Profit`, Outfit 22/600 `Seven-month performance`. Time-range tabs `[7D] [MTD] [6M] [1Y] [All]` — active state slate-900 bg + white fg.
     - `<RevenueChart>` — 200 px tall SVG with revenue area + line (`blue-600`, 2.4 px), expenses dashed line (`#64748b`, 1.6 px), profit line (`volt-400`, 2.4 px). Y-axis labels in lakh increments. X-axis = month abbreviations. Dotted leader on the latest month plus a slate-900 callout chip "₹5.68L" in volt-yellow text. Dots on each data point for revenue and profit.
     - Legend row (24 px gap, top border): `<ChartLegend>` × 3 with colored dots and `BigNum` 18/700 values: Revenue ₹5.68L, Expenses ₹2.18L, Net profit ₹3.50L.
   - **Sessions panel** (`<Card p=0>`):
     - Header (padding 24/24/0): mono overline `Sessions · capacity`, Outfit 18/600 `Live this week`, top-right `View all →` link in blue-600.
     - Body (padding 20/24): 5 `<SessionFillRow>` rows (one per active session, ordered by capacity utilization descending). Each row: session name (Manrope 13/600 ellipsized) + coach + time below, right-aligned mono `enrolled/cap` (12/700), 4 px capacity bar with color by status (`#10b981` open · `#f59e0b` closing · `#ef4444` full). If `waitlist > 0`, a mono caption below "+ N ON WAITLIST" in `#a16207`.
4. **Lane header** `03 · Needs your attention` with a volt-yellow action chip `11 ITEMS`.
5. **Three-column attention row** (16 px gap):
   - **Pending approval** `<Card p=22 accent=#f59e0b>`:
     - Mono overline `Pending approval · 3`, h4 `Enrollments to review`.
     - 3 enrollment rows (avatar 32, name + session sub, status chips `WAIVER` (variant `approval`) if missing, `PENDING` if payment unpaid).
     - Bottom `<Button variant=secondary size=sm full>Review all →</Button>` → navigates to Enrollments.
   - **Dues** `<Card p=22 accent=#ef4444>`:
     - Mono overline `Overdue · ₹26.6K total` (in `#dc2626`), h4 `Dues follow-up`.
     - 3 dues rows: parent name (13/600), `<student> · <days>d overdue` (11 slate-500), right-aligned mono amount in `#dc2626`.
     - Bottom button `Send reminders →` → navigates to Dues.
   - **Activity feed** `<Card p=22>`:
     - Mono overline `Live activity`, h4 `Today`.
     - 5 rows: 8 × 8 colored dot (success/warn/danger/info/neutral) + text + mono timestamp `14M AGO`. Examples: "Anika Patel paid ₹4,800 · INV-0419", "New enrollment · Mira Roy (U10)", "Card declined · A. Kapoor", "Coach Arjun marked 12 present", "Waitlist offer accepted · Naina S.".

#### UI — Components used
- `<KpiCard label value delta deltaTone spark accent sub>` — pattern reused across most admin pages.
- `<RevenueChart>` — purpose-built; can be replaced with a library (Recharts / Visx) but must match colors and labels.
- `<SessionFillRow>` — capacity-bar widget.
- `<ChartLegend dot label value>` — small block.
- `<LaneHeader index title action>`.
- `<Chip>` for in-card statuses.

#### UI — Data displayed
| Visible | Source |
|---|---|
| Revenue MTD `₹5.68L`, delta `+7.5%` | `sum(Payment.amount) where status="paid" AND processedAt in current month` vs same span last month |
| Net Profit `₹3.50L` | revenue MTD − expenses MTD |
| Active Students `247` | `count(Student where status="active")` |
| Dues outstanding `₹26.6K`, `4 parents` | `sum(Dues.amount)`, `count(distinct Dues.parentId)` |
| Sparklines | 7-month series of each KPI |
| Chart series | `RevenueByMonth[]` (7 months trailing) |
| Pending approval rows | `Enrollment where status="pending"` ordered by `submittedAt` desc, limit 3 |
| Dues rows | `Dues where stage != "resolved"` ordered by `daysOverdue` desc, limit 3 |
| Activity feed | Recent events from a `dashboard.activity` stream (last 24 h, limit 5) |
| Live this week sessions | `Session where status ∈ {"open","full","closing"}` ordered by `enrolled/cap` desc, limit 5 |

#### UI — Interactions
- KPI card click → drills into the relevant page filtered to that scope (e.g. Revenue card → Payments filtered to paid, MTD; Dues card → Dues page).
- Time-range tabs change the chart and the KPI deltas; only the chart card re-fetches.
- `View all →` on the Sessions panel → Sessions page.
- Any enrollment, dues, or activity row click → its detail (modal or full page).
- `Send reminders →` → Dues page with the 3 most overdue pre-selected for bulk SMS.
- `Review all →` → Enrollments page.

#### UI — States
- **Loading:** KPI skeletons (24 × 64), chart skeleton (200 px), card rows skeletoned with `Avatar` placeholders.
- **No data (fresh academy):** KPIs render `₹0` and `0`. Chart shows an empty-state SVG with mono caption `Insufficient data for trend`. Attention row shows the standard empty cards from §4.4.
- **Partial failure (one card fails):** that card shows its own error state without affecting the rest.

#### UI — Responsive
- The Admin app is desktop-only. At < 1280 px the layout degrades gracefully: the 4-column KPI strip wraps to 2×2; the main row stacks; attention row stacks to single column. Below 1024 px we display a "Use a desktop browser" notice (admin is not intended for mobile).

#### Backend (ideal)

- `GET /api/admin/dashboard?range=mtd` →
  ```json
  {
    "range": "mtd",
    "kpis": {
      "revenue": { "value": 568000, "delta_pct": 7.5, "trend": [384000,412000,396000,458000,502000,528000,568000] },
      "netProfit": { "value": 350000, "delta_pct": 12.1, "trend": [216000, 240000, 208000, 266000, 304000, 324000, 350000], "marginPct": 61.6 },
      "activeStudents": { "value": 247, "deltaAbs": 18, "trend": [212,221,228,232,238,242,247] },
      "dues": { "value": 26600, "deltaAbs": 0, "parents": 4, "trend": [14000,18000,22000,28000,21000,24000,26600], "over7DaysCount": 2 }
    },
    "revenueChart": [
      { "month": "Nov", "revenue": 384000, "expenses": 168000 },
      ...
    ],
    "liveSessions": [ { "id": "s5", "name": "...", "coach": "...", "time": "...", "enrolled": 10, "capacity": 10, "waitlist": 5, "status": "full" }, ... ],
    "attentionItems": {
      "enrollmentsPending": [ { "id": "e1", "studentName": "...", "sessionName": "...", "waiverSigned": false, "paymentStatus": "pending" }, ... ],
      "duesTop": [ { "id": "d1", "parentName": "...", "studentName": "...", "daysOverdue": 4, "amount": 6200 }, ... ],
      "activity": [ { "kind": "pay", "text": "Anika Patel paid ₹4,800 · INV-0419", "at": "2026-05-17T11:28:00+05:30" }, ... ]
    }
  }
  ```
- `range` accepts `7d | mtd | 6m | 1y | all`.

#### Backend (ideal) — Permissions
- `admin` only.

#### Backend (ideal) — Side effects
- None (pure read).

#### Backend (ideal) — Validation
- `range` enum check.

#### Backend (ideal) — Data model touchpoints
- Reads `Payment`, `Expense`, `Student`, `Session`, `Enrollment`, `Dues`. Aggregations are derived; cache MTD aggregates for 60 s to avoid load.
- Indexes needed: `Payment.processedAt`, `Payment.status`, `Payment.academyId`, `Dues.daysOverdue`, `Enrollment.status`, `Enrollment.submittedAt`.

#### Edge cases & open questions
- Time-range deltas need consistent comparison windows. For MTD use *prior MTD through the same day-of-month*. Confirm definition.
- The "Activity feed" is a fuzzy stream — clarify if it's a true event log or just a derived view of the last N transactions.
- The "Insights" feel needs *some* threshold heuristics for the deltas to colorize correctly (positive vs negative depending on metric).

#### ↪ Current backend mapping
- `GET /api/dashboard/admin` (dashboard_routes.py:20) — exists and returns *some* admin dashboard data, but shape may not match the ideal above. Reuse as the inhabitable endpoint; add fields as needed.
- `GET /api/v2/admin/dashboard/attention` (dashboard_routes.py:21) — exists for the attention block. Confirm fields.
- `GET /api/v2/admin/finance/revenue` (billing_routes.py:290) — supplies revenue analytics; should feed the chart series.

---

### 6.2 Payments

**Persona / device / route (proposed):** Admin · desktop · `/admin/payments?filter=<status>`.
**Source (design):** `admin-screens.jsx → AdminPayments()`.
**Purpose:** Operational ledger of every payment. Filter by status, multi-select rows for bulk reminders/exports/mark-paid, and export to CSV.

#### User stories
- As an **admin**, I can see all payments with their current status, sortable and filterable.
- As an **admin**, I can multi-select rows and send bulk SMS reminders, export, or mark paid.
- As an **admin**, I can trigger the monthly invoice generation for the current cycle.
- As an **admin**, I can drill into any row to see the full payment record.
- As an **admin**, I can refund a payment (partial or full) — flow not in the design.

#### UI — Layout
1. **Topbar:** title `Payments`, subtitle `Ledger · all transactions, all sessions`.
2. **KPI strip** (4 cards):
   - **Collected · MTD** `₹X` (sum of paid), accent `#10b981`, sub `Across N payments`.
   - **Pending** `₹Y`, accent `#f59e0b`, sub `N parents · avg M days`.
   - **Failed · overdue** `₹Z`, accent `#ef4444`, sub `Needs follow-up`.
   - **Autopay coverage** `71%`, accent `blue-600`, sub `175 / 247 students`.
3. **Toolbar / tabs** (inside the wrapping `Card p=0`, top section, padding 16 × 22, bottom border):
   - Left: filter pills `All` · `Paid` · `Pending` · `Failed` · `Overdue` · `Refunded` with counts. Active pill: slate-900 bg, white fg. Count chip inside each pill (mono 10/700).
   - Right (when no selection): `<Button variant=secondary size=sm icon=filter>Filter</Button>` · `<Button variant=secondary icon=dl>Export CSV</Button>` · `<Button variant=primary icon=plus>Generate monthly</Button>`.
   - Right (when selection > 0): mono `N SELECTED` text + `Remind` · `Export` · `Mark paid` (primary).
4. **Table** (dense, mono numerics, hover row highlight `#fafbfd`):
   - Columns: `[checkbox] | Date | Parent / Student | Session | Amount (right-aligned mono) | Method | Status (Chip) | Invoice (mono) | <more> menu`.
   - Header row: slate-50 bg, mono 10/700 letter-spaced 0.15em column labels.
   - Body row: 14 × 14 padding. Parent/Student cell renders `<Avatar size=28>` + Manrope 13/600 parent name + 11 slate-500 student sub.
5. **Footer** (inside the same Card, top border, bg `#fafbfd`):
   - Left: mono `SHOWING N / TOTAL`.
   - Right: pagination `‹ 1 2 ›` (mono buttons).

#### UI — Components
- `<KpiCard>` × 4.
- `<TabPill active count onClick>` × N.
- `<PaymentsTable>` with header + body + footer.
- `<Chip variant={status}>` per row.

#### UI — Data displayed
| Column | Source field(s) |
|---|---|
| Date | `Payment.processedAt` (or `cycleStart` if pending) — short locale (`May 14`) |
| Parent / Student | `Parent.name` + `Student.name` |
| Session | `Session.name` |
| Amount | `Payment.amount` (₹ formatted with thousands) |
| Method | `Payment.method` + `methodDetail` (e.g. `Autopay · Visa •• 4242`) |
| Status | `Payment.status` mapped to chip variant |
| Invoice | `Payment.invoiceId` |

#### UI — Interactions
- Row click → side panel with full payment detail (amount breakdown, retry history, refund options, related session, parent contact).
- Tab pill click → updates filter, resets selection, updates URL `?filter=...`.
- Multi-select via row checkboxes; header checkbox toggles "select all on current page".
- `Generate monthly` → opens a confirm modal: "Generate invoices for cycle May 2026? 247 students · estimated ₹11.85L." with `Cancel` / `Generate` buttons. Triggers an async job; the admin sees a toast and a job-status pill until complete.
- `Export CSV` → downloads `payments_2026-05.csv` with all currently-filtered rows.
- `Remind` (bulk) → opens a composer pre-filled with the "Payment reminder" template; sender selects channel (SMS / email / both).
- `Mark paid` (bulk) → confirm dialog, then PATCHes each.
- Row context menu (⋯) options: View, Refund, Apply discount, Send reminder, Cancel invoice.

#### UI — States
- Empty (no payments yet) — Card with `<ShuttleMark>` and CTA `Generate first monthly invoices`.
- Empty filter (no failed payments) — friendly subtitle.
- Loading — 10 skeleton rows.

#### Backend (ideal)
- `GET /api/admin/payments?status=&from=&to=&q=&page=&pageSize=` → `{ items: Payment[], pagination: {page, pageSize, total}, totals: { collected, pending, failed, refunded } }`.
- `POST /api/admin/payments/generate-monthly` → `{ jobId }` then `GET /api/admin/jobs/{jobId}` for status.
- `PATCH /api/admin/payments/{id}/mark-paid` body `{ reason?, paidAt? }` → updated `Payment`.
- `POST /api/admin/payments/{id}/refund` body `{ amount, reason }` → refund record.
- `POST /api/admin/payments/{id}/apply-discount` body `{ amount, reason }`.
- `POST /api/admin/payments/{id}/undo-paid` (audit-trailed).
- `POST /api/admin/payments/bulk-remind` body `{ paymentIds: [...], channels: ["sms","email"], templateId }` → `{ enqueued: N }`.

#### Permissions
- `admin` only.

#### Side effects
- Generate-monthly → creates N `Payment` records with status `pending`, queues autopay attempts where enabled, emits `payment.generated` events.
- Mark paid / undo paid → emits payment events, writes `AuditLog`.
- Refund → debits via Stripe / UPI provider, writes refund record, emits `payment.refunded`.

#### Validation
- Mark-paid only allowed when status is `pending` or `failed` or `overdue`.
- Refund amount ≤ `Payment.amount − refundedAmount`.
- Discount ≤ `Payment.amount`.

#### ↪ Current backend mapping
- `GET /api/payments` (finance_routes.py:69) — list payments. Confirm filter/pagination shape.
- `POST /api/payments/generate-monthly` (finance_routes.py:122) — generate monthly invoices.
- `PATCH /api/payments/{pid}/mark-paid` (finance_routes.py:210).
- `PATCH /api/payments/{pid}/apply-discount` (finance_routes.py:237).
- `POST /api/payments/{pid}/refund` (finance_routes.py:295) + `POST /api/admin/payments/{payment_id}/refund` (finance_routes.py:344).
- `POST /api/payments/{pid}/undo-paid` (finance_routes.py:260).
- v2 equivalents: `POST /api/v2/admin/payments/generate-monthly`, `POST /api/v2/admin/payments/{payment_id}/mark-paid`, `POST /api/v2/admin/payments/{payment_id}/discount`, `POST /api/v2/admin/payments/refund`, `POST /api/v2/admin/payments/{payment_id}/undo-paid` (all in billing_routes.py).
- No bulk-remind endpoint exists today (`POST /api/email/send-dues-reminders` runs a system-wide job, not per-selection). **New endpoint required.**

---

### 6.3 Dues follow-up

**Persona / device / route:** Admin · desktop · `/admin/dues`.
**Source (design):** `admin-screens.jsx → AdminDues()`.
**Purpose:** Active collections workflow — see which parents owe what, how long they've been overdue, the contact history, and trigger the next outreach step. Surface the automatic recovery sequence rules.

#### User stories
- As an **admin**, I can see all parents with unresolved overdue payments, sorted by days overdue.
- As an **admin**, I can send a single SMS or mark a row paid in one click.
- As an **admin**, I can bulk-remind everyone with one action.
- As an **admin**, I can understand the automatic recovery sequence (Day 0 → +2 → +5 → +14) and confirm the next step.

#### UI — Layout
1. **Topbar:** title `Dues follow-up`, subtitle `Active collections · automatic sequence`.
2. **KPI strip:**
   - **Total overdue** `₹26.6K` (red accent), `4 parents`.
   - **Avg days overdue** `7.2`, `Down from 9.1 last month`.
   - **Final notice** `1`, volt accent, `Pari Dutta · 14 days`.
   - **Recovery rate · 30d** `89%`, `Above industry avg`.
3. **Lane header** `01 · Active follow-ups` with action button `Bulk remind` (primary, msg icon).
4. **Dues rows card** (`<Card p=0>`) — each row in a 4-column grid `1fr / 200px / 240px / 200px`:
   - **Col 1:** `<Avatar size=44>` + parent name (Manrope 15/600) + `<student> · <session>` sub (12 slate-500).
   - **Col 2:** mono overline `Amount due`, Outfit 22/700 amount in `#dc2626`.
   - **Col 3:** mono overline `Status`, then a chip below (`failed` if final-notice, `overdue` if > 5 days, else `pending`) labeled `Nd OVERDUE`, then sub `Last: <method>` (e.g. "2 days ago · SMS").
   - **Col 4:** right-aligned `<Button variant=secondary size=sm icon=msg>SMS</Button>` · `<Button variant=primary size=sm>Mark paid</Button>`.
5. **Lane header** `02 · Recovery sequence · automatic` (no action).
6. **Recovery sequence cards** — 4-column grid:
   - Each card: mono overline (`Day 0`, `Day +2`, `Day +5`, `Day +14`), Outfit 18/600 label, `<Chip>` at the bottom (`open` AUTO SEND / `pending` AUTO SEND / `failed` AUTO PAUSE).
   - Day 0: "Payment due" · OPEN.
   - Day +2: "Friendly SMS" · AUTO SEND (pending tone).
   - Day +5: "Email + call" · AUTO SEND.
   - Day +14: "Final notice · pause" · AUTO PAUSE (failed tone).

#### UI — Data displayed
| Visible | Source |
|---|---|
| Total overdue | `sum(Dues.amount where stage != resolved)` |
| Avg days overdue | `avg(Dues.daysOverdue)`, with last-month comparison |
| Final notice count | `count(Dues where stage="final-notice")` |
| Recovery rate · 30d | `# resolved Dues in last 30d / # opened Dues in last 30d` |
| Row amount | `Dues.amount` |
| Row days overdue | `Dues.daysOverdue` (computed daily from `Payment.cycleEnd`) |
| Last contact | `Dues.lastContactAt` + `lastContactMethod` ("2 days ago · SMS") |
| Stage | `Dues.stage` |

#### UI — Interactions
- `Bulk remind` → opens a composer modal with channel selector + template picker, addressed to all visible dues. Confirm sends.
- Per-row `SMS` → opens a small composer prefilled with the parent's mobile and the appropriate-stage template; one click `Send`. On success, updates `lastContactAt` and shows a toast.
- Per-row `Mark paid` → opens "Record manual payment" modal (amount auto-filled, method = manual/UPI/cash dropdown, optional note). Submit creates a `Payment` record + closes the `Dues`.
- Click on a row body → drill-down panel with payment history, retry log, communications log.

#### UI — States
- Empty (no dues) — `<ShuttleMark>` card "All caught up · no overdue payments".
- Loading — skeleton rows.

#### Backend (ideal)
- `GET /api/admin/dues` → `{ items: Dues[], totals }`.
- `POST /api/admin/dues/{id}/remind` body `{ channel, templateId, customBody? }` → emits notification, updates `lastContactAt`.
- `POST /api/admin/dues/bulk-remind` body `{ duesIds[], channel, templateId }`.
- `POST /api/admin/dues/{id}/resolve` body `{ method, amount, note? }` → creates Payment, marks Dues `resolved`.
- `GET /api/admin/dues/sequence` → returns the configured recovery sequence (the 4 steps).
- `PATCH /api/admin/dues/sequence` (subset of Settings → Notifications) updates the steps.

#### Permissions
- `admin` only.

#### Side effects
- `remind` → enqueue SMS/email via Twilio/Postmark/Resend, persist communication record.
- `resolve` → creates a `Payment` (status `paid`), updates `Dues.stage = resolved`, emits `dues.resolved` event, updates KPI counters.
- Day-14 auto-pause → schedules `Enrollment.status = paused`.

#### Validation
- Amount on resolve must equal or exceed the outstanding balance unless `partial` flag is provided.

#### ↪ Current backend mapping
- `GET /api/dues-followup` (extras_routes.py:20) — list overdues.
- `GET /api/v2/admin/dues-followup` (dues_routes.py:19) — v2 equivalent.
- `POST /api/v2/admin/dues-reminders` (dues_routes.py:28) — trigger reminders.
- `POST /api/email/send-dues-reminders` (email_routes.py:138) — legacy bulk-send.
- Per-dues `remind` and `resolve` endpoints are not separate from the payment endpoints today. **New `dues.resolve` recommended** vs. requiring an admin to manually go to Payments → mark-paid.

---

### 6.4 Reports

**Persona / device / route:** Admin · desktop · `/admin/reports`.
**Source (design):** `admin-screens.jsx → AdminReports()`.
**Purpose:** Pre-built report templates with one-click export, plus a flexible "quick export" picker for period + format.

#### User stories
- As an **admin**, I can run any of the 6 standard reports and download as CSV.
- As an **admin**, I can run a quick custom export by picking a period and format (CSV / XLSX / PDF).
- As an **admin**, I see when each report was last refreshed.

#### UI — Layout
1. **Topbar:** title `Reports`, subtitle `Standard exports · custom queries`.
2. **Lane header** `01 · Standard reports` with action `Custom report`.
3. **Report grid** — 3 columns, 16 px gap. Each `<Card accent>`:
   - Top row: 40 × 40 colored icon tile (accent bg @ 14%, accent fg, 9 px radius) + `READY` chip on the right.
   - Outfit 20/600 title (Revenue / Profit & loss / Attendance / Pending payments / Coach payouts / Waivers).
   - 13 px slate-500 description.
   - Bottom row: mono `Updated <date>` left, action buttons right: `View` (ghost) + `CSV` (dark, dl icon).
4. **Lane header** `02 · Quick exports`.
5. **Quick export card** (`<Card p=28>`) — single row with three controls:
   - **Period** select (e.g. May 2026 / April 2026 / Q2 2026 / FY 2025-26 / Custom range).
   - **Format** three pill buttons CSV / XLSX / PDF.
   - **Export** primary button (dl icon).

#### UI — Data displayed
| Card | Source |
|---|---|
| Revenue | aggregation from `Payment` |
| Profit & loss | revenue − coach payouts − expenses |
| Attendance | `Attendance` roll-up |
| Pending payments | `Payment where status ∈ pending,failed,overdue` |
| Coach payouts | `Payout` |
| Waivers | `WaiverSignature` joined with `Waiver` |

#### UI — Interactions
- Click `View` → opens an in-page sheet preview of the report (a table view paginated).
- Click `CSV` → triggers download immediately.
- Custom report → opens a query builder (out of scope for this doc; surface as a "Pro" / coming-soon button if the builder isn't ready).
- Quick export → triggers a single download per format. PDF format implies server-side rendering of a paginated report (Puppeteer / WeasyPrint).

#### UI — States
- Card showing `GENERATING…` chip while a snapshot is being rebuilt.
- Card error: red border + `FAILED · last attempt <date>`.

#### Backend (ideal)
- `GET /api/admin/reports` → `{ reports: [ {id, title, lastRefreshedAt, status} ] }`.
- `GET /api/admin/reports/{id}.csv?from=&to=` (also `.xlsx`, `.pdf`) — streams the report.
- `POST /api/admin/reports/{id}/refresh` — manually rebuild.

#### Permissions
- `admin`.

#### Side effects
- Long-running reports may go through a job queue; the UI polls.

#### Validation
- Format enum: `csv | xlsx | pdf`. Period: parseable.

#### ↪ Current backend mapping
- `GET /api/reports/revenue.csv` (dashboard_routes.py:285).
- `GET /api/reports/pending-payments.csv` (dashboard_routes.py:310).
- `GET /api/reports/attendance.csv` (dashboard_routes.py:332).
- `GET /api/reports/coach-payouts.csv` (dashboard_routes.py:352).
- `GET /api/reports/profit.csv` (dashboard_routes.py:373).
- `GET /api/reports/waivers.csv` (dashboard_routes.py:396).
- v2: `GET /api/v2/admin/reports/{report_name}.csv` (reports_routes.py:15) — generic.
- XLSX and PDF formats are **not yet supported**.

---

### 6.5 Sessions

**Persona / device / route:** Admin · desktop · `/admin/sessions`.
**Source (design):** `admin-screens.jsx → AdminSessions()`.
**Purpose:** Browse all sessions, see capacity / waitlist / revenue at a glance, and create new sessions.

#### User stories
- As an **admin**, I can see every session with its capacity, waitlist, fee, and monthly revenue.
- As an **admin**, I can create a new session and edit an existing one.
- As an **admin**, I can spot at-capacity sessions and ones close to closing.

#### UI — Layout
1. **Topbar:** title `Sessions`, subtitle `Active classes · capacity at a glance`.
2. **KPI strip:**
   - **Active sessions** `7`, accent `blue-600`, `Across 4 coaches`.
   - **At capacity** `2`, accent `#ef4444`, listing the names.
   - **Waitlist total** `9`, accent `volt-400`, `1 offer pending`.
   - **Open spots** `27`, accent `#10b981`, `Across 5 sessions`.
3. **Lane header** `01 · All sessions` with action button `New session` (primary, plus icon).
4. **Sessions grid** — 2 columns, 16 px gap. Each `<SessionCard>`:
   - Header row: mono level overline + Outfit 18/600 name + sub `day · time · Coach <name>`, with status chip on the right (`open` / `full` / `closing` / `paused`).
   - Capacity block: mono `CAPACITY` left, `enrolled/cap` right, 6 px bar tinted by status.
   - 3-column stats row (top border): `Fee / mo`, `Waitlist` (yellow if > 0), `Revenue / mo` (= fee × enrolled).

#### UI — Interactions
- Click card body → session detail page or modal: roster, attendance history, waitlist, edit form.
- `New session` → modal/form: name, level, coach (dropdown), days (multi-select), start/end time, capacity, fee, fee cycle, description.
- Quick actions per card (`⋯`): Edit · Pause · Duplicate · Cancel.
- Drag to reorder? — Not in the design. Skip.

#### UI — Data displayed
| Visible | Source |
|---|---|
| Session name, level, day, time, coach | `Session` + `Coach.name` |
| Capacity bar | `enrolled / capacity` |
| Status chip | `Session.status` (derived) |
| Fee/mo | `Session.fee` formatted |
| Waitlist count | `count(Enrollment where sessionId=… AND status="waitlist")` |
| Revenue/mo | `fee × enrolled` (estimate; the real number must come from `Payment` aggregates for the active cycle if needed) |

#### Backend (ideal)
- `GET /api/admin/sessions` → list with computed `enrolledCount`, `waitlistCount`, `status`.
- `POST /api/admin/sessions` body `{ name, coachId, days[], startTime, endTime, level, capacity, fee, feeCycle, description? }`.
- `GET /api/admin/sessions/{id}` → with roster, recent attendance, waitlist.
- `PATCH /api/admin/sessions/{id}`.
- `DELETE /api/admin/sessions/{id}` (soft delete if it has enrollments).
- `POST /api/admin/sessions/{id}/pause` body `{ reason?, until? }`.
- `POST /api/admin/sessions/{id}/duplicate`.

#### Permissions
- `admin` only.

#### Side effects
- Pausing a session pauses all enrollments and stops billing for that cycle.
- Cancelling triggers refund flow for paid-but-future enrollments.

#### Validation
- Coach exists. Days non-empty. Time range valid. Capacity > 0. Fee ≥ 0.
- Cannot reduce capacity below enrolled count.

#### ↪ Current backend mapping
- `GET /api/sessions` (sessions_routes.py:110), `POST /api/sessions` (130), `PATCH` (161), `DELETE` (171), `POST .../cancel` (179).
- v2: `GET /api/v2/admin/sessions` (sessions_routes.py:33), `POST` (49), `DELETE` (61).
- Duplicate not implemented.

---

### 6.6 Coach payouts

**Persona / device / route:** Admin · desktop · `/admin/payouts`.
**Source (design):** `admin-screens.jsx → AdminPayouts()`.
**Purpose:** Calculate, approve, and pay each coach's payout for the current period. Show YTD trends.

#### User stories
- As an **admin**, I can see what each coach is owed this month and the formula used.
- As an **admin**, I can approve and mark paid individually or in bulk.
- As an **admin**, I can see YTD payouts and how April closed.

#### UI — Layout
1. **Topbar:** title `Coach payouts`, subtitle `May 2026 · ending May 31`.
2. **KPI strip:**
   - **May payouts · est** `₹1.18L`, accent `#7c3aed`, `Across 4 coaches`.
   - **Pending approval** `4`, accent `volt-400`, `Ready by May 31`.
   - **April · paid** `₹1.09L`, `Closed Apr 30`.
   - **YTD payouts** `₹5.84L`, `20.7% of revenue`.
3. **Lane header** `01 · May 2026 · pending approval` with action `Approve all` (primary, check icon).
4. **Payout rows** (`<Card p=0>`, one row per coach):
   - 5-column grid `1.5fr / 1fr / 1fr / 1fr / 200px`:
     - **Col 1:** `<Avatar size=48>` + Outfit 16/600 coach name + sub `<sessions> sessions · <students> students`.
     - **Col 2:** mono overline `Basis · rate`, Manrope 13/600 basis (Revenue % / Per class / Per student), mono sub showing the actual rate.
     - **Col 3:** mono overline `Collected`, Outfit 18/700 amount, mono `vs ₹<expected> EXP`.
     - **Col 4:** mono overline `Payout · May`, Outfit 22/700 in blue-600.
     - **Col 5:** `<Button variant=secondary size=sm>View formula</Button>` + `<Button variant=primary size=sm>Approve</Button>`.

#### UI — Data displayed
| Visible | Source |
|---|---|
| Coach name, sessions, students | `Coach` |
| Basis · rate | `Coach.basis` + `Coach.rate` |
| Collected | `Payout.collectedRevenue` for the current period |
| Expected revenue | `Payout.expectedRevenue` |
| Payout amount | `Payout.expectedPayout` or `collectedPayout` (see open question) |
| Approved / paid | `Payout.approved` / `Payout.paid` |

#### UI — Interactions
- `View formula` → modal showing the calculation: e.g. "Collected revenue ₹1,84,200 × 18% = ₹33,156". For Per-class basis: "₹1,500 × 24 classes = ₹36,000". For Per-student: "₹250 × 42 students = ₹10,500".
- `Approve` → marks the row approved; the button switches to `Mark paid`.
- `Approve all` → bulk approves all unapproved.
- `Mark paid` → confirm modal to record method (Bank transfer / UPI / Cash) and optional reference number.
- Click into a coach row → coach detail page with full payout history.

#### UI — States
- All approved & paid: row shows two chips `APPROVED` + `PAID` and a `View slip` link instead of action buttons.
- Period not yet closed: badge `EST · CLOSES MAY 31`.

#### Backend (ideal)
- `GET /api/admin/payouts?period=2026-05` → `Payout[]`.
- `POST /api/admin/payouts/calculate?period=...` → re-runs the calculation for the period (idempotent).
- `POST /api/admin/payouts/{id}/approve`.
- `POST /api/admin/payouts/{id}/undo-approve`.
- `POST /api/admin/payouts/{id}/mark-paid` body `{ method, ref?, paidAt? }`.
- `POST /api/admin/payouts/{id}/undo-paid`.
- `GET /api/admin/payouts/{coachId}/payslip?period=...` → PDF.
- `GET /api/admin/payout-rules`, `POST /api/admin/payout-rules` for the global rules.

#### Permissions
- `admin` only.

#### Side effects
- Approve writes audit log.
- Mark paid creates an `Expense` record categorised as `coach payout` (so the Expenses page reflects it).

#### Validation
- Cannot mark paid without approve. Cannot approve a period that isn't closed unless an "Allow early payout" toggle is on in Settings.

#### ↪ Current backend mapping
- `GET /api/coach-payouts` (finance_routes.py:670).
- `POST /api/coach-payouts/{pid}/approve` (693).
- `POST /api/coach-payouts/{pid}/mark-paid` (710).
- `POST /api/coach-payouts/{pid}/undo-paid` (491).
- `POST /api/coach-payouts/{pid}/undo-approve` (512).
- `POST /api/coach-payouts/calculate` (602).
- `GET /api/coach-payouts/{coach_id}/payslip` (extras_routes.py:89).
- `GET /api/payout-rules` / `POST /api/payout-rules` (569 / 584).
- v2: `GET /api/v2/admin/finance/payouts` (billing_routes.py:233).

---

### 6.7 Students

**Persona / device / route:** Admin · desktop · `/admin/students?filter=<>&level=<>`.
**Source (design):** `admin-ops-screens.jsx → AdminStudents()`.
**Purpose:** Student directory with filters by status (All / New / At risk / Paused) and level, plus attendance visualization per row.

#### User stories
- As an **admin**, I can browse the full student roster.
- As an **admin**, I can filter to at-risk students (overdue / failed payments) or paused students.
- As an **admin**, I can see each student's 30-day attendance trend as a tiny bar chart.
- As an **admin**, I can add a new student directly (manual onboarding) or click into a student profile.

#### UI — Layout
1. **Topbar:** title `Students`, subtitle `Directory · 247 active · 4 paused`.
2. **KPI strip:**
   - **Active students** `X`, accent `blue-600`, sub `Across 7 sessions · 4 coaches`.
   - **New · this month** `Y`, accent `volt-400`, sub `+12% MoM growth`.
   - **Paused** `Z`, accent neutral, sub `Avg pause: 3.2 weeks`.
   - **Payment risk** `W`, accent `#ef4444`, sub `Overdue or failed`.
3. **Toolbar** (top of the wrapping Card):
   - Left: pills `All` / `New` / `At risk` / `Paused` (each with count) + vertical divider + level select (`All levels` / `Beginner` / `Intermediate` / `Advanced` / `Adult`).
   - Right: `<Button variant=secondary icon=dl>Export</Button>` + `<Button variant=primary icon=plus>Add student</Button>`.
4. **Table** columns: `Student | Parent | Session | Joined | Attendance · 30d | Payment | <chevron>`.
   - Student cell: `<Avatar 32>` + name (with optional `NEW` mono pill or `PAUSED` chip inline) + sub `Age N · <level>`.
   - Joined cell: mono uppercase month abbrev.
   - Attendance cell: `<AttendanceBar rate>` — a `<percentage>%` label color-coded (green > 90%, amber > 75%, red below) plus a row of 20 colored dot-cells representing the last 20 sessions.
   - Payment cell: `<Chip variant=payStatus>`.
5. **Footer:** mono `SHOWING N OF M · 247 ACADEMY TOTAL` + sort label `SORTED BY ENROLLMENT DATE · DESC`.

#### UI — Interactions
- Row click → student profile (`/admin/students/{id}`): personal info, contacts, enrollments history, attendance log, payment ledger, notes, waiver status.
- `Add student` → multi-step modal (parent search/create → student details → assign session → confirm).
- `Export` → CSV of the filtered set.
- The `NEW` pill is shown for students whose `joined` is within the current month.

#### UI — Data displayed
| Column | Source |
|---|---|
| Student name | `Student.name` |
| Age | derived from `Student.dateOfBirth` |
| Level | `Student.level` |
| Parent | `Parent.name` |
| Session | `Session.name.split(' · ')[0]` (display only the prefix) |
| Joined | `Student.joinedAt` (mon-yyyy) |
| Attendance · 30d | `attendance count last 30 days / sessions in window` |
| Payment | derived from latest `Payment.status` for the active cycle |

#### Backend (ideal)
- `GET /api/admin/students?filter=&level=&q=&page=&pageSize=`.
- `POST /api/admin/students` body `{ name, dateOfBirth, level, parentId or newParent: {name, email, phone}, sessionIds[] }`.
- `GET /api/admin/students/{id}` → full profile.
- `PATCH /api/admin/students/{id}`.
- `DELETE /api/admin/students/{id}` (soft delete).
- `GET /api/admin/students/{id}/attendance?from=&to=`.
- `GET /api/admin/students/{id}/payments`.

#### Permissions
- `admin` only.

#### Side effects
- Create-with-newParent provisions a `Parent` and a Firebase user invite.
- Soft delete unlinks from sessions but retains historical attendance/payment records.

#### ↪ Current backend mapping
- Legacy: `GET /api/students` (sessions_routes.py:226), `POST` (197), `GET /{sid}` (298), `PATCH` (312), `DELETE` (329).
- v2: `GET /api/v2/admin/students` (directory_routes.py:57).

---

### 6.8 Enrollments

**Persona / device / route:** Admin · desktop · `/admin/enrollments`.
**Source (design):** `admin-ops-screens.jsx → AdminEnrollments()`.
**Purpose:** Approval queue for newly-submitted enrollments. Each row shows whether waiver + payment are complete; admin approves or nudges.

#### User stories
- As an **admin**, I can see every enrollment pending review with its status (ready / blocked).
- As an **admin**, I can approve a ready enrollment in one click, or nudge the parent for missing waiver/payment.
- As an **admin**, I can bulk-approve all "ready" rows and bulk-decline all "blocked" rows.
- As an **admin**, I see recent decisions (approved/declined) in a timeline.

#### UI — Layout
1. **Topbar:** title `Enrollments`, subtitle `Pending approvals · today`.
2. **KPI strip:**
   - **Pending review** `N`, accent `#f59e0b`, sub `Oldest: 2 days`.
   - **Ready to approve** `K`, accent `#10b981`, sub `Waiver + payment OK`.
   - **Blocked** `M`, accent `#ef4444`, sub `Missing waiver or payment`.
   - **Approval rate · 30d** `96%`, neutral, sub `27 of 28 approved`.
3. **Lane header** `01 · Awaiting review` with action group: `Decline all blocked` (secondary) + `Approve all ready` (primary, check icon).
4. **Pending enrollment list** — each item an `<EnrollmentRow>` Card (with `accent=#10b981` if ready, `#f59e0b` if not):
   - 4-column grid `1.6fr / 1.4fr / 220px / 200px`:
     - **Col 1:** `<Avatar 48>` + Outfit 16/600 student name + `Parent: <name>` + mono `SUBMITTED <when>` (uppercase).
     - **Col 2:** mono overline `Requested session`, Manrope 14/600 session name, slate sub `Coach <X> · ₹<fee>/mo`.
     - **Col 3:** stacked status rows. Each row: a 16 × 16 round status icon (green/red bg with check/x) + Manrope 12/600 label. Three rows: `Waiver signed`/`pending`, `₹<fee> received`/`Awaiting payment`, `Spot available` (always true here, otherwise it would be on the waitlist).
     - **Col 4:** vertical button stack:
       - If ready: `Approve` (primary, full) + `Decline` (ghost, full).
       - If blocked: `Nudge parent` (secondary, msg icon, full) + `View details` (ghost, full).
5. **Lane header** `02 · Recent decisions`.
6. **Recent decisions list** — `<Card p=0>`, one row per recent decision: `<Avatar 32>` + name + parent + session, status chip `APPROVED` (enrolled) / `DECLINED` (failed), right-aligned mono datetime.

#### UI — Data displayed
| Column | Source |
|---|---|
| Pending review | `Enrollment.status = "pending"` |
| Student name | `Student.name` |
| Parent | `Parent.name` |
| Session name | `Session.name` |
| Submitted | `Enrollment.submittedAt` (relative) |
| Waiver | `Enrollment.waiverSigned` |
| Payment | `Enrollment.paymentStatus` |
| Approval rate · 30d | over `Enrollment` decisions in last 30d |

#### Backend (ideal)
- `GET /api/admin/enrollments?status=pending`.
- `POST /api/admin/enrollments/{id}/approve` body `{ note? }`.
- `POST /api/admin/enrollments/{id}/decline` body `{ reason }`.
- `POST /api/admin/enrollments/{id}/nudge` body `{ channel, templateId, customBody? }`.
- `POST /api/admin/enrollments/bulk-approve` body `{ ids[] }`.
- `POST /api/admin/enrollments/bulk-decline` body `{ ids[], reason }`.

#### Permissions
- `admin` only.

#### Side effects
- Approve → updates `Enrollment.status = "enrolled"`, attaches the student to the session, triggers welcome email, recalculates session `enrolledCount`.
- Decline → updates status, triggers a parent notification.
- Bulk approve fans out N approve calls (in a transaction or job).

#### Validation
- Approve allowed only if `waiverSigned && paymentStatus !== "failed"` (or admin force-approves with explicit flag).
- Decline requires reason text.

#### ↪ Current backend mapping
- `POST /api/enrollments` (sessions_routes.py:343), `GET /api/enrollments` (378), `POST .../cancel` (412), `POST .../approve` (435), `POST .../transfer` (450), `POST .../pause-month` (504), `POST .../resume-month` (530).
- `GET /api/enrollments/pending-approval` (extras_routes.py:179).
- v2: `DELETE /api/v2/admin/enrollments/{id}` (sessions_routes.py:116), `POST .../transfer` (127), `POST .../pause` (152), `POST .../resume` (163).
- Decline / nudge / bulk-decline endpoints: **none today**. **New endpoints required.**

---

### 6.9 Waitlist

**Persona / device / route:** Admin · desktop · `/admin/waitlist`.
**Source (design):** `admin-ops-screens.jsx → AdminWaitlist()`.
**Purpose:** Manage the waitlist queue per session, send offers, set policy (expiry, ordering, notifications).

#### User stories
- As an **admin**, I can see who is on the waitlist for which session, in order.
- As an **admin**, I can offer the top spot, send manual offers, or revoke an offer.
- As an **admin**, I can configure the offer expiry, ordering rule (FIFO / sibling-priority), and notification channels.

#### UI — Layout
1. **Topbar:** title `Waitlist`, subtitle `Per-session queue · offer policy`.
2. **KPI strip:**
   - **Total waitlisted** `N`, accent `volt-400`.
   - **Offers pending** `K`, accent `blue-600`, `Auto-expire in 48h`.
   - **Acceptance rate** `71%`, `Last 90 days`.
   - **Avg wait time** `14d`, `Until spot offered`.
3. **Lane header** `01 · By session` with action `Manual add` (secondary, plus icon).
4. **Per-session cards** (`<Card p=0>`):
   - Header (18 × 22 padding, bottom border): mono `Session`, Outfit 18/600 session name, sub `12 / 12 enrolled · N waiting`. Right: `<Button variant=secondary size=sm>Add capacity</Button>` + `<Button variant=primary size=sm icon=arrow>Offer top spot</Button>`.
   - Rows: 5-column grid `60px / 1fr / 200px / 200px / 180px`:
     - Position chip (44 × 44 square, radius 10, mono Outfit 20/700, bg `volt-50` if offered, `slate-100` otherwise).
     - `<Avatar 32>` + student name + parent.
     - mono overline `Joined queue` + date.
     - If offered: mono overline `Offer expires` (in `#a16207`) + Outfit 20/700 countdown (`46:12:08` hh:mm:ss). If not: mono `Status` + `<Chip variant=waitlist>`.
     - Right buttons: if offered `Resend` (secondary) + `Revoke` (ghost). If queued `Remove` (ghost) + `Send offer` (primary).
5. **Lane header** `02 · Offer policy` (mt=40).
6. **Policy card** (`<Card p=28>`) — 3-column grid:
   - **Auto-offer expiry** `48h`, sub explanation.
   - **Order rule** `FIFO`, sub.
   - **Notification** `SMS + email`, sub.

#### UI — Interactions
- `Send offer` (per row) → fires the offer email + SMS + push, sets `Enrollment.status=offered`, `offerExpiresAt = now + policy.expiry`, starts a countdown.
- `Resend` re-sends without resetting the timer.
- `Revoke` cancels the offer (back to `waitlist`), opens the spot to the next person if auto.
- `Offer top spot` (session header) → equivalent to `Send offer` for the top of that session's queue.
- `Add capacity` → modal increments `Session.capacity` by N (default 1), confirm with reason.
- `Manual add` → modal: select session + parent/student (search or create new) → adds at the back of the queue.
- Policy controls → live edits to `WaitlistPolicy` (per academy or per session). The design shows them as read-only display; treat them as editable in production.

#### UI — Data displayed
| Visible | Source |
|---|---|
| Position | `rank by Enrollment.submittedAt where status=waitlist or offered` |
| Joined queue | `Enrollment.submittedAt` |
| Offered, expires | `Enrollment.offeredAt`, `offerExpiresAt` |
| Acceptance rate | enrollments transitioning offered→enrolled / total offers in last 90d |

#### Backend (ideal)
- `GET /api/admin/waitlist?sessionId=` → per session.
- `POST /api/admin/waitlist/{enrollmentId}/offer` body `{ expiresInHours? }`.
- `POST /api/admin/waitlist/{enrollmentId}/revoke`.
- `POST /api/admin/waitlist/{enrollmentId}/resend`.
- `POST /api/admin/waitlist` body `{ sessionId, studentId }`.
- `GET /api/admin/waitlist/policy`, `PATCH /api/admin/waitlist/policy` body `{ expiryHours, orderRule, channels[] }`.
- `POST /api/admin/sessions/{id}/increase-capacity` body `{ by: 1, reason }`.

#### Permissions
- `admin` only.

#### Side effects
- Offering emits SMS+email+push (per policy). Expiry timer scheduled.
- On expiry: auto-revoke and offer next if `policy.autoNext = true`.

#### Validation
- Cannot offer if session has open spots (would be a direct enroll, not an offer).
- Expiry > 0.

#### ↪ Current backend mapping
- `GET /api/waitlist` (waitlist_routes.py:58), `POST /api/waitlist` (72), `GET /api/admin/waitlist` (98), `POST .../enroll` (175), `POST .../skip` (240), `DELETE` (268), `POST /api/waitlist/{wid}/enroll` (299).
- v2: `GET /api/v2/admin/waitlist` (waitlist_routes.py:20), `POST .../sessions/{session_id}/waitlist/promote` (92), `POST .../waitlist/{waitlist_id}/skip` (102), `DELETE` (111).
- Offer / revoke / resend / policy endpoints — **not present**. **New endpoints required.**

---

### 6.10 Expenses

**Persona / device / route:** Admin · desktop · `/admin/expenses?cat=<>`.
**Source (design):** `admin-ops-screens.jsx → AdminExpenses()`.
**Purpose:** Record and review academy expenses; visualize category mix; export.

#### User stories
- As an **admin**, I can record a new expense (date, vendor, category, amount, recurring tag, note).
- As an **admin**, I can filter the ledger by category.
- As an **admin**, I can see what proportion of spend is fixed vs variable.
- As an **admin**, I can export the ledger to CSV.

#### UI — Layout
1. **Topbar:** title `Expenses`, subtitle `Ledger · category breakdown`.
2. **KPI strip:**
   - **May spend** `₹X K`, accent `slate-900`, sub `N transactions`.
   - **Fixed costs** `₹Y K`, accent `blue-600`, sub `Court rent · utilities · ins.`.
   - **Variable** `₹Z K`, accent `volt-400`, sub `Equipment · marketing`.
   - **vs April** `₹14.0K` with `+7%` delta (neg), accent `#10b981`, sub `Above budget by ₹4K`.
3. **Lane header** `01 · Category breakdown · May`.
4. **Stacked-bar card** (`<Card p=28>`): 14 px tall stacked horizontal bar with category-colored segments (Court rent blue, Equipment volt, Coach payout purple, Marketing pink, Utilities cyan, Fees slate, Insurance green). Below it: 4-column grid of category legends (`<color square> Name · ₹amount · pct%`).
5. **Ledger card** (`<Card p=0>`):
   - **Toolbar:** category filter pills (each with a colored dot prefix and a count chip); right side `Export` (secondary, dl) + `Record expense` (primary, plus).
   - **Table:** `Date | Category | Vendor / Note | Method | Amount (right, mono, with "−" prefix) | <more>`. Category cell renders a colored "pill" with the category name and dot. Vendor cell shows the vendor + optional `RECURRING` mono pill in `blue-50`/`blue-700`. Note shown below in slate-500.
   - **Total row** at the bottom: bg `slate-50`, mono `TOTAL · N items`, right-aligned summed amount with `−₹` prefix.

#### UI — Components
- `<KpiCard>`, `<Chip>`, `<Button>`, plus expense-specific stacked bar.

#### UI — Data displayed
| Visible | Source |
|---|---|
| Categories | `EXPENSE_CATEGORIES` constant (Court rent, Equipment, Coach payout, Marketing, Utilities, Fees, Insurance) |
| Row data | `Expense` fields |
| Recurring badge | `Expense.recurring` |

#### Backend (ideal)
- `GET /api/admin/expenses?cat=&from=&to=`.
- `POST /api/admin/expenses` body `{ date, vendor, category, amount, method, recurring, recurringCadence?, note?, attachmentUrl? }`.
- `PATCH /api/admin/expenses/{id}`.
- `DELETE /api/admin/expenses/{id}` (soft delete).
- `GET /api/admin/expenses/category-breakdown?from=&to=`.

#### Permissions
- `admin` only.

#### Side effects
- Recurring expenses with `cadence=monthly` should auto-create next month's row at month start (cron job).
- Coach payout expenses are created automatically when a payout is marked paid in §6.6.

#### Validation
- Amount > 0. Date valid. Category in enum. If `recurring`, `cadence` required.

#### ↪ Current backend mapping
- `GET /api/expenses` (finance_routes.py:529), `POST` (539), `PATCH` (552), `DELETE` (560).
- v2: `GET /api/v2/admin/finance/expenses` (billing_routes.py:254), `POST` (274).

---

### 6.11 Messages

**Persona / device / route:** Admin · desktop · `/admin/messages?thread=<id>`.
**Source (design):** `admin-comms-screens.jsx → AdminMessages()`.
**Purpose:** Two-pane inbox for admin↔parent and admin↔coach communications. Templates supported. Broadcast announcements separate (see Announcements section below).

#### User stories
- As an **admin**, I can see all unread, parent, coach, urgent threads.
- As an **admin**, I can read and reply to any thread.
- As an **admin**, I can use templates (Payment reminder, Make-up offer, Welcome, Final notice).
- As an **admin**, I can send broadcast announcements (e.g. "May newsletter") to all parents.

#### UI — Layout
- **Outer:** `<Card>` with a 340 px left thread list and a flex-1 conversation pane; outer height `calc(100vh - 100px)`; the topbar lives outside, padded but matched.
1. **Thread list (left pane):**
   - Header: mono overline `Inbox · N`, right + button (volt-yellow square with plus icon — new conversation).
   - Filter pills row: `All` / `Unread` / `Parents` / `Coaches`.
   - Each thread item: `<Avatar 32>` + name + mono right-aligned time. Below the name a mono uppercase persona tag (`PARENT` in blue-50, `COACH` in volt-50) + optional 6 × 6 red dot if urgent. Then subject (12.5 px, bold if unread). Then preview line (12 slate-500 ellipsized) and unread count blue circle (mono 9/700).
   - Active thread item: bg `#f8fafc` and left border 3 px volt-yellow.
2. **Conversation pane (right):**
   - Header (white, bottom border): `<Avatar 40>` + Outfit 17/600 name + persona tag + subject sub. Right: `View profile` (secondary) + `<Icon.more>` ghost.
   - Messages area (slate-50/100 bg): bubbles, "me" (slate-900 bg, white text, bottom-right corner squared off to 3 px) align right, "them" (white bg, slate border, bottom-left squared) align left. Below each bubble a mono uppercase timestamp.
   - Composer (white, top border):
     - Templates row: mono overline `Templates` + 4 small pill buttons (Payment reminder / Make-up offer / Welcome / Final notice). Click pill → inserts template body into the textarea.
     - Textarea (slate-200 border, 8 px radius), min height 48 px.
     - Bottom row: left icon buttons (`Icon.plus` attach, `Icon.calendar` schedule, `Icon.spark` AI assist?). Right: `Save draft` (secondary) + `Send · ⌘↵` (primary, arrow icon).
3. **Announcements** (not visually shown in the inbox pane but referenced in `ANNOUNCEMENTS`):
   - Should be accessible from the inbox header (e.g. a tab `Announcements` next to `Inbox`).
   - Each announcement: title, sent date, audience, open rate. Compose announcement form: subject, body (rich text), audience selector, channels.

#### UI — Data displayed
| Visible | Source |
|---|---|
| Thread name (parent/coach) | `User.name` |
| Subject | `Thread.subject` |
| Preview | `last message.body` truncated |
| Time | `lastMessageAt` |
| Unread count | per-thread `messages where readBy ∌ me` count |
| Persona tag | `Thread.kind` |
| Messages list | `Thread.messages[]` |
| Templates | `MessageTemplate[]` |

#### UI — Interactions
- Thread click → loads message history; marks all as read on entry.
- Send → POSTs the message, optimistically appends.
- Save draft → persists locally to the thread record.
- Schedule (calendar icon) → opens a date/time picker; message will be sent at that time.
- Compose new (top-right plus) → modal: search for recipient, subject, body.

#### UI — States
- No threads → empty card with `Start a conversation` CTA.
- No selected thread → right pane empty placeholder.

#### Backend (ideal)
- `GET /api/admin/threads?filter=&q=` → list.
- `GET /api/admin/threads/{id}` → full thread with messages.
- `POST /api/admin/threads/{id}/messages` body `{ body, attachments? }`.
- `POST /api/admin/threads` body `{ recipientUserId, subject, body }`.
- `PATCH /api/admin/threads/{id}/read`.
- `GET /api/admin/templates`.
- `POST /api/admin/announcements` body `{ subject, body, audience, channels[], scheduleAt? }`.
- `GET /api/admin/announcements` → list with open rates.

#### Permissions
- Admins can DM any user. Coaches/parents are restricted (see §4.8).

#### Side effects
- New message triggers a notification (in-app push) for the recipient. Email/SMS based on user preference and Settings.

#### ↪ Current backend mapping
- `GET /api/messages/contacts` (comms_routes.py:84), `GET /api/messages/threads` (106), `GET /api/messages/thread/{other_user_id}` (137), `POST /api/messages` (158).
- `GET /api/notifications` (192), `PATCH /api/notifications/{nid}/read` (202), `POST /api/notifications/read-all` (212).
- v2: `GET /api/v2/admin/messages` (comms_routes.py:20), `POST .../broadcast` (41), `POST .../dm` (58).
- Templates / announcements with open-rate tracking — **partially or not present**; broadcast exists but no engagement metrics.

---

### 6.12 Waivers

**Persona / device / route:** Admin · desktop · `/admin/waivers`.
**Source (design):** `admin-comms-screens.jsx → AdminWaivers()`.
**Purpose:** Manage the academy's waiver document (current version + history) and track per-student signing status.

#### User stories
- As an **admin**, I can see the current waiver, its adoption rate, and its version history.
- As an **admin**, I can publish a new version, which triggers re-sign requests.
- As an **admin**, I can see who has signed, who hasn't, who is on an outdated version, and who is expiring soon.
- As an **admin**, I can send signature reminders in bulk.

#### UI — Layout
1. **Topbar:** title `Waivers`, subtitle `Liability & media release · v3.1 · 2024 edition`.
2. **KPI strip:**
   - **Signed · current** `N`, accent `#10b981`, sub `98.4% of active students`.
   - **Pending signature** `K`, accent `#f59e0b`, sub `Blocks first session`.
   - **Expiring · 30d** `M`, accent `volt-400`, sub `Auto-renewal reminders sent`.
   - **Outdated version** `O`, accent neutral, sub `Pre-v3.1 · re-sign optional`.
3. **Lane header** `01 · Current waiver · version control` with action `Download PDF` (secondary, dl).
4. **Two-column row** (`1.4fr 1fr`):
   - **Active doc card:** big "v3.1" cover tile (56 × 72, slate-900 bg, volt yellow accent bar + Outfit 22/700 version), title `Liability & media release · 2024 edition`, description, footer with `Effective`, `Last edited`, `Adoption` mini-stats.
   - **Version history card:** mono overline `Version history` + a timeline list of versions: dot (green for current, slate for old) + line connector + version label + chip `CURRENT` + date + note.
5. **Lane header** `02 · Per-student status` with action `Remind all pending` (primary, msg icon).
6. **Signing status table:** columns `Student · Parent | Version (mono) | Signed | Method | Expires | Status | <action>`.
   - Status chips: `SIGNED` (enrolled), `PENDING` (pending), `EXPIRING` (pending in `#a16207`), `OUTDATED` (paused).
   - Action: `Send` (primary) for pending, `Renew` (secondary) for expiring, `View` (ghost) otherwise.

#### UI — Data displayed
| Visible | Source |
|---|---|
| Current version | `Waiver where active=true` (latest by version) |
| Adoption | `count(WaiverSignature where waiverId=current) / count(active Students)` |
| Signed date / method / expires | `WaiverSignature` |
| Status | derived: signed (current and not expired), pending (no signature), expiring (within 30d of expiry), outdated (signed an older version) |

#### Backend (ideal)
- `GET /api/admin/waivers` → list versions + adoption.
- `POST /api/admin/waivers` body `{ title, body, version }`.
- `PATCH /api/admin/waivers/{id}` (edit drafts only).
- `POST /api/admin/waivers/{id}/publish`.
- `GET /api/admin/waivers/{id}.pdf`.
- `GET /api/admin/waiver-signatures?status=`.
- `POST /api/admin/waiver-signatures/{id}/remind`.
- `POST /api/admin/waiver-signatures/bulk-remind` body `{ status: "pending"|"expiring" }`.

#### Permissions
- `admin` only for waiver CRUD; parents sign via §8.5 (registration step 5) or a re-sign link.

#### Side effects
- Publishing a new version: invalidates active signatures (or marks them outdated, configurable) and triggers re-sign emails.

#### ↪ Current backend mapping
- `GET /api/waiver/current` (onboarding_routes.py:179) — fetch current.
- v2: `GET /api/v2/admin/waivers` (waiver_routes.py:24).
- Publish / per-student signature CRUD / bulk-remind: **not present**. **New endpoints required.**

---

### 6.13 Settings

**Persona / device / route:** Admin · desktop · `/admin/settings/{section}`.
**Source (design):** `admin-comms-screens.jsx → AdminSettings()` and sub-panels.
**Purpose:** Centralised academy configuration with 7 sections.

#### UI — Layout
- **Two-column:** 260 px sticky left nav + content panel.
- **Left nav** (`SETTINGS_NAV`): mono overline `Configuration`, then 7 button items each with label + 11 px slate-500 description. Active item: white bg, slate-200 border, left border 3 px volt-yellow.
- **Right panel:** common `<PanelHead index title sub>` (blue mono overline `SETTINGS · NN`, Outfit 26 h2, slate sub) + a series of `<Field label hint>` rows (180 px label column, content column, bottom hairline divider).
- Common save bar (`Cancel` ghost + `Save changes` primary), top border, right-aligned.

#### Sections

##### 6.13.1 Academy details
- Fields: Academy name, Tagline, Location, Contact email, Contact phone, Timezone (select), Currency (select).
- Source mapping: `Academy` entity.

##### 6.13.2 Fee structures
- Per-session fee table (one row per session: name, fee input with ₹ prefix, "Inc. GST" / "No GST" indicator, Edit link).
- Fields:
  - Sibling discount (`%` input + label "off second+ child").
  - Annual prepay discount (`%` input + label "off total").
  - Late fee (₹ input + label "flat · per occurrence").
  - GST registration (toggle `REGISTERED` / `NOT REGISTERED`).
- Source mapping: `Session.fee` and a new `AcademyBilling` rules object.

##### 6.13.3 Payment gateway
- "Connected providers" grid (2 cols): each provider card (Stripe, Razorpay UPI, Bank transfer, GoCardless) — name + detail + connected chip + account stub.
- Fields:
  - Default payment method (select).
  - Autopay default (toggle "OPT-IN BY DEFAULT" / "OPT-OUT").
  - Autopay retry (select: 1 / 2 / 3 retries with intervals).
  - Receipts (toggle AUTO-SEND / DISABLED).
- Connect / disconnect actions are implied per provider card.

##### 6.13.4 Notifications
- Trigger × channels table (Enrollment received, Payment failed, Class cancelled, Waitlist offer, Attendance daily, Coach payout ready, Monthly invoice) × (SMS / Email / Push) with `<Check>` cells (slate-900 box with volt check or empty box). Audience column on the right.
- Fields:
  - Quiet hours (start–end time inputs).
  - Throttle (max notifications per parent per day, int).
- The design notes SMS=Twilio, Email=Postmark, Push=Firebase — these are global infra choices, not user-configurable here.

##### 6.13.5 Roles & access
- "Invite member" primary button.
- Team list table: `<Avatar 34>` + name/email + role select dropdown (Owner / Admin · Full / Admin · Limited / Coach · Senior / Coach) + last-active mono caption + Remove (red text button).

##### 6.13.6 Branding
- Logo (64 × 64 preview + Replace button + filename caption).
- Accent color (5 swatches; first one selected with thick slate-900 border).
- Court accent (4 swatches; volt-yellow default).
- Email signature (textarea, defaults to "— The Rally Academy Team / Court 7 · Northside · Bengaluru / rallyacademy.in").

##### 6.13.7 Data & exports
- Last backup field: chip `HEALTHY` + mono datetime + sub.
- Manual export: 3 buttons `Students CSV`, `Payments CSV`, `Full archive · ZIP`.
- Data retention select (12mo / 36mo / 84mo statutory / Indefinite).
- Account deletion: red `Delete academy…` button (with confirmation flow).

#### Backend (ideal)
- `GET /api/admin/settings` and `PATCH /api/admin/settings` covering all sections.
- For granularity, also expose section-scoped endpoints:
  - `GET/PATCH /api/admin/settings/academy`
  - `GET/PATCH /api/admin/settings/fees`
  - `GET/PATCH /api/admin/settings/gateway`
  - `POST /api/admin/settings/gateway/{provider}/connect` and `.../disconnect`
  - `GET/PATCH /api/admin/settings/notifications`
  - `GET /api/admin/settings/team`, `POST /api/admin/team/invite`, `PATCH /api/admin/team/{userId}` (role), `DELETE /api/admin/team/{userId}`.
  - `GET/PATCH /api/admin/settings/branding`
  - `GET /api/admin/settings/data` (last backup, retention), `POST /api/admin/settings/data/export` (zip), `DELETE /api/admin/academy` (with safety word confirmation)

#### Permissions
- Settings are admin-only. Owner role required to:
  - Connect/disconnect gateways
  - Change roles for admins
  - Delete the academy

#### Side effects
- Changing fees does NOT retroactively change existing invoices.
- Connecting/disconnecting a gateway triggers an OAuth/credentials flow with the provider; webhook URLs update.
- Account deletion enqueues a job that purges data after a configurable cool-down (e.g. 30 days), with a "Restore" link in the meantime.

#### Validation
- Currency change requires confirmation if there are existing payments.
- Timezone change requires confirmation if there are scheduled jobs.
- Email signature: max 1000 chars; allow plain-text or limited Markdown.

#### ↪ Current backend mapping
- `GET /api/settings` (settings_routes.py:45), `PATCH /api/settings` (60), `POST /api/settings/payout-basis` (70).
- v2 academy: `GET /api/v2/admin/academy` (academy_routes.py:28), `PATCH` (37), `GET /api/v2/admin/academy/fees` (52), `GET /api/v2/admin/academy/gateway` (61), `PATCH .../fees` (70), `GET /api/v2/admin/academy/notifications` (85), `PATCH .../notifications` (94).
- Team CRUD: `GET /api/users` (auth_routes.py:597), `GET /api/users/{id}` (610), `PATCH /api/users/{id}` (620), `DELETE` (648), invites via `POST /api/invites` (482). v2: `GET /api/v2/admin/users` (directory_routes.py:26), `PATCH .../role` (36).
- Branding, data retention, account deletion: **not present**. **New endpoints required.**

---

## 7. Coach (mobile)

**Persona:** `coach` role.
**Device:** Mobile / PWA. Reference frame 402 × 874 px (iPhone class). Dark surface (`#06080d`), high contrast for gym lighting.
**Source files:** `coach.html`, `assets/coach-screens.jsx`.

The coach app is a single-page mobile shell with a sticky bottom tab bar and (for attendance) a sticky bottom save bar. The entire surface is dark.

### 7.0 Coach shell (top bar + tab bar)

#### UI — CoachTopBar
- Padding `8 / 18 / 16 / 18`. Bottom hairline `1px solid rgba(255,255,255,0.06)`.
- **Left:** if `onBack` callback present → 40 × 40 rounded square button (bg `rgba(255,255,255,0.06)`, `Icon.arrowL(20, white)`); otherwise show identity block:
  - Mono uppercase eyebrow `● ON COURT` in `volt-400` (10/700 letter-spaced 0.2em).
  - Outfit 22/600 title (e.g. "Hey, Coach Arjun").
  - Optional Manrope 12/`#94a3b8` sub (e.g. "Tuesday · May 17 · 4 sessions today").
- **Right:** custom right slot. On Today, it's a 40 × 40 bell button with a 6 × 6 volt-yellow dot for unread notifications. On Take Attendance, it's a `MARK ALL PRESENT` mono pill button (8 × 14 padding).

#### UI — CoachTabBar
- Position `absolute bottom: 0 left:0 right:0`, padding `12 / 14 / 30 / 14` (extra bottom for iOS home indicator).
- Background `rgba(6,8,13,0.95)` with `backdrop-filter: blur(16px)`, top hairline `1px solid rgba(255,255,255,0.06)`.
- 4 tabs evenly spaced: **Today** (`home` icon), **Sessions** (`calendar`), **Roster** (`list`), **Payout** (`pay`).
- Active tab: icon and label in `volt-400`; inactive in `#64748b`. Active also shows a 24 × 3 px volt-yellow underbar 12 px above the icon.
- Label: mono 10/700 uppercase, letter-spacing 0.1em.

#### Shell-level behaviors
- Bell button → opens notification sheet (slides up from bottom, dark surface).
- Tab navigation is instantaneous (no transitions).
- Offline indicator (when applicable) shows above the top bar as a thin volt-tinted strip "OFFLINE · LAST SYNCED hh:mm" with auto-sync once back online (see §4.7).

#### Permissions
- All coach screens require `coach` role and a session ownership check.

---

### 7.1 Today

**Persona / device / route (proposed):** Coach · mobile · `/coach` (default landing).
**Source (design):** `coach-screens.jsx → CoachToday()`.
**Purpose:** At-a-glance overview of the coach's day: next session hero, full day's schedule, and month-to-date KPIs.

#### User stories
- As a **coach**, I see what's next within seconds of opening the app.
- As a **coach**, I can start attendance for the next session in one tap.
- As a **coach**, I can see today's remaining sessions and jump to any of them.
- As a **coach**, I can see how many classes I've held this month, my attendance rate, my expected payout, and my student count.

#### UI — Layout (scroll down through the dark surface)
1. **Top bar** with identity (see §7.0).
2. **"Next up" hero card** (padding 20, margin 20/18/0/18, radius 16, volt-tinted gradient bg `linear-gradient(135deg, rgba(250,204,21,0.15), rgba(250,204,21,0.04))`, 1 px border in `rgba(250,204,21,0.3)`):
   - Decorative `<CourtLines>` 200 × 80 px at top-right with 0.4 opacity.
   - Header row: mono `NEXT IN 12 MIN` (volt) on the left; on the right a volt pill `4:30 PM` (Outfit slate-900 on volt-400).
   - Outfit 26/600 session name `Junior Smash · U10`.
   - 13 / `#cbd5e1` sub `Court A · 12 of 12 enrolled · 60 min`.
   - Action row: primary "Start attendance" volt button (full flex, 14 padding, Outfit 15/700 slate-900 fg, arrow icon) + 50 × 50 secondary `Icon.list` button (transparent white border) → opens session detail.
3. **Today's schedule** section:
   - Header row: mono `TODAY'S SCHEDULE` overline (`#94a3b8`), hairline divider, mono `4` count (volt).
   - 4 schedule rows (padding 14, radius 12, bg `rgba(255,255,255,0.04)`, 1px border):
     - 56 × 56 left tile with Outfit 16/700 hour + mono 9/700 AM/PM. The current session has volt-yellow bg + slate fg; other sessions have `#0a0f1c` bg + slate fg.
     - Outfit 15/600 white session name.
     - 12/`#94a3b8` sub `Court X · N students`.
     - If `status="now"`: mono `● LIVE` volt chip on the right; the row uses volt-tinted bg `rgba(250,204,21,0.06)` and border `rgba(250,204,21,0.25)`.
4. **This month KPI tiles** (2-col grid, 8 px gap; padding 14, radius 12, left border 3 px accent):
   - `CLASSES HELD` `24` sub `of 28 scheduled` accent volt.
   - `PRESENT RATE` `91%` sub `across all sessions` accent green.
   - `EXP PAYOUT` `₹35.4K` sub `May · pending approval` accent blue.
   - `STUDENTS` `42` sub `+3 this month` accent volt.
5. **Tab bar** at bottom (§7.0).

#### UI — Data displayed
| Visible | Source |
|---|---|
| Coach name greeting | `Coach.name` |
| Sessions today count | `count(Session today where coachId=me)` |
| Next session metadata | next `Session` where `startTime > now` for today |
| Today's schedule rows | all today's sessions ordered by start time |
| Classes held | count of `Attendance` sessions where coachId=me in current month |
| Present rate | `present / (present + absent + late)` over current month |
| Exp payout | `Payout(period=current).expectedPayout` for me |
| Students | distinct count of students enrolled in my sessions |

#### UI — Interactions
- **Start attendance** → navigates to Take Attendance screen for the next-up session (or current live session if one is happening).
- **List icon button** → opens session detail (roster, notes, lesson plans).
- Tapping any schedule row → opens that session's attendance (or read-only roster if it hasn't started).
- KPI tile tap → drills into the relevant detail (e.g. Present rate → an attendance summary screen).
- Bell button → notifications sheet.

#### UI — States
- **No sessions today:** hero replaced by "No sessions today · Enjoy the rest day" card, no schedule list, just KPIs.
- **All sessions complete:** hero shows "All done for today" with `Icon.check`.
- **Offline:** offline strip above the top bar; KPI values come from last sync.
- **Loading:** skeleton hero + 4 schedule placeholders.

#### UI — Responsive
- Mobile-first; min width 320 px. The 2×2 KPI grid collapses to a vertical stack below 360 px.

#### Backend (ideal)
- `GET /api/coach/today` →
  ```json
  {
    "coach": { "name": "Arjun Menon", "id": "c1" },
    "today": "2026-05-17",
    "now": "2026-05-17T16:18:00+05:30",
    "next": { "id": "s1", "name": "Junior Smash · U10", "startsAt": "...", "endsAt": "...", "court": "A", "enrolled": 12, "capacity": 12 },
    "schedule": [ { "id": "s1", "name": "...", "startsAt": "...", "court": "A", "studentsCount": 12, "status": "now|upcoming|done" }, ... ],
    "monthly": {
      "classesHeld": 24,
      "classesScheduled": 28,
      "presentRate": 0.91,
      "expectedPayout": 35400,
      "studentsCount": 42,
      "newStudentsThisMonth": 3
    }
  }
  ```

#### Permissions
- `coach` role; the endpoint always scopes to the requesting coach.

#### Side effects
- None.

#### Validation
- `date` query param parseable (defaults to today in academy timezone).

#### Edge cases
- A coach who shares a court with another coach may see a session whose `coachId` is not theirs but where they're a substitute. Substitution is not in the design — out of scope.

#### ↪ Current backend mapping
- `GET /api/today` (coach_routes.py:47).
- `GET /api/v2/coach/today` (today_routes.py:35).
- `GET /api/v2/coach/dashboard` (dashboard_routes.py:15) — provides monthly KPIs.
- Consolidation into a single `coach/today` endpoint may be desirable.

---

### 7.2 Take Attendance

**Persona / device / route (proposed):** Coach · mobile · `/coach/sessions/{sessionId}/attendance`.
**Source (design):** `coach-screens.jsx → CoachAttendance()`.
**Purpose:** Mark each student in the session present / late / excused / make-up / absent, with optional notes. Optimised for one-handed courtside use with swipe gestures. Works offline; saves once the coach taps the sticky bottom Save bar.

#### User stories
- As a **coach**, I can mark every student in seconds.
- As a **coach**, I can use a swipe gesture (right = present, left = absent) for the common cases.
- As a **coach**, I can tap a row to expand a 5-button menu for less-common states.
- As a **coach**, I can attach a quick note to a student (visible to parent or private to admin).
- As a **coach**, I can `MARK ALL PRESENT` to bulk-set still-unmarked students.
- As a **coach**, the screen tells me how many remain to be marked so I don't accidentally submit incomplete.
- As a **coach**, I see streak indicators and "needs attention" badges (overdue payment, pause request, prior note) so I know context per student.
- As a **coach**, my work persists locally if I lose network mid-session.

#### UI — Layout
1. **Top bar:** back arrow on the left, right slot = `MARK ALL PRESENT` mono pill.
2. **Session strip card** (padding `14/16`, volt-tinted bg+border, radius 12, in a `padding 0/18/14` container):
   - Top row: left side mono volt overline `Junior Smash · U10` + Outfit 16/600 sub `Tue · 4:30 PM · Court A`; right side a 56 × 56 `<Ring value=(marked/total) color=volt label=marked sub="OF 12">`.
   - Counter row: 6 small tiles `P / L / A / E / M / ·` each with a top border in its status color, count (Outfit 16/700), and mono one-letter label.
3. **Swipe hint row** (mono 9/700, slate-500): left `ROSTER · 12`; right `← ABSENT TAP MENU PRESENT →` (last segment volt).
4. **Roster list** — vertical scroll (occupies remaining height):
   - Each `<SwipeRow>` is a 14 px padded card, 12 px radius:
     - **Default:** bg `rgba(255,255,255,0.04)`, 1 px white-tint border.
     - **Marked:** bg `#0e1726`, 1 px border in status color @ 40%, left 4 px border in status color.
     - Layout: `<Avatar 42>` + student name (Outfit 15/600 white) + sub (Manrope 11 `#94a3b8`) with `Age N`, optional `· N-class streak` (volt with mini ShuttleMark).
     - If `pause`, `!payOk`, or has a note → chip strip: `<Chip variant=paused dark>`, `<Chip variant=overdue dark>`, mono yellow "📌 NOTE" pill.
     - **Right side:** if marked → `<Chip variant=status dark>` + a `+ NOTE` text button (volt mono); if unmarked → 36 × 36 dashed-circle "?".
   - **Swipe behaviour:** card translates horizontally; if released past +80 px → mark present, past −80 px → mark absent. While dragging, the underlying reveal layer is green or red with mono uppercase label `● MARK PRESENT` / `MARK ABSENT ●`.
   - **Tap behaviour:** if the user taps with little movement, the row expands into a 5-button menu below it (Present/Late/Excused/Make-up/Absent) each as a column with a colored circle letter (P/L/E/M/A) and mono label.
5. **Sticky save bar** (bottom):
   - When `unmarked > 0`: `<N> left to mark` (transparent-white text on translucent surface, not pressable).
   - When `unmarked === 0` and unsaved: primary volt button `Save attendance · 12 marked →`.
   - After save: green success state `Saved · synced to admin` with check icon.
6. **Note bottom-sheet** (overlay when `+ NOTE` tapped):
   - Drag handle bar at top.
   - Avatar + Outfit 18/600 student name + volt overline `Add note`.
   - Tab row: `Progress` (visible to parent) / `Lesson plan` (visible to parent) / `Private` (coaches + admin only). Active tab: volt-yellow bg, slate fg.
   - Textarea (min 120 px, dark surface).
   - Bottom buttons: `Cancel` (secondary dark) + `Save note` (primary volt).

#### UI — Components
- `<SwipeRow>`, `<NoteSheet>`, `<Ring>`, `<Chip>`.

#### UI — Data displayed
| Visible | Source |
|---|---|
| Roster | `Enrollment` rows for this session, joined with `Student`. Includes students currently paused (visually de-emphasized). |
| Streak | `Student.streak` (derived from consecutive present attendances) |
| `pause` badge | `Student.pause` (or active `PauseRequest`) |
| `overdue` badge | `Student.payStatus = "overdue"` |
| `note` indicator | recent unread coach note for this student (in the parent's view) — or simply "has note this period" |

#### UI — Interactions
- Swipe right → set `present`; swipe left → set `absent`.
- Tap → toggle the 5-button menu; choosing a value sets status and collapses the menu.
- `+ NOTE` → opens the bottom sheet.
- `MARK ALL PRESENT` (top right) → for each row whose `status === null`, set to `present` (does not overwrite explicit choices).
- `Save attendance` → POSTs the entire roster as a single bulk update. On success: collapses to "Saved · synced to admin" green state and disables.
- After save, the user is implicitly free to navigate via the tab bar; if they return, the page shows the saved state.

#### UI — States
- **Loading** (initial fetch): roster skeleton 6 rows.
- **Empty roster** (e.g. session got cancelled, 0 enrollments): a card "No students enrolled · session marked as held"; the Save button submits a zero-roster confirmation.
- **Offline:** the offline pill strip appears above. Save button copy changes to `Save · syncs when back online`. On save, the writes go to local queue.
- **Error saving:** sticky bar turns red with "Couldn't save · tap to retry"; preserves all marks.
- **Already submitted (read-only return visit):** rows show their statuses; Save button replaced by mono caption "Submitted at 5:32 PM · 12 marked"; an Edit button (small, top right) re-enables editing.

#### UI — Responsive
- Pure mobile; horizontal swipe must use `touch-action: pan-y` so vertical scroll is unaffected.

#### Backend (ideal)
- `GET /api/coach/sessions/{sessionId}/attendance?date=YYYY-MM-DD` →
  ```json
  {
    "session": { "id": "s1", "name": "...", "startsAt": "...", "court": "A" },
    "date": "2026-05-17",
    "roster": [
      { "studentId": "st1", "name": "Aarav Sharma", "age": 9, "streak": 12, "pause": false, "payOk": true, "hasNote": false, "status": null|"present"|... }
    ],
    "submittedAt": null|"<iso>",
    "submittedBy": null|"<userId>"
  }
  ```
- `POST /api/coach/sessions/{sessionId}/attendance` body (idempotent — replaces existing):
  ```json
  {
    "date": "2026-05-17",
    "marks": [ { "studentId": "st1", "status": "present", "note": null }, ... ],
    "submittedAt": "2026-05-17T17:32:00+05:30"
  }
  ```
- `POST /api/coach/students/{studentId}/notes` body `{ sessionId, kind: "progress"|"plan"|"private", body }`.

#### Permissions
- `coach` role; the coach must own the session (or be a substitute, future).
- A coach cannot mark attendance for sessions they don't coach.

#### Side effects
- On `POST attendance`:
  - Upserts `Attendance` records per `(sessionId, sessionDate, studentId)`.
  - Updates each student's `Student.streak` and `attRate`.
  - Emits `attendance.recorded` events that can drive parent push notifications ("Aarav marked present").
  - If a student is paused (`Student.pause = true`) and the coach marks them present, raise an audit log entry (not a hard error).
- On `POST notes`: writes a `ProgressNote`, triggers a parent push if `kind ∈ {progress, plan}`.

#### Validation
- `status ∈ {"present","absent","late","excused","makeup"}`.
- Notes: max 500 chars.
- `date` must be ≤ today (no future-dating); allow back-dating up to 7 days (configurable).

#### Edge cases & open questions
- **Make-up attendance:** what session does `makeup` belong to? — implies the student originally missed a different session. The data model should support `Attendance.makeupForSessionDate`.
- **Add-on student:** can a coach add a drop-in student who isn't enrolled? Out of scope from the design; treat as future.
- **Cancellation mid-class:** if a coach hits "Cancel session" from `Icon.list`, no attendance is taken — needs a confirmation flow.

#### ↪ Current backend mapping
- `POST /api/attendance/bulk` (coaching_routes.py:67) — bulk mark.
- `GET /api/attendance` (96) — list attendance.
- v2: `POST /api/v2/coach/attendance` (attendance_routes.py) — idempotent.
- Notes: `GET/POST /api/v2/coach/sessions/{session_id}/lesson-plans` (notes_routes.py:26/36) and `/progress-notes` (54/64). Legacy: `GET /api/progress-notes` (coaching_routes.py:204), `POST` (234), `DELETE` (249); `GET/POST /api/lesson-plans` (136/165).
- Offline-queue support is **client-side only**; backend needs to be idempotent (use `(sessionId, date, studentId)` natural key).

---

### 7.3 Payout summary

**Persona / device / route (proposed):** Coach · mobile · `/coach/payout`.
**Source (design):** `coach-screens.jsx → CoachPayout()`.
**Purpose:** Show the coach the current period's expected payout, the calculation transparency (formula breakdown), and the last few paid periods.

#### User stories
- As a **coach**, I see exactly what I'm expected to earn this month and what's already collected.
- As a **coach**, I understand the formula behind that number.
- As a **coach**, I see past payouts and when they were paid.

#### UI — Layout
1. **Top bar:** title `Payout`, sub `May 2026 cycle`. Back arrow returns to Today.
2. **Hero amount card** (padding 22, radius 16, blue-tinted gradient `linear-gradient(135deg, rgba(37,99,235,0.18), rgba(37,99,235,0.04))`, 1 px border `rgba(37,99,235,0.3)`):
   - Top row: mono overline `Expected payout · May` + `<Chip variant=approval dark>` (NEEDS APPROVAL).
   - Outfit 56/700 amount (tabular numerics): `₹35,424`.
   - Mono `COLLECTED · ₹33,156 · 94%`.
   - 6 px progress bar with blue → light-blue gradient fill at 94%.
3. **Formula breakdown card** (padding 18, dark surface):
   - Volt overline `How it's calculated`.
   - 3 rows separated by hairlines:
     - `Expected revenue` · `42 STUDENTS × FEES` · Outfit 18/700 `₹1,96,800`.
     - `Collected revenue` · `YOUR BASIS · COLLECTED %` · `₹1,84,200`.
     - `Rate` · `REVENUE % · 18%` (uppercased basis label) · `× 18%` (in volt).
   - Then a thicker volt-yellow rule.
   - Final row: Outfit 15/600 `Expected payout`, mono volt `= ₹1,84,200 × 18%`, right-aligned Outfit 22/700 volt `₹35,424`.
4. **Paid history** section:
   - Slate `Paid history` overline + hairline divider.
   - Each history row (padding 14, radius 12): 44 × 44 green-tinted circle with `Icon.check` + Outfit 14/600 month + Manrope 11 `#94a3b8` sub `Paid <date> · <basis>` + right-aligned Outfit 16/700 amount + `<Chip variant=paid dark>`.
5. **Tab bar.**

#### UI — Data displayed
| Visible | Source |
|---|---|
| Expected payout | `Payout(period=current).expectedPayout` |
| Collected payout | `Payout(period=current).collectedPayout` |
| % collected | `collectedRevenue / expectedRevenue` (here 94%) |
| Approval state | `Payout.approved` |
| Formula values | `Payout` snapshot |
| History rows | `Payout where coachId=me AND paid=true` ordered by `paidAt` desc |

#### UI — Interactions
- Tap hero or "How it's calculated" → opens a formula detail sheet with examples per basis type.
- Tap a history row → modal with full payout slip (downloadable as PDF).
- No actions: coach cannot self-approve or self-pay; admin must (§6.6).
- If admin has approved but not yet paid: chip swaps to `APPROVED` and the hero subtitle reads "Awaiting payment".
- If paid for the current period: chip is `PAID`, hero amount is final (collected payout).

#### UI — States
- **Loading:** hero + breakdown skeletons.
- **No history:** show only "Will appear once a payout has been paid."
- **New coach, period 0:** hero shows `₹0` and a friendly "First payout calculates at month-end."

#### Backend (ideal)
- `GET /api/coach/payout?period=2026-05` →
  ```json
  {
    "period": "2026-05",
    "basis": "revenue_pct",
    "rate": 18,
    "expectedRevenue": 196800,
    "collectedRevenue": 184200,
    "expectedPayout": 35424,
    "collectedPayout": 33156,
    "approved": false,
    "paid": false,
    "students": 42,
    "classesHeld": 24,
    "currency": "INR"
  }
  ```
- `GET /api/coach/payout/history?limit=12` → list of paid `Payout` rows.
- `GET /api/coach/payout/{period}/payslip.pdf` → PDF.

#### Permissions
- `coach` role; only own payout visible.

#### Side effects
- None (read-only).

#### ↪ Current backend mapping
- `GET /api/coach-payouts/{coach_id}/payslip` (extras_routes.py:89).
- v2: no dedicated coach-facing endpoint; coach must fetch via `/api/v2/admin/finance/payouts` (admin-only) → **gap**. **New endpoint `/api/v2/coach/payout` required.**

---

### 7.4 Sessions tab (read-only)

The Coach tab bar lists `Sessions` and `Roster` as separate tabs (per `coach.html`). They are not separately mocked in `coach-screens.jsx`; the design intent (inferred from the rest of the prototype):

#### 7.4.1 Sessions (Coach view)
- A list of all sessions the coach owns. Each row: name, day/time, capacity bar, status chip, next-session date.
- Tap → session detail with roster + recent attendance + lesson plans.

#### 7.4.2 Roster (Coach view)
- A flat list of all students across all sessions the coach owns.
- Filterable by session, level. Tap → student profile (coach view: progress notes, attendance history, basic parent contact).

Backend: reuse existing `/api/v2/coach/today` + new `GET /api/v2/coach/sessions` and `GET /api/v2/coach/students`. These may also be derivable from `GET /api/v2/coach/today` if scoped wider.

#### ↪ Current backend mapping
- No dedicated `coach/sessions` list endpoint today (the coach `today` route returns per-day). **New endpoints needed.**

---

## 8. Parent (mobile)

**Persona:** `parent` role (or anonymous during registration).
**Device:** Mobile / PWA. Reference frame 402 × 874 px. Light surface (`#f8fafc`); blue / volt accents.
**Source files:** `parent.html`, `assets/parent-home.jsx`, `assets/parent-registration.jsx`.

### 8.0 Parent shell (top bar + tab bar)

#### UI — ParentTopBar
- Layout: padding `8 / 18 / 16 / 18`, 3-column flex.
- Left: 38 × 38 light back button (`rgba(15,23,42,0.06)` bg) when `onBack` is provided, otherwise an empty spacer.
- Center: Outfit 17/600 title (e.g. "Billing", "Progress", "Inbox").
- Right: optional 38 × 38 button (e.g. gear, bell, plus).

#### UI — ParentTabBar
- Position `absolute bottom: 0`, padding `12/16/30/16`, bg `rgba(255,255,255,0.92)` with `backdrop-filter: blur(16px)`, top hairline.
- 4 tabs: **Home** (`home`), **Pay** (`pay`), **Progress** (`chart`), **Inbox** (`msg`).
- Active tab: icon and label in slate-900; inactive in `#94a3b8`. Volt yellow underbar above the icon when active. Label mono 10/700 uppercase.

#### Shell-level behaviours
- The Home tab has its own custom hero (no shared topbar block since the hero replaces it).
- Bell button on Home opens the notification sheet.
- A persistent "active child" context applies across all tabs; switching children happens via the home hero's child selector.

---

### 8.1 Home

**Persona / device / route (proposed):** Parent · mobile · `/parent` (default landing).
**Source (design):** `parent-home.jsx → ParentHome()`.
**Purpose:** Parent's daily snapshot for one selected child: today's session, attendance ring, next-action banner, recent activity, mini-progress preview.

#### User stories
- As a **parent**, I see my child's session today and can RSVP or get directions in one tap.
- As a **parent**, I see how my child is doing this month (attendance %, on-track chip).
- As a **parent**, I see the next required action (pay / sign waiver / accept waitlist offer) or confirmation that autopay is on.
- As a **parent**, I see recent academy activity (coach notes, attendance, payments) at a glance.
- As a **parent**, I can switch between children if I have more than one enrolled.
- As a **parent**, I can add another child without leaving the home screen.

#### UI — Layout (mobile, scrollable)
1. **Hero header** (cobalt → blue-700 gradient `linear-gradient(180deg, #2563eb 0%, #1e3a8a 360px, #f8fafc 360px)`):
   - Top row: mono `Tuesday · May 17` overline (volt-on-blue tone, 0.8 opacity) + Outfit 26/600 `Hi, Rohan` (white). Right: 42 × 42 bell button (bg `rgba(255,255,255,0.16)`, 1 px border, volt dot indicator when notifications).
   - Child selector strip — two pills:
     - Active child pill: white bg, slate fg, `<Avatar 26>` + Outfit 13/600 name `Aarav (9)` + chevD icon (opens child switcher modal).
     - `+ Add child` pill: transparent with white border, mono 12.
2. **Stat ring hero card** (overlapping into white section, `margin-top: -8`, padding 22, drop shadow):
   - Left: `<Ring value=0.94 size=92 color=blue label="94%" sub="ATTEND">`.
   - Right: mono `Junior Smash · U10` overline, Outfit 18/600 `15 of 16 sessions`, 12 slate-500 `Coach Arjun · 4:30 PM · Mon · Wed`, chip strip `<Chip variant=present label="ON TRACK">` + `<Chip variant=autopayOn>`.
   - Below (inner card, slate-900 bg with court-lines decoration at 0.15 opacity):
     - Mono volt `Today` overline + Outfit 20/600 `Practice at 4:30 PM` + 12/`#cbd5e1` `Court A · Northside Sports Complex`.
     - Action row: `Directions` (transparent white border, pin icon) + `I can't make it` (volt button, slate fg).
3. **Next action banner** (full-width white card, padding 20, radius 14):
   - 48 × 48 mint-tinted check icon tile (when no action needed → autopay).
   - Center text: green volt overline `All set · Autopay on` + Outfit 16/600 `Next charge · ₹4,800 on May 28` + 12 slate `Visa •• 4242 · Junior Smash · U10`.
   - Right chevron.
   - Variants by state:
     - **Payment due**: red icon `Icon.card`, `Action needed`, "Pay ₹4,800 by May 28", `Pay now →`.
     - **Waiver missing**: amber icon `Icon.check`, `Sign before next session`, `Sign waiver →`.
     - **Waitlist offer**: volt icon `Icon.spark`, "Spot opened in Cadet Drill U14! Accept by Fri 6pm", `Accept offer →`.
4. **Recent activity** section:
   - `<LaneHeader index="A" title="Recent activity">`.
   - 3 activity rows (white cards, radius 12):
     - 36 × 36 colored tile (`note` yellow, `attend` green, `pay` blue) with `Icon.<kind>`.
     - Manrope 13/600 title (e.g. "Coach Arjun added a note", "Marked present", "May fees paid · ₹4,800").
     - 12 slate-500 sub (e.g. note excerpt, session reference, invoice number).
     - Mono uppercase relative timestamp `5H AGO`.
5. **Progress preview** section:
   - `<LaneHeader index="B" title="May progress">`.
   - Card with mono overline `Sessions completed`, mono right caption `+2 vs APR` (green), `<MiniBars values=[12,14,13,16,15,14,15] highlight=6 color=blue>`, then a row of month abbrevs underneath (mono 9/700 letter-spaced 0.1em).
6. **Tab bar.**

#### UI — Components
- `<Ring>`, `<Card>`, `<Chip>`, `<LaneLine>`, `<LaneHeader>`, `<MiniBars>`, `<CourtLines>`, `<Avatar>`, `<Button>`, `<Icon.*>`.

#### UI — Data displayed
| Visible | Source |
|---|---|
| Greeting + parent name | `Parent.name` |
| Current child summary | active child `Student` |
| Attendance ring | `Student.attRate` over current month |
| Sessions completed | `count(Attendance where status ∈ {present,late,makeup,excused})` |
| Today's session | next today's `Session` for this child |
| Next action | `Student.nextAction`: derived: `payment_due | waiver_pending | offer_pending | autopay_ok | none` |
| Activity feed | last 5 events: payment, attendance, note, offer, message |
| Progress mini-chart | sessions per month for last 7 months |

#### UI — Interactions
- Bell → notifications sheet.
- Child pill → child switcher modal (list of all `parent.childIds`).
- `+ Add child` → opens a mini "add child" flow (a 3-step trimmed version of registration: child info → session → confirm; uses existing waiver if same parent has signed).
- `Directions` → opens Maps deep-link with `Academy.location`.
- `I can't make it` → opens an absence notice modal (reason: travel / illness / other; optional note) which posts an `AbsenceNotice` to the coach; logged on roll as `EXCUSED` if submitted before class.
- Next-action banner → routes to relevant tab.
- Activity row tap → expanded detail / message thread / payment detail.
- Progress mini-chart → Progress tab.

#### UI — States
- **No child yet (post-onboarding edge case)**: hero header shows "Add your first child" CTA only; everything below is hidden.
- **Waitlisted child**: ring + "ON TRACK" chip replaced with `<Chip variant=waitlist label="WAITLIST · #2">`; the "Today" card replaced by "We'll notify you when a spot opens"; activity feed still functions.
- **Paused enrollment**: chip `PAUSED`; "Today" card replaced by "Paused until June 1 · resume now?".
- **Loading**: skeleton hero ring + 3 activity row placeholders.

#### UI — Responsive
- Mobile-first. The Home screen is the most graphics-heavy parent page; keep all elements above the fold on a 6.1" iPhone.

#### Backend (ideal)
- `GET /api/parent/home?childId=<id>` →
  ```json
  {
    "parent": { "id": "...", "name": "Rohan Sharma" },
    "children": [ { "id": "st1", "name": "Aarav", "age": 9 }, ... ],
    "active": {
      "child": { "id": "st1", "name": "Aarav", "age": 9, "level": "Beginner" },
      "session": { "id": "s1", "name": "Junior Smash · U10", "coach": "Arjun Menon", "schedule": "Mon · Wed · 4:30 PM" },
      "attendance": { "ratePct": 94, "sessionsAttended": 15, "totalSessions": 16, "chips": ["on_track","autopay_on"] },
      "today": {
        "hasSession": true,
        "startsAt": "2026-05-17T16:30:00+05:30",
        "court": "A",
        "location": "Northside Sports Complex"
      },
      "nextAction": {
        "kind": "autopay_ok|payment_due|waiver_pending|offer_pending",
        "title": "Next charge · ₹4,800 on May 28",
        "sub": "Visa •• 4242 · Junior Smash · U10",
        "deeplink": "/parent/pay"
      },
      "activity": [ { "kind": "note", "title": "...", "sub": "...", "at": "..." }, ... ],
      "progress": { "sessionsByMonth": [{"m":"Nov","v":12}, ...] }
    }
  }
  ```

#### Permissions
- `parent` role; only own children visible.

#### Side effects
- None.

#### Validation
- `childId` belongs to authenticated parent.

#### ↪ Current backend mapping
- `GET /api/dashboard/parent` (dashboard_routes.py:219).
- `GET /api/v2/parent/children` (activity_routes.py:24).
- `GET /api/v2/parent/enrollments` (33).
- `GET /api/v2/parent/attendance` (42).
- `GET /api/v2/parent/progress` (53).
- A consolidated `parent/home` endpoint would simplify the FE; today this would require 4-5 round trips.

---

### 8.2 Pay / Billing

**Persona / device / route (proposed):** Parent · mobile · `/parent/pay`.
**Source (design):** `parent-home.jsx → ParentPay()`.
**Purpose:** Manage payments — next charge hero, quick actions (Pay now / Request pause), autopay panel, payment history.

#### User stories
- As a **parent**, I see exactly what's next charged, when, and on which card.
- As a **parent**, I can pay early (skip the autopay date), update my card, or pause my enrollment.
- As a **parent**, I can toggle autopay on/off.
- As a **parent**, I can see my last 12 months of payments with status.

#### UI — Layout
1. **Hero balance card** (dark slate-900 surface, padding `16/22/28`):
   - Top topbar (gear icon right) titled `Billing`.
   - Mono overline `Next charge · May 28`.
   - Outfit 56/700 amount `₹4,800` (tabular numerics).
   - 13/`#cbd5e1` sub `Junior Smash · U10 · monthly`.
   - Chip strip: `<Chip variant=autopayOn dark>` + a custom mono pill `VISA •• 4242`.
   - Decorative court-lines at 0.15 opacity top-right.
2. **Quick actions row** (2-col grid):
   - **Pay now** (volt button, padded card): card icon + Outfit 14/600 `Pay now` + 11 slate `Skip the autopay date`.
   - **Request pause** (white border card): clock icon + Outfit 14/600 `Request pause` + 11 slate `Travel · injury · other`.
3. **Autopay panel** card:
   - `<LaneHeader index="01" title="Autopay">`.
   - Top row: Outfit 17/600 `Active · Visa •• 4242` + Manrope 12/slate `Charges on the 28th every month`. Right: iOS-style switch toggle (cobalt when on).
   - 2-col inner grid (padding 14, light bg, radius 10):
     - Last charge: mono overline + Outfit 18/700 date + `<Chip variant=paid>`.
     - Next charge: mono overline + Outfit 18/700 date + `<Chip variant=autopayOn>`.
   - `Change card / method →` button (secondary).
4. **Payment history** card:
   - `<LaneHeader index="02" title="Payment history">`.
   - Rows (5 visible by default, expandable):
     - Left: 44 × 44 light date tile (mono month abbrev top, Outfit day below).
     - Center: Outfit 16/600 amount (`-` prefix for refunds, tabular), 11 slate method, status chip below.
     - Right chevron.
5. **Tab bar.**

#### UI — Data displayed
| Visible | Source |
|---|---|
| Next charge | next `Payment where status=pending` for this child |
| Card / method label | from `Autopay.methodDetail` |
| Autopay status | `Enrollment.autopayEnabled` |
| Last charge | most recent paid `Payment` |
| Payment history | `Payment` rows where parentId=me, ordered by `processedAt` desc |

#### UI — Interactions
- **Pay now** → opens Stripe/UPI checkout for the pending charge.
- **Request pause** → opens a 3-question modal (reason / start date / duration in weeks) that creates a `PauseRequest` (admin must approve).
- **Toggle autopay** → confirms then calls the autopay PATCH.
- **Change card / method** → opens Stripe Customer Portal (or equivalent UPI mandate management).
- Per-row tap → invoice detail (line items, refund breakdown if applicable, "Download PDF" button).

#### UI — States
- **No payment due** (e.g. paused enrollment) — hero shows `₹0 · Paused until June 1`, autopay panel grayed out.
- **Failed last charge** — hero in red-tint: "Payment failed · update card" with primary CTA.
- **Loading** — skeletons.
- **Offline** — show last cached state; disable mutating actions.

#### Backend (ideal)
- `GET /api/parent/billing/summary?childId=` — hero + autopay state.
- `GET /api/parent/payments?childId=&limit=&cursor=` — history paginated.
- `POST /api/parent/payments/pay-now` body `{ paymentId, returnUrl }` → `{ checkoutUrl }`.
- `POST /api/parent/billing/autopay` body `{ enrollmentId, enabled: bool }`.
- `POST /api/parent/billing/portal` → returns Stripe customer portal URL.
- `POST /api/parent/pause-requests` body `{ enrollmentId, reason, fromDate, durationWeeks }`.
- `GET /api/parent/invoices/{id}.pdf`.

#### Permissions
- `parent` only; resources scoped to own children.

#### Side effects
- Pay-now triggers Stripe checkout; on success Stripe webhook updates the Payment.
- Autopay toggle creates/cancels Stripe subscription mandates.
- Pause request creates `PauseRequest` for admin approval (`§6.x`, not directly in design).

#### Validation
- Toggle autopay only allowed if a default payment method is on file.
- Pay-now only allowed for `Payment.status ∈ {"pending","failed","overdue"}`.

#### ↪ Current backend mapping
- `GET /api/v2/parent/payments` (payment_routes.py:146).
- `GET /api/v2/parent/credit-balance` (payment_routes.py).
- `POST /api/v2/parent/checkout/start` (71) — pay-now.
- `POST /api/v2/parent/autopay/start` (90).
- `POST /api/v2/parent/billing/portal` (112).
- `GET /api/v2/parent/checkout/status/{session_id}` (129).
- Legacy: `POST /api/billing/checkout-session` (149), `POST /api/billing/subscription-checkout` (218), `POST /api/billing/customer-portal` (320), `GET /api/billing/checkout-status/{session_id}` (382).
- Pause requests: `GET /api/v2/parent/pause-requests` (pause_routes.py:22), `POST` (31). Legacy `POST /api/pause-requests` (sessions_routes.py:581).
- Invoice PDF: **not present today**.

---

### 8.3 Progress

**Persona / device / route (proposed):** Parent · mobile · `/parent/progress?childId=`.
**Source (design):** `parent-home.jsx → ParentProgress()`.
**Purpose:** A child's monthly progress dashboard — sessions, streak, attendance trend, level progression, coach notes timeline.

#### User stories
- As a **parent**, I see my child's headline stats for the current month (sessions, streak, attendance %, level).
- As a **parent**, I see what the coach has written about my child this month (and the lesson plan for the next session).

#### UI — Layout
1. **Sticky title block** (white bg, padded 0/22/28/22): mono overline `Aarav · Junior Smash · U10` + Outfit 32/700 `This month`.
2. **Stats grid** (2-col, 12 px gap):
   - **Sessions** card (accent blue): mono `Sessions` + Outfit 36/700 `15` with mono `/16` + `<Sparkline>` underneath.
   - **Streak · weeks** card (accent volt): Outfit 36/700 `12` + `<ShuttleMark>` + 11 slate sub `Personal best · keep going`.
   - **Attendance** card: Outfit 36/700 `94%` + 11 green sub `↑ 4pt vs Apr`.
   - **Level** card: Outfit 22/700 `Beginner` + 4 px progress bar 70% filled volt + mono `70% TO CADET`.
3. **Coach notes** section:
   - `<LaneHeader index="01" title="Coach notes">`.
   - Each note (white card, radius 12, left border 3 px volt):
     - Top row: mono overline `<TITLE>` + mono right `<DATE>`.
     - Manrope 13/0 body line-height 1.5.
     - Footer: `<Avatar 22>` + coach name (11 slate).
4. **Tab bar.**

#### UI — Data displayed
| Visible | Source |
|---|---|
| Sessions this month | `count(Attendance where studentId=… in current month)` |
| Streak weeks | derived from consecutive weeks with ≥1 present |
| Attendance % | rate this month |
| Level + progression | `Student.level` + a `LevelProgress.percentToNext` |
| Notes | `ProgressNote` where parent-visible (`kind ∈ progress, plan`) ordered desc |

#### UI — Interactions
- Tap a stat card → drills into the stat's detail (e.g. Sessions → list of attendance records this month).
- Tap a note → expanded view with full body and any attached image/video.

#### UI — States
- **No notes yet:** show empty placeholder "Coach Arjun will share notes here as the month progresses."

#### Backend (ideal)
- `GET /api/parent/progress?childId=` →
  ```json
  {
    "child": { "id": "...", "name": "Aarav", "session": "Junior Smash · U10" },
    "month": { "sessions": 15, "scheduled": 16, "streakWeeks": 12, "attendancePct": 94, "attendanceDelta": 4 },
    "level": { "current": "Beginner", "percentToNext": 0.7, "nextName": "Cadet" },
    "notes": [ { "id": "...", "kind": "progress|plan", "title": "Footwork drill", "body": "...", "byCoach": "Arjun Menon", "createdAt": "..." }, ... ],
    "trend": { "sessionsByMonth": [ ... ] }
  }
  ```

#### Permissions
- `parent` only; only own children.

#### ↪ Current backend mapping
- `GET /api/v2/parent/progress` (activity_routes.py:53) — progress notes only; would need expansion to cover monthly KPIs + level.
- Level tracking and "percent to next level" are **not modeled** today.

---

### 8.4 Inbox

**Persona / device / route (proposed):** Parent · mobile · `/parent/inbox?tab=<all|coach|academy|payment>`.
**Source (design):** `parent-home.jsx → ParentInbox()`.
**Purpose:** Messaging hub — filter by sender (Coach / Academy / Payment), open threads, send replies.

#### User stories
- As a **parent**, I can see all messages from the coach, academy, and payment system.
- As a **parent**, I can read and reply to coach messages.
- As a **parent**, I can compose a new message to my coach (via the `+` button).

#### UI — Layout
1. **Header** (white bg, bottom border): `ParentTopBar` titled `Inbox` with a `+` button right. Below: tab pill row `All` · `Coach` · `Academy` · `Payment` (active = slate-900 bg).
2. **Thread list** (light bg, padding 22):
   - Each row (no card; hairline divider between):
     - `<Avatar 44>` + Outfit 15/600 sender name + mono right-aligned timestamp.
     - 13 slate-500 message preview line (or slate-900 if unread, weight 500).
     - 7 × 7 blue unread dot at the right edge.
3. **Tab bar.**

#### UI — Data displayed
| Visible | Source |
|---|---|
| Threads | `Thread where me ∈ participants` filtered by `Thread.kind` and persona-allowed senders |
| Sender name | `User.name` ("Coach <name>" / "Rally Academy") |
| Preview | last message body truncated |
| Unread dot | last message unread by me |

#### UI — Interactions
- Thread tap → conversation view (composer + bubbles, same pattern as Admin inbox but mobile). On open, marks read.
- `+` → opens a new message composer addressed to the parent's primary coach by default (or a recipient picker if multiple coaches).
- Filter pills → tab updates URL `?tab=`.

#### UI — States
- Empty inbox: card with `<ShuttleMark>` "All quiet" + sub.
- Loading: 4 skeleton rows.

#### Backend (ideal)
- `GET /api/parent/threads?kind=` → list.
- `GET /api/parent/threads/{id}` → thread + messages.
- `POST /api/parent/threads/{id}/messages` body `{ body }`.
- `POST /api/parent/threads` body `{ recipientUserId, subject?, body }` (default recipient = primary coach).
- `PATCH /api/parent/threads/{id}/read`.

#### Permissions
- Parent can only DM their own coach or the academy. Coach↔parent DMs only if the parent has a child in that coach's session.

#### Side effects
- New message triggers notification (push to recipient).

#### ↪ Current backend mapping
- Parent equivalents would mirror `/api/messages/*` (comms_routes.py) with persona scoping. Today, parents likely use the same generic endpoints.
- **Parent-scoped thread endpoints recommended** (e.g. `/api/v2/parent/threads`).

---

### 8.5 Registration flow (Welcome → Done, 7 steps)

**Persona / device / route (proposed):** Public/anonymous → Parent · mobile · `/register` (with deep-linkable step state).
**Source (design):** `parent-registration.jsx → ParentRegistration()` and step components.
**Purpose:** Conversational, one-question-per-screen enrollment flow that creates a parent + child + enrollment + waiver signature + first payment in 7 steps. Takes ~3 minutes; auto-saves progress so the parent can resume.

The 7 steps are: **Welcome → Parent → Child → Session → Waiver → Pay → Done**. Steps are tracked in a progress bar (4 px tall, 7 segments, volt for completed). Each step has its own primary CTA.

#### Common chrome
- **Top:** back arrow (left, returns to previous step or exits) + mono `STEP N / 7` + close `X` (right, prompts confirm before discarding).
- **Progress bar:** 7 segments below the header.
- **Step heading block:** mono blue overline `NN of 06 · <step name>` + Outfit 30/700 question/title.
- **Sticky bottom CTA:** full-width slate-900 button with right-arrow icon. Disabled if validation fails.

#### Shared interaction model
- Forward navigation requires the step's validation to pass (button stays disabled otherwise).
- Backward navigation never destroys data.
- A close + confirm flow saves a draft `EnrollmentApplication` to which the parent can return (resume-by-link).

---

#### 8.5.1 Welcome (Step 1)

**Source:** `parent-registration.jsx → RegWelcome()`.

##### UI — Layout
- Editorial moment with two decorative SVGs: `<ShuttleMark size=180 color=volt>` top-right at 0.6 opacity; `<CourtLines w=280 h=120>` mid-left at 0.5 opacity.
- Mono blue overline `Rally Academy · Registration`.
- Outfit 44/700 headline `Let's get your kid on the court.` with `on the court` underlined volt-yellow (60%-from-bottom gradient).
- 15/slate body: "Six quick steps. Takes about 3 minutes. We'll save your progress so you can pick up where you left off."
- 5-row checklist:
  - `01 Tell us about you · Name, email, phone`
  - `02 Tell us about your child · Name, age, level`
  - `03 Pick a session · Times that fit your week`
  - `04 Sign the waiver · Standard sports waiver`
  - `05 Confirm enrollment · Pay or join waitlist`
  - (Step 06 is `Pay` and Step 07 is `Done`; the design lists only 5 user-action steps in the preview.)
- Sticky CTA: `Start registration` (variant `dark`, size xl, arrow icon volt).

##### Interactions
- Tap CTA → step 2.
- Tap back → exits to public landing (or shows "Discard?" if user has any draft).

##### Backend
- `POST /api/parent/registration/start` (anonymous) → returns `{ applicationId, expiresAt }` and sets a cookie/localStorage token for resumption.

---

#### 8.5.2 Parent info (Step 2)

**Source:** `RegParent()`.

##### UI — Layout
- Step heading: `01 of 06 · You` / `Who's enrolling today?`.
- 3 form fields (label = mono overline above input):
  - **Your full name** (required, min 2 chars).
  - **Email** (required, validated format; helper: "We'll send receipts and class updates here.").
  - **Mobile** (required, validated format; default country code = academy's locale).
- Blue info banner: "We never sell your contact info. You can add a second parent later." with `Icon.check` glyph.
- Sticky CTA: `Continue`.

##### Validation
- All three fields required; email format; phone format per academy region.

##### Backend
- `PATCH /api/parent/registration/{applicationId}` body `{ parent: {name, email, phone} }`.
- On submit, server attempts to find an existing parent by email/phone (in case the parent is enrolling a second child while signed out). If found, prompt "It looks like you already have an account — sign in to continue?"

##### Edge cases
- An email already linked to an account requires sign-in or a magic-link verification step.

---

#### 8.5.3 Child info (Step 3)

**Source:** `RegChild()`.

##### UI — Layout
- Step heading: `02 of 06 · Your child` / `Tell us about your player.`.
- 3 form fields:
  - **Child's name** (required).
  - **Date of birth** (required; date input; helper: "So we can match them to the right age group.").
  - **Skill level** (required; 3-button segmented control: Beginner / Intermediate / Advanced; selected = slate-900 bg + white fg).
- Yellow advisory card: "First time playing? Pick Beginner. Coaches will assess and bump them up if they're ready."
- Sticky CTA: `Continue`.

##### Validation
- Name min 2 chars. DOB in past, child age 4–80 (open question on the upper bound — the mock has a 36 y/o adult student).
- Level enum.

##### Backend
- `PATCH /api/parent/registration/{applicationId}` body `{ child: {name, dob, level} }`.

##### Edge cases
- Multi-child registration: this design flow handles only one child per session of the wizard. A second child can be added later via the home `+ Add child` flow.

---

#### 8.5.4 Session selection (Step 4)

**Source:** `RegSession()`.

##### UI — Layout
- Step heading: `03 of 06 · Session` / `Pick a class that fits.`.
- Mono overline `Recommended for U10 Beginner` (computed from child's age + level).
- List of recommended sessions, each as a tappable card (radius 14, 2 px border):
  - Selected state: slate-900 bg + white fg + 2 px volt-yellow border.
  - Header row: Outfit 17/600 session name + Manrope 12 sub `day · time`; right `<Chip variant=open|full>`.
  - Footer row: `<Avatar 26>` + Manrope 12 `Coach <FirstName>` + right Outfit 16/700 `₹<fee>/mo`.
  - If `full`: a volt-tinted strip below `● JOIN WAITLIST · N AHEAD`.
- Sticky CTA: `Continue`.

##### Validation
- A session must be selected.

##### Backend
- `PATCH /api/parent/registration/{applicationId}` body `{ sessionId }`.
- The list is fetched from `GET /api/v2/parent/sessions/available?ageGroup=&level=` (existing endpoint).

##### Edge cases
- All recommended sessions are full → show a "See other levels" link to broaden the filter; if everything is full, all selections lead to waitlist.
- The list updates live: if another parent grabs the last spot while the user is on this screen, that session's chip flips to FULL.

---

#### 8.5.5 Waiver (Step 5)

**Source:** `RegWaiver()`.

##### UI — Layout
- Step heading: `04 of 06 · Waiver` / `One quick legal.`.
- Scrollable waiver text card (white, max-height 280 px, overflow-y auto) with:
  - Mono overline `Rally Academy · Liability Waiver v2.4` (version pulled live).
  - Paragraphs of legal text, child's name interpolated where relevant (`<strong>{data.child.name}</strong>`).
- Acceptance checkbox card (radius 12):
  - Default: white bg, slate-200 border.
  - Accepted: mint bg `#ecfdf5`, mint border.
  - Content: 20 × 20 checkbox (accent green) + Outfit 14/600 `I've read and accept the waiver` + 12 slate sub.
- Sticky CTA: `Continue` (enabled only when accepted) — disabled label `Accept to continue`.

##### Validation
- Checkbox required.

##### Backend
- `PATCH /api/parent/registration/{applicationId}` body `{ waiver: { accepted: true, version: "v3.1" } }`.
- Server records `WaiverSignature` with `method = "checkbox"`, ip, user-agent, version. **Note**: the design also references e-sign with a drawn signature in the broader copy; the registration step itself is checkbox-only. A separate e-sign upgrade flow is implied for academies that require it.

##### Edge cases
- A new waiver version published mid-session → must re-prompt the user with the latest text.

---

#### 8.5.6 Pay (Step 6)

**Source:** `RegPay()`.

##### UI — Layout
- Step heading: `05 of 06 · Pay` / `Almost there.` (or `Hold the spot.` if the chosen session is full → waitlist mode).
- **Order summary card** (`<Card p=0>`):
  - Top section: mono overline `Summary` + Outfit 17/600 session name + 12 slate `For <child> · <time>`.
  - Mid section (3 line items, mono right-aligned numerics):
    - `Monthly fee` · `₹4,800` (or whatever the session fee).
    - `One-time registration` · `₹500`.
    - `First-class discount` · `− ₹500` (in green).
  - Footer (bg `#fafbfd`, top border): mono overline `Total today` / Outfit 28/700 amount; right `<Chip variant=autopayOn label="AUTOPAY ON">`.
  - If the selected session is **full**: footer reads "No charge until offered" with total `₹0`.
- **Pay method picker** (visible only if NOT full): mono overline `Pay with` + 2 selectable rows (each padding 14, 2 px border for selected):
  - Row example: 38 × 38 icon tile + Outfit 14/600 method label + 11 slate sub + right radio (filled when selected).
  - Options:
    - **Visa •• 4242** · `Autopay every month` (default selected).
    - **UPI** · `Manual every month`.
  - Additional options at runtime: add new card, Apple Pay, Google Pay (where supported).
- Sticky CTA: `Pay ₹4,800 & enroll` (with check icon) or `Join waitlist · #N` (no payment, waitlist mode).

##### Validation
- Payment method must be selected for non-full session.

##### Backend
- Quote (optional pre-confirm): `POST /api/parent/registration/{applicationId}/quote` → `{ lineItems, total, currency }`.
- Confirm: `POST /api/parent/registration/{applicationId}/confirm`:
  - If session is open: starts a Stripe Checkout / UPI mandate and returns `{ checkoutUrl }`.
  - If session is full: creates an Enrollment with `status=waitlist`, returns success without payment.
- Webhook: `POST /api/v2/parent/webhooks/stripe` finalizes once Stripe confirms.

##### Side effects
- On successful payment: provisions Parent (Firebase user if not exists), creates Child, creates Enrollment (`status=enrolled` or `pending` awaiting admin approval — see Setting `Enrollment auto-approve`), creates WaiverSignature, creates first Payment.
- Sends welcome email + notification to admin.

##### Edge cases
- Payment fails mid-flow: keep the application in `pending payment` and offer retry on Step 6.
- Network drops between Stripe redirect and our return: poll `GET /api/v2/parent/checkout/status/{session_id}` (existing endpoint).

---

#### 8.5.7 Done (Step 7)

**Source:** `RegDone()`.

##### UI — Layout
- Centered success state with decorative `<ShuttleMark size=220>` at 0.15 opacity behind.
- 88 × 88 green circle with big check icon (shadow `0 12px 32px rgba(16,185,129,0.3)`).
- Green volt overline `Confirmation · INV-2026-0428`.
- Outfit 32/700 headline `You're enrolled.`.
- 15/slate body: "Aarav's first session is **Tue, May 20 at 4:30 PM**. We've sent the receipt and waiver copy to your email."
- 3 follow-up cards (white, radius 12):
  - Calendar tile: `Icon.calendar` + `Added to your calendar` + `Tue & Thu · 4:30 PM`.
  - Message tile: `Icon.msg` + `Coach Arjun says hi` + quote.
  - Card tile: `Icon.card` + `Autopay confirmed` + next charge details.
- Bottom CTA: `Open my dashboard →` (variant dark, xl).

##### Interactions
- CTA → navigates to `/parent` Home.
- Tap Calendar card → initiates iOS Calendar / Google Calendar deep-link with the ICS feed for this enrollment.
- Tap Message card → opens the welcome thread.

##### Backend
- `GET /api/parent/registration/{applicationId}/confirmation` → full done-payload (invoice number, calendar URL, welcome message).
- The application transitions to `submitted` and becomes read-only after confirmation.

##### Edge cases
- Waitlist confirmation: the same screen but headline `You're on the waitlist.` and body explains expected wait. No invoice number.
- Admin-approval-required mode: the screen says "Enrollment pending review · we'll notify you within 24 hours."

#### ↪ Current backend mapping (registration end-to-end)
- Onboarding (legacy): `POST /api/start` (onboarding_routes.py:210), `PATCH /api/{app_id}` (243), `GET /api/{app_id}/status` (358), `POST /api/{app_id}/checkout` (403).
- Onboarding (v2): `POST /api/v2/parent/onboarding/start` (37), `PATCH /api/v2/parent/onboarding/{application_id}` (56), `GET .../status` (80).
- Waiver: `GET /api/waiver/current` (onboarding_routes.py:179).
- Session catalog: `GET /api/v2/parent/sessions/available` (session_routes.py:24).
- Stripe checkout: `POST /api/v2/parent/checkout/start` (payment_routes.py:71); status: `GET /api/v2/parent/checkout/status/{session_id}` (129); webhook: `POST /api/v2/parent/webhooks/stripe` (webhook_routes.py:16).
- Registration anonymous: `POST /api/v2/parent` (registration_routes.py:28).
- Quote: not implemented — would be useful.
- Confirmation payload: not surfaced as a single endpoint today; derived from application status + invoice fetch.

---

## 9. Glossary

| Term | Definition |
|---|---|
| **Academy** | The tenant. One running instance of the product belongs to one academy. |
| **Active session** | A `Session` not paused / cancelled; appears on rosters and accepts enrollments. |
| **Activity feed** | A merged stream of recent events (payments, enrollments, attendance, messages) shown on the admin dashboard and on parent home. |
| **Attendance** | A `(sessionId, sessionDate, studentId)` record with a status (present / absent / late / excused / make-up). |
| **Autopay** | A recurring billing mandate (e.g. Stripe subscription or UPI mandate) that automatically charges the parent on each cycle. |
| **Basis** (payout) | The method used to compute a coach's payout: `revenue_pct` (% of collected revenue), `per_class`, or `per_student`. |
| **Capacity** | The maximum number of students a session can accept; once reached, status flips to `full`. |
| **Closing** | A session that is near capacity (e.g. 1–2 seats left). Heuristic, not a hard rule. |
| **Coach payout** | The amount a coach earns for a period, computed from basis × rate × actuals. |
| **Cycle** | The billing period for an enrollment (typically a month). |
| **Dues** | An overdue payment that has entered the collections workflow. |
| **Enrollment** | A `(studentId, sessionId)` relationship with a lifecycle (pending → waitlist/offered → enrolled → paused/cancelled). |
| **Final notice** | The last stage of the dues recovery sequence before an enrollment is auto-paused. |
| **Lane line** | A visual section divider — thick volt-yellow bar + thin slate bar — borrowed from court markings. |
| **Mark all present** | The coach attendance bulk-action that sets every still-unmarked roster row to `present`. |
| **MTD** | Month-to-date. |
| **Offer (waitlist)** | A time-bound invitation to a waitlisted parent to claim an opened spot. Expires after a configurable window. |
| **Onboarding** | The legacy term for the parent registration flow. |
| **Pause** | A temporary suspension of an enrollment (no billing, no class). Parent-requested, admin-approved. |
| **Payslip** | A PDF summary of a coach's paid payout. |
| **Recovery sequence** | The automatic series of reminders/escalations triggered when a payment goes overdue (Day 0 / +2 / +5 / +14). |
| **Roster** | The set of enrolled students in a session for a given date. |
| **Shuttle mark** | The shuttlecock-shaped SVG accent in the design system. |
| **Streak** | A student's consecutive sessions present (or weeks present, on the parent view). |
| **Volt** | The brand-accent color `#facc15` (volt-yellow). |
| **Waiver** | The liability document a parent must sign before their child trains. Versioned. |
| **Waitlist** | The ordered queue of would-be enrollees waiting for capacity to open. |

---

## Appendix A — Current Backend Mapping (consolidated)

The backend exposes both a **legacy** API under `/api/*` and a **v2 (DDD/BFF)** API under `/api/v2/*` per `AGENTS.md`. The migration direction is: keep legacy stable; add v2 capabilities incrementally; do not big-bang rewrite.

Below is a consolidated inventory grouped by spec section, showing currently-implemented routes that satisfy (in whole or part) the ideal contracts in this document. Anything **not** listed here is either net-new or partially specified.

### A.1 Auth & shell

| Spec § | Current legacy | Current v2 |
|---|---|---|
| Sign in / sign out / refresh | `POST /api/auth/login`, `POST /api/auth/logout`, `POST /api/auth/refresh`, `GET /api/auth/me` — `auth_routes.py:379/400/411/406` | `GET /api/v2/me` — `me_routes.py:24` |
| Register | `POST /api/auth/register`, `POST /api/auth/register-full` — `127/191` | `POST /api/v2/parent` (anonymous registration) — `registration_routes.py:28` |
| Public sessions (pre-login) | `GET /api/auth/public-sessions` — `356` | — |
| Password reset | `POST /api/auth/forgot-password`, `POST /api/auth/reset-password` — `433/464` | — |
| Invites | `POST/GET /api/invites`, `DELETE /api/invites/{token}`, `GET /info`, `POST /accept` — `482/513/520/529/538` | — |
| Users CRUD | `GET/PATCH/DELETE /api/users/{user_id}` — `597/610/620/648`; `POST .../reset-password` — `636` | `GET /api/v2/admin/users`, `PATCH .../role` — `directory_routes.py:26/36` |
| Health | — | `GET /api/v2/healthz` — `main.py:124` |

### A.2 Admin Dashboard (§6.1)

| Need | Current |
|---|---|
| KPI bundle | `GET /api/dashboard/admin` — `dashboard_routes.py:20`; revenue analytics `GET /api/v2/admin/finance/revenue` — `billing_routes.py:290` |
| Attention items | `GET /api/v2/admin/dashboard/attention` — `dashboard_routes.py:21` |
| Activity feed | **Gap** — no consolidated endpoint |

### A.3 Payments (§6.2)

| Need | Current |
|---|---|
| List | `GET /api/payments` — `finance_routes.py:69`; total/aggregates not isolated |
| Create | `POST /api/payments` — `84` |
| Generate monthly | `POST /api/payments/generate-monthly` — `122`; v2: `POST /api/v2/admin/payments/generate-monthly` — `billing_routes.py:175` |
| Mark paid | `PATCH /api/payments/{pid}/mark-paid` — `210`; v2: `POST /api/v2/admin/payments/{payment_id}/mark-paid` — `187` |
| Apply discount | `PATCH /api/payments/{pid}/apply-discount` — `237`; v2: `POST /api/v2/admin/payments/{payment_id}/discount` — `204` |
| Undo paid | `POST /api/payments/{pid}/undo-paid` — `260`; v2: `POST /api/v2/admin/payments/{payment_id}/undo-paid` — `220` |
| Refund | `POST /api/payments/{pid}/refund` — `295`, `POST /api/admin/payments/{payment_id}/refund` — `344`; v2: `POST /api/v2/admin/payments/refund` — `159` |
| Delete | `DELETE /api/payments/{pid}` — `252` |
| Bulk-remind / per-status filter / autopay coverage KPI | **Gap** |

### A.4 Dues (§6.3)

| Need | Current |
|---|---|
| List dues | `GET /api/dues-followup` — `extras_routes.py:20`; v2: `GET /api/v2/admin/dues-followup` — `dues_routes.py:19` |
| Send reminders | `POST /api/email/send-dues-reminders` — `email_routes.py:138`; v2: `POST /api/v2/admin/dues-reminders` — `dues_routes.py:28` |
| Per-dues remind / resolve / sequence config | **Gap** |

### A.5 Reports (§6.4)

| Need | Current |
|---|---|
| Revenue CSV | `GET /api/reports/revenue.csv` — `dashboard_routes.py:285` |
| P&L CSV | `GET /api/reports/profit.csv` — `373` |
| Attendance CSV | `GET /api/reports/attendance.csv` — `332` |
| Pending payments CSV | `GET /api/reports/pending-payments.csv` — `310` |
| Coach payouts CSV | `GET /api/reports/coach-payouts.csv` — `352` |
| Waivers CSV | `GET /api/reports/waivers.csv` — `396` |
| Audit logs | `GET /api/audit-logs` — `414`; v2: `GET /api/v2/admin/audit-logs` — `audit_routes.py:15` |
| Generic v2 report | `GET /api/v2/admin/reports/{report_name}.csv` — `reports_routes.py:15` |
| XLSX / PDF formats | **Gap** |

### A.6 Sessions (§6.5)

| Need | Current |
|---|---|
| List / Get / CRUD / Cancel | `GET /api/sessions`, `POST`, `GET/{sid}`, `PATCH`, `DELETE`, `POST /cancel` — `sessions_routes.py:110/130/143/161/171/179` |
| v2 list / create / delete | `GET /api/v2/admin/sessions`, `POST`, `DELETE` — `sessions_routes.py:33/49/61` |
| Duplicate, pause-session, increase-capacity | **Gap** |

### A.7 Coach payouts (§6.6, §7.3)

| Need | Current |
|---|---|
| List | `GET /api/coach-payouts` — `finance_routes.py:670`; v2: `GET /api/v2/admin/finance/payouts` — `billing_routes.py:233` |
| Approve | `POST /api/coach-payouts/{pid}/approve` — `693` |
| Mark paid | `POST .../mark-paid` — `710` |
| Undo paid / approve | `POST .../undo-paid` — `491`, `POST .../undo-approve` — `512` |
| Calculate | `POST /api/coach-payouts/calculate` — `602` |
| Payslip PDF | `GET /api/coach-payouts/{coach_id}/payslip` — `extras_routes.py:89` |
| Rules | `GET/POST /api/payout-rules` — `569/584` |
| **Coach-facing**: `GET /api/v2/coach/payout` | **Gap** |

### A.8 Students (§6.7)

| Need | Current |
|---|---|
| List / Get / CRUD | `GET /api/students` — `sessions_routes.py:226`; `POST` — `197`; `GET/{sid}` — `298`; `PATCH` — `312`; `DELETE` — `329` |
| v2 admin list | `GET /api/v2/admin/students` — `directory_routes.py:57` |
| Per-student attendance, payment timelines | partially via `/api/attendance`, `/api/payments` filtered; **no dedicated endpoints** |

### A.9 Enrollments (§6.8)

| Need | Current |
|---|---|
| Create / list | `POST /api/enrollments` — `343`; `GET /api/enrollments` — `378` |
| Cancel | `POST /api/enrollments/{eid}/cancel` — `412` |
| Approve | `POST /api/enrollments/{eid}/approve` — `435` |
| Transfer | `POST /api/enrollments/{eid}/transfer` — `450`; v2: `POST /api/v2/admin/enrollments/{enrollment_id}/transfer` — `sessions_routes.py:127` |
| Pause / resume month | `POST /api/enrollments/{eid}/pause-month` — `504`, `POST .../resume-month` — `530`; v2: `POST .../pause` — `152`, `POST .../resume` — `163` |
| Pending list | `GET /api/enrollments/pending-approval` — `extras_routes.py:179` |
| v2 cancel | `DELETE /api/v2/admin/enrollments/{enrollment_id}` — `sessions_routes.py:116` |
| **Decline / nudge / bulk-decline** | **Gap** |

### A.10 Waitlist (§6.9)

| Need | Current |
|---|---|
| Parent waitlist | `GET /api/waitlist` — `waitlist_routes.py:58`; `POST /api/waitlist` — `72`; `POST /api/waitlist/{wid}/enroll` — `299` |
| Admin waitlist | `GET /api/admin/waitlist` — `98`; `POST .../enroll` — `175`; `POST .../skip` — `240`; `DELETE` — `268` |
| v2 admin | `GET /api/v2/admin/waitlist` — `waitlist_routes.py:20`; `POST .../promote` — `92`; `POST .../skip` — `102`; `DELETE` — `111` |
| **Offer / revoke / resend / policy config / capacity bump** | **Gap** |

### A.11 Expenses (§6.10)

| Need | Current |
|---|---|
| CRUD | `GET /api/expenses` — `finance_routes.py:529`; `POST` — `539`; `PATCH /{eid}` — `552`; `DELETE` — `560` |
| v2 | `GET /api/v2/admin/finance/expenses` — `billing_routes.py:254`; `POST` — `274` |
| Category breakdown, recurring auto-generation | **Gap** (likely derivable client-side) |

### A.12 Attendance (§7.2)

| Need | Current |
|---|---|
| Bulk mark | `POST /api/attendance/bulk` — `coaching_routes.py:67` |
| Get records | `GET /api/attendance` — `96` |
| Coach v2 (idempotent) | `POST /api/v2/coach/attendance` — `attendance_routes.py` |
| Parent view | `GET /api/v2/parent/attendance` — `activity_routes.py:42` |
| Lesson plans | `GET /api/lesson-plans` — `coaching_routes.py:136`; `POST` — `165`; `PATCH /{lid}` — `179`; `DELETE` — `191`; v2: `GET/POST /api/v2/coach/sessions/{session_id}/lesson-plans` — `notes_routes.py:26/36` |
| Progress notes | `GET/POST /api/progress-notes` — `204/234`; `DELETE` — `249`; v2: `GET/POST /api/v2/coach/sessions/{session_id}/progress-notes` — `notes_routes.py:54/64` |

### A.13 Coach Today / dashboard (§7.1)

| Need | Current |
|---|---|
| Today | `GET /api/today` — `coach_routes.py:47`; v2: `GET /api/v2/coach/today` — `today_routes.py:35` |
| Coach KPIs | `GET /api/dashboard/coach` — `dashboard_routes.py:173`; v2: `GET /api/v2/coach/dashboard` — `dashboard_routes.py:15` |

### A.14 Parent app (§8.1–§8.4)

| Need | Current |
|---|---|
| Home consolidation | **Gap** — would consolidate `GET /api/v2/parent/children` (24) + `enrollments` (33) + `attendance` (42) + `progress` (53) |
| Billing summary | derive from `GET /api/v2/parent/payments` — `payment_routes.py:146`; credit balance `GET /api/v2/parent/credit-balance` |
| Pay now / autopay / portal | `POST /api/v2/parent/checkout/start` — `71`; `POST /api/v2/parent/autopay/start` — `90`; `POST /api/v2/parent/billing/portal` — `112`; status `GET /api/v2/parent/checkout/status/{session_id}` — `129` |
| Pause request | `GET /api/v2/parent/pause-requests` — `pause_routes.py:22`; `POST` — `31`; admin: `GET /api/v2/admin/pause-requests`, `POST .../approve` — `27`, `POST .../decline` — `39`. Legacy: `POST /api/pause-requests` — `sessions_routes.py:581`, `POST .../approve` — `634`, `POST .../decline` — `682` |
| Invoice PDF | **Gap** |
| Inbox (parent-scoped) | Generic `/api/messages/*` (admin-style) is used; **dedicated parent endpoints recommended** |

### A.15 Parent Registration (§8.5)

| Need | Current |
|---|---|
| Start application | `POST /api/start` — `onboarding_routes.py:210`; v2: `POST /api/v2/parent/onboarding/start` — `37` |
| Update step | `PATCH /api/{app_id}` — `243`; v2: `PATCH /api/v2/parent/onboarding/{application_id}` — `56` |
| Status poll | `GET /api/{app_id}/status` — `358`; v2: `GET /api/v2/parent/onboarding/{application_id}/status` — `80` |
| Checkout | `POST /api/{app_id}/checkout` — `403`; v2: `POST /api/v2/parent/checkout/start` — `71` |
| Anonymous parent create | `POST /api/v2/parent` — `registration_routes.py:28` |
| Quote | **Gap** |
| Confirmation payload | **Gap** (derived) |

### A.16 Comms & notifications (§6.11, §8.4)

| Need | Current |
|---|---|
| Contacts | `GET /api/messages/contacts` — `comms_routes.py:84` |
| Threads list | `GET /api/messages/threads` — `106` |
| Thread detail | `GET /api/messages/thread/{other_user_id}` — `137` |
| Send | `POST /api/messages` — `158` |
| Notifications list | `GET /api/notifications` — `192` |
| Mark read / read-all | `PATCH /api/notifications/{nid}/read` — `202`; `POST /api/notifications/read-all` — `212` |
| Admin v2 | `GET /api/v2/admin/messages` — `comms_routes.py:20`; `POST .../broadcast` — `41`; `POST .../dm` — `58` |
| Templates, scheduled send, open-rate analytics | **Gap** |

### A.17 Waivers (§6.12, §8.5.5)

| Need | Current |
|---|---|
| Current waiver | `GET /api/waiver/current` — `onboarding_routes.py:179` |
| Admin list | `GET /api/v2/admin/waivers` — `waiver_routes.py:24` |
| Publish version / per-student signature CRUD / bulk-remind | **Gap** |

### A.18 Settings (§6.13)

| Need | Current |
|---|---|
| Get/update settings | `GET /api/settings` — `settings_routes.py:45`; `PATCH` — `60` |
| Payout basis | `POST /api/settings/payout-basis` — `70` |
| v2 academy | `GET /api/v2/admin/academy` — `academy_routes.py:28`; `PATCH` — `37` |
| Fees | `GET /api/v2/admin/academy/fees` — `52`; `PATCH` — `70` |
| Gateway | `GET /api/v2/admin/academy/gateway` — `61` |
| Notifications | `GET /api/v2/admin/academy/notifications` — `85`; `PATCH` — `94` |
| Roles, branding, data retention, account deletion | **Gap** |

### A.19 Background scheduling & email

| Need | Current |
|---|---|
| Scheduler status | `GET /api/scheduler/status` — `scheduler_routes.py:17`; next period `GET /api/scheduler/next-period` — `41` |
| Run monthly invoices | `POST /api/scheduler/run-monthly-invoices` — `26` |
| Run dues reminders | `POST /api/scheduler/run-dues-reminders` — `34` |
| Email send | `POST /api/email/test` — `email_routes.py:119`; `POST /api/email/send-dues-reminders` — `138`; `POST /api/email/welcome/{parent_id}` — `189` |
| Calendar events | `GET /api/calendar/events` — `calendar_routes.py:106` |
| Move log | `GET /api/move-log` — `sessions_routes.py:714` |

### A.20 Webhooks

| Need | Current |
|---|---|
| Stripe (legacy) | `POST /api/webhook/stripe` — `billing_routes.py:768` |
| Stripe (v2 parent) | `POST /api/v2/parent/webhooks/stripe` — `webhook_routes.py:16` |

### Backend gaps (summary)

Items that surfaced as **Gap** above and are most likely to need new endpoints:

1. Admin universal search (`/api/admin/search`).
2. Admin nav counts (`/api/admin/nav-counts`).
3. Bulk-remind for payments / dues (per-selection, not system-wide).
4. Dues-resolve flow (record payment + close dues atomically).
5. Per-dues remind with channel + template body.
6. Recovery sequence config CRUD (Day 0/+2/+5/+14 timeline).
7. Reports in XLSX and PDF formats.
8. Enrollment decline / nudge / bulk-decline.
9. Waitlist offer / revoke / resend / policy CRUD.
10. Session duplicate / pause-session / increase-capacity.
11. Waiver publish-version, per-signature CRUD, bulk-remind.
12. Settings → branding, roles management (CRUD UX), data retention, account deletion.
13. Coach-facing `payout` endpoint.
14. Parent home consolidation endpoint.
15. Parent invoice PDF.
16. Parent-scoped thread endpoints.
17. Registration quote + confirmation payload.
18. Message templates + scheduled send + open-rate analytics.
19. Multi-currency support (most current code assumes a single fixed currency).
20. Background-check status tracking (Enrollments → US-mandated check, not in mock).

---

## Appendix B — Open Questions / Design Ambiguities

See §4.10 for the running list; this appendix will collect per-page additions as they arise.
