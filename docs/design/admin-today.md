# Admin Today (S63 read model, S64 classes and roster sheet, S65 quick actions and phone search)

Decisions applied: **D-20 option 2** (the dashboard starts with Today; money below for owners; no second screen) and **D-14 option 3** (health marker on the roster, note on tap, never stored, never in lists or exports; "None declared" differs from "Not answered").

The plan asked for an HTML prototype approved by the owner before building. The owner has accepted the recommendation and asked for the build tonight, so the wireframes below are the agreed design (copied here in the S63 commit).

## 1. Goal and the quotes it answers

Standing at the desk with a phone, the front desk can answer "who is in the 9:00 class and what is Sam's mum's number" in under ten seconds, and start the four things that happen every day without hunting through menus.

- admin-ops: "A Today screen with big buttons: absent, running late, coach sick, new walk-in."
- admin-ops: "I want a 'who is in class today' view with parent phone and allergies."
- admin-ops: "Setup checklist dominates top, especially on phone; 'needs attention' and today's classes are pushed down."
- admin-ops: "A parent lookup by phone number showing kids, classes, balance and last message." / "Printable roster."
- admin-owner: "The setup checklist on the dashboard tells me what is left" and the money tiles "all moved together, which makes me trust it" (so they stay, below).

## 2. Entry points and navigation

- `/admin` (the existing dashboard route; sidebar item under the TODAY group). No new route.
- Roster sheet: a `Modal` over `/admin`, opened by tapping a class card. Deep link `/admin?class=<occurrence_id>` opens it (used by push and by the cover flow). Closing removes the param.
- Quick actions open dialogs over `/admin`; `/admin?cover=<occurrence_id>` opens the cover flow (`coach-sick.md`).
- Phone search lives in the existing header `PeopleSearch` (every admin page), not only here.

## 3. Page order (how the dashboard, money and checklist relate)

| # | Block | Who | Change |
|---|---|---|---|
| 1 | **Today**: date line, quick actions, classes now and next | all staff | new |
| 2 | Needs your attention | all staff | existing; gains cover-request and family-message lines |
| 3 | My follow-ups | all staff | existing, unchanged |
| 4 | Setup checklist | all staff | existing; S09 already collapses it to one line of remaining steps. It sits here, never above Today, and disappears when nothing remains |
| 5 | Money tiles (Owed, Autopay, Needs action, Revenue for owners) | Revenue owner-only, as today | existing; the "Sessions today" tile is **removed** (block 1 replaces it) |
| 6 | Class report handoffs, revenue chart | owner | existing |
| 7 | Recent payments | all staff | existing (S09 phone rows) |

Front-desk admins see 1–5 and 7 with no revenue tile, exactly the visibility rules of today.

## 4. Layout

### 4.1 Phone (375px)

```
┌───────────────────────────────────────┐
│ TODAY · THU, NOV 26                   │  Overline (academy date)
│ ┌─────────────────┐ ┌───────────────┐ │
│ │  Absent         │ │ Running late  │ │  2×2 grid, each 64px tall,
│ └─────────────────┘ └───────────────┘ │  Button secondary, icon + label
│ ┌─────────────────┐ ┌───────────────┐ │
│ │  Coach is sick  │ │ New walk-in   │ │
│ └─────────────────┘ └───────────────┘ │
│                                       │
│ ━━ CLASSES TODAY ━━━━━━━━━━━━ 3 ━━━━━ │  LaneHeader + count
│ ┌───────────────────────────────────┐ │
│ │ ● NOW        4:30 – 5:30 PM       │ │  Chip + time, 15px semibold
│ │ Junior Beginners                  │ │
│ │ Coach Demo · Court 1              │ │  13px slate
│ │ 11 enrolled · 9 here · 1 absent   │ │
│ │ ⚑ 1 health note                  →│ │  red-800 text + flag icon
│ └───────────────────────────────────┘ │
│ ┌───────────────────────────────────┐ │
│ │ ● NEXT · in 25 min  5:30 – 6:30 PM│ │
│ │ Tuesday Intermediate              │ │
│ │ Coach Casey · Court 2             │ │
│ │ 3 enrolled · not marked yet       │ │
│ │ ● COACH CAN'T MAKE IT  Find cover→│ │  amber chip + link (coach-sick)
│ └───────────────────────────────────┘ │
│ ┌───────────────────────────────────┐ │
│ │ ● CANCELLED  7:00 – 8:00 PM       │ │  struck-through title
│ │ Adult Social · Gym flooded        │ │
│ └───────────────────────────────────┘ │
│ Tomorrow: 2 classes, first at 9:00 AM │  one line, links to /admin/sessions
│                                       │
│ ━━ 00 NEEDS YOUR ATTENTION ━━━━━━━━━━ │  existing blocks continue
└───────────────────────────────────────┘
```

### 4.2 Desktop (≥1024px)

```
┌ sidebar ┐ ┌──────────────────────────────────────────────────────────────┐
│ TODAY   │ │ TODAY · THU, NOV 26      [Absent][Running late][Coach is sick][New walk-in] │
│ ▌Today  │ │ ━━ CLASSES TODAY ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 3 │
│  Inbox  │ │ ┌───────────────────┐ ┌───────────────────┐ ┌───────────────┐ │
│  …      │ │ │ ● NOW 4:30–5:30   │ │ ● NEXT · in 25 min│ │ ● CANCELLED   │ │  3-column grid of
│         │ │ │ Junior Beginners  │ │ Tuesday Intermed. │ │ Adult Social  │ │  the same cards
│         │ │ │ 11 · 9 here       │ │ 3 · not marked    │ │ Gym flooded   │ │
│         │ │ │ ⚑ 1 health note   │ │ COACH CAN'T MAKE… │ │               │ │
│         │ │ └───────────────────┘ └───────────────────┘ └───────────────┘ │
│         │ │ ┌ 00 Needs your attention ──────┐ ┌ My follow-ups ───────────┐ │
│         │ │ ┌ Owed ─┐ ┌ Autopay ┐ ┌ Needs action ┐ ┌ Revenue (owner) ┐    │
└─────────┘ └──────────────────────────────────────────────────────────────┘
```

Quick actions are 38px `md` buttons in the header row on desktop.

### 4.3 Roster sheet (Modal; full-height on phone, 512px `lg` on desktop)

```
┌───────────────────────────────────────┐
│ CLASS DATE                         ✕  │  RallyModal overline
│ Junior Beginners                      │  title
│ Thu, Nov 26 · 4:30 – 5:30 PM · Court 1│
│ Coach Demo                            │
│ [ Print roster ]  [ Open class ]      │  secondary sm; Open → /admin/sessions/<id>
│ ─────────────────────────────────────│
│ ⚑ 1 health note in this class         │  strip; only if count > 0
│ ─────────────────────────────────────│
│ Alex Demo                    ● PRESENT│  PhoneListRow
│ Demo Parent · (309) 555-0120       📞 │  tel: link, 44px
│ ─────────────────────────────────────│
│ Sam Demo  ⚑                  ● ABSENT │  ⚑ = button "Health note"
│ Demo Parent · (309) 555-0120       📞 │
│  ┌─────────────────────────────────┐ │  expands in place on tap
│  │ HEALTH NOTE                     │ │
│  │ Peanut allergy, carries EpiPen  │ │
│  │ Emergency contact               │ │
│  │ Rosa Demo · (309) 555-0177   📞 │ │
│  └─────────────────────────────────┘ │
│ ─────────────────────────────────────│
│ Dev Patel               ● NOT MARKED  │
│ Asha Patel · no phone on file         │
│ Health: not answered                  │  slate, shown on expand only
│ ─────────────────────────────────────│
│ Lucia Alvarez  TRIAL    ● EXPECTED ABSENT │
└───────────────────────────────────────┘
```

Sorted by first name. Attendance is read-only here; corrections stay on the class page (S25).

Print (`Print roster`): one page, class title, date, time, coach, then a table: `#`, Name, Parent, Phone, a blank "Here" tick box. A child with a declared note prints `⚑` beside the name and the footer line "⚑ Health note on file. Notes are not printed; open the roster on a phone to read them." Health text and emergency contacts never print (D-14: never in exports).

### 4.4 Quick actions

| Button | Opens | Notes |
|---|---|---|
| **Absent** | existing `RecordAbsenceDialog` (`frontend/components/admin/requests/request-queues.tsx`; export it) | New optional props `initialStudentId`, `initialOccurrenceId`; today's classes listed first in its class select. No email is sent (its existing rule). |
| **Running late** | new `RunningLateDialog` | Step 1: pick the child from today's rosters (search box over the Today data). Step 2: preview "Sam Demo is running late for Junior Beginners (4:30 PM)." with an optional "How late?" field (free text, 40 chars) and the line "This sends a message to Coach Demo. Attendance is not changed." Button `Tell the coach`. |
| **Coach is sick** | cover flow | see `coach-sick.md` |
| **New walk-in** | existing `QuickAddFamily` (`frontend/app/(admin)/admin/families/QuickAddFamily.tsx`), rendered here with its dialog opened by this button | Class select defaults to the class that is NOW or NEXT. |

### 4.5 Phone search (in `PeopleSearch`)

Typing 4 or more digits (spaces, dashes, brackets and a leading `+1` ignored) adds a "Phone matches" group at the top:

```
│ 🔍 555 0120                           │
│ PHONE MATCHES                         │
│ Demo Parent · (309) 555-0120          │
│ Sam Demo, Alex Demo                 → │  → /admin/families/<parent_id>
```

## 5. States

| State | Today block | Roster sheet |
|---|---|---|
| Loading | Quick actions render at once; three card skeletons (`Skeleton variant="block" height="7rem"`) | Rows as `TableSkeleton`; header from the card data |
| Empty | `EmptyState` title "No classes today", description "Tomorrow: 2 classes, first at 9:00 AM." or "Nothing scheduled this week." Quick actions stay | "No children in this class yet." with `Open class` |
| Error | `ErrorNotice` "We could not load today's classes." + Retry. Quick actions still work. Other dashboard blocks load independently | "We could not load this roster." + Retry |
| Partial: health read fails or offline | n/a (cards show no health count; see below) | Rows render; strip reads "Health notes need a connection. Retry." No marker is drawn, so absence of a flag is never read as "no notes" |
| Health setting off for the academy | No health line on cards; no strip; no flags; nothing printed | same |
| Success (action) | Toasts: "Absence recorded for Sam Demo." / "Coach Demo has been told Sam Demo is running late." / existing QuickAdd result | n/a |
| Refresh | Refetch every 60 s while the tab is visible and on focus; the NOW/NEXT chips come from the server, never the device clock | Refetch on open |

## 6. Exact copy

- Header overline: `TODAY · {THU, NOV 26}`. Lane: `Classes today`.
- Phase chips: `NOW`, `NEXT · in {n} min` (under 60 min), `NEXT`, `LATER`, `FINISHED`, `CANCELLED`.
- Count line: `{n} enrolled · {n} here · {n} absent` once any mark exists; before that `{n} enrolled · not marked yet`. "Here" = present + late.
- Health: `⚑ {n} health note(s)`; sheet labels `Health note`, `Emergency contact`, `Health: none declared`, `Health: not answered`.
- Attendance chips: `PRESENT`, `LATE`, `ABSENT`, `NOT MARKED`, `EXPECTED ABSENT`. Tags: `TRIAL`, `MAKE-UP`.
- Missing phone: `no phone on file`.
- Buttons: `Absent`, `Running late`, `Coach is sick`, `New walk-in`, `Print roster`, `Open class`, `Tell the coach`.
- Words: "class", "class date", never "session" (rename the removed tile's concept accordingly).

## 7. Components

Reuse: `Card`, `Chip`, `LaneHeader`, `Overline`, `Button`, `RallyModal`, `PhoneList`/`PhoneListRow`, `ContactLinks`, `Skeleton`/`TableSkeleton`, `EmptyState`, `ErrorNotice` (`frontend/components/ds/`); `useAcademyTimezone` (`frontend/components/admin/use-academy-today.ts`); `formatAcademyTimeRange`, `formatAcademyDay` (`frontend/lib/format/academy-time.ts`); the print pattern from `frontend/components/waivers/signed-waiver-document.tsx`.

New, in `frontend/components/admin/today/`: `today-classes.tsx` (cards), `roster-sheet.tsx` (modal and print table), `quick-actions.tsx`, `running-late-dialog.tsx`. API functions `getAdminToday(date?)`, `getAdminTodayRosterHealth(occurrenceId)` in `frontend/lib/api/admin.ts`. Add the sheet to `frontend/app/admin-lists-are-phone-ready.test.ts`.

## 8. Data

### 8.1 New: `GET /api/v2/admin/today?date=YYYY-MM-DD`

`backend/v2/interfaces/admin/today_routes.py`, wired in `composition/admin_today.py`. Auth `require_persona("admin")` (admins and owners); tenant = request academy; `date` defaults to today on the academy clock. Build it on what the coach surface already uses for supervisors: `list_today.execute_for_academy(date, include_cancelled=True)` plus `get_occurrence_roster` and the existing-marks read (`backend/v2/interfaces/coach/today_routes.py`), then add parent name and phone from `users` in one batched `$in` read.

```json
{
  "date": "2026-11-26", "timezone": "America/Chicago",
  "classes": [{
    "occurrence_id": "…", "session_id": "…", "title": "Junior Beginners", "location": "Court 1",
    "start_at": "…", "end_at": "…", "status": "scheduled", "cancellation_reason": null,
    "phase": "now", "starts_in_minutes": null,
    "coach_id": "…", "coach_name": "Demo Coach", "cover_coach_name": null,
    "cover_requested": false,
    "enrolled_count": 11, "here_count": 9, "absent_count": 1, "marked_count": 10,
    "roster": [{
      "student_id": "…", "full_name": "Sam Demo", "kind": "enrolled",
      "attendance": "absent", "expected_absent": false,
      "parent_id": "…", "parent_name": "Demo Parent", "parent_phone": "(309) 555-0120"
    }]
  }],
  "tomorrow": {"class_count": 2, "first_start_at": "…"},
  "messages_waiting": 1,
  "health_enabled": true
}
```

`phase`, counts and `messages_waiting` (academy-inbox threads whose newest message is from the family; see `parent-messaging.md`) are computed in the backend. `cover_requested` per `coach-sick.md`. **No health or emergency-contact field appears in this response**, so it is safe to refetch and to keep in the query cache.

### 8.2 New: `GET /api/v2/admin/today/roster-health?occurrence_id=…`

Same module. Admin and owner only, tenant scoped, 404 for an occurrence in another academy. Reads through the **same batched reader S49 builds** (`composition/coach_roster_health.py`); do not write a second one. Returns 404 when the academy's health setting is off.

```json
{"occurrence_id": "…", "declared_count": 1, "children": [
  {"student_id": "…", "status": "declared", "note": "Peanut allergy, carries EpiPen",
   "emergency_contact_name": "Rosa Demo", "emergency_contact_phone": "(309) 555-0177"},
  {"student_id": "…", "status": "none_declared"},
  {"student_id": "…", "status": "not_answered"}]}
```

Caching rules (health data is never cached):
- Response header `Cache-Control: no-store`.
- Query key `["admin","today","roster-health", occurrenceId]` with `gcTime: 0`, `staleTime: 0`, `refetchOnWindowFocus: false`; fetched only while the sheet is open; removed from the query cache on close (`queryClient.removeQueries`).
- The card's "⚑ n health notes" line is fetched the same way for the classes on screen, one request each, and shows nothing until the read succeeds. It is a count only.
- Never written to localStorage, never in the Today payload, CSV exports, print, emails, push or AI input. Add a test that the admin Today response model has no health fields, and a `sw.ts` test that this path is not matched by any caching rule.
- `docs/security-matrix.md`: "Read a class date's health notes | Admin: Yes (own academy) | Coach: assigned only (S49) | Parent: No".

### 8.3 Running late

No new endpoint. `POST /api/v2/admin/messages/dm` (existing) once per coach on the class date (lead or cover, plus assistants), body exactly `{child} is running late for {class} ({start time}). {how late}` and nothing else about the child. The existing push path notifies the coach. No attendance mark is written; the coach marks Late on arrival.

### 8.4 Phone search

`GET /api/v2/admin/users` (in `directory_routes.py`) gains `phone: str | None`. Server strips non-digits and a leading country `1`; requires at least 4 digits (else 422); matches parents in the request academy whose stored phone, normalised the same way, **contains** the digits; returns at most 10, each with `children: [names]`. `PeopleSearch` calls it only when the trimmed input has 4+ digits and no letters.

### 8.5 Existing reads kept

Attention (`listAdminAttention`), collections, payment feed, revenue (owner only) are unchanged. Remove the `listAdminSessions(today)` query that fed the deleted tile.

## 9. Accessibility

- Each class card is one `<button>` with an accessible name such as "Junior Beginners, now, 4:30 to 5:30 PM, 11 enrolled, 9 here. Open roster." The "Find cover" link inside the card is a separate focusable element, not nested in the button (render the card as a `div` with a stretched button plus the link above it).
- Phase and attendance use `Chip` (dot and word). The health flag is an icon **and** the words "Health note"; the per-row flag is a `<button aria-expanded>` labelled "Health note for Sam Demo".
- Quick-action buttons are 64px tall on phones, labelled with text (icons are decorative, `aria-hidden`).
- Modal: focus trap, Escape closes, focus returns to the card (provided by `Modal`).
- Phone numbers are `tel:` links with the name in the label ("Call Demo Parent").
- The 60-second refresh must not move focus or scroll; phase changes are not announced.
- Print table has a `<caption>` and `<th scope="col">`.

## 10. Out of scope

Marking or correcting attendance from the sheet; SMS or WhatsApp; a call log from the sheet (the family record has it); balance and last message in the phone-search result (the result links to the family record, which shows both); a day picker on Today (the class list and calendar cover other days); drag-and-drop court boards; undo for twenty minutes; changing which staff see money.

## 11. Acceptance checklist

admin-ops, phone at 375px (seed: two classes today, parent phones, K04):
1. `/admin` opens with TODAY, four buttons and today's classes before anything else; the setup checklist is below Needs attention as one line.
2. Tap the 9:00 class: within ten seconds he reads who is in it and taps Sam's parent's number to call.
3. Sam's row shows ⚑; tapping it shows "Peanut allergy, carries EpiPen" and the emergency contact. Another child reads "Health: none declared", a third "Health: not answered".
4. Go offline and reopen the sheet: names and phones may fail to load, and no health text is shown from memory.
5. Print roster: one page, names and phones, ⚑ beside Sam, no health text.
6. Absent → pick Sam and today's class → "Absence recorded for Sam Demo."
7. Running late → Sam → Tell the coach; logged in as the coach, the message is in Messages; attendance is unchanged.
8. New walk-in opens the add-family steps with the current class preselected.
9. Search "555 0120" from the header: Demo Parent appears with Sam and Alex and opens the family.
10. Another academy's admin sees none of this academy's classes.

admin-owner:
11. The money tiles, revenue chart and recent payments are all still there, below Today; there is no "Sessions today" tile.
