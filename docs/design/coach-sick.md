# "Coach is sick" cover flow (S66) and coach "I can't make it" (S67)

Decisions applied: **D-20** (the flow starts from Today), **D-21 option 3** (when cover is assigned the admin chooses each time whether families are told; the box is ticked by default). A coach's request never cancels a class and never messages families; only the front desk's action does.

## 1. Goal and the quotes it answers

When a coach phones in sick, the front desk handles it from one screen: see who is free, put cover in, or cancel, and know exactly which families hear about it and what they are credited.

- admin-ops: "One tap 'coach is sick' that finds a replacement and messages families."
- admin-ops: "Change replacement… saved with no visible success message… Replacement dropdown includes the scheduled coach herself."
- admin-ops: "The Cancel this date dialog is what I wish every screen did."
- coach-new: "A one-tap 'I'm running late / can't make it' that tells the head coach." / "who do I call if I'm late/sick"
- coach-veteran: "substitute request, swap a class"

## 2. Entry points and navigation

Front desk:
- Today quick action **Coach is sick** (`admin-today.md`): opens the flow with nothing preselected.
- Today class card link **Find cover →** (shown when a coach has asked for cover): opens the flow at step 2 for that class date. Same as `/admin?cover=<occurrence_id>`.
- The coach's request in **Messages**: a `Find cover` button on the message goes to `/admin?cover=<occurrence_id>`.
- The class page's existing "Change replacement" and "Cancel this date" stay as they are.

Coach:
- Class page `/coach/sessions/[id]?date=…`, in the header block under the time and venue: a text button **I can't make it**. Shown only for a future class date the coach is assigned to (lead, cover or assistant). Not on Today cards (too easy to tap courtside).

No new frontend routes.

## 3. Front-desk flow

One `RallyModal` (full-height on a phone, 512px on desktop), three steps. Component: `frontend/components/admin/sessions/cover-flow.tsx`.

### Step 1: who and when

```
┌───────────────────────────────────────┐
│ COACH IS SICK                  1 of 3 │
│ Which coach, and which class dates?   │
│ Coach                                 │
│ [ Casey Lee                        ▾ ]│  active coaches with a class in
│                                       │  the next 14 days
│ Casey's class dates                   │
│ ☑ Today, Tue Dec 8 · 5:30 PM          │  today's are pre-ticked
│   Tuesday Intermediate · 3 enrolled   │
│ ☐ Thu, Dec 10 · 5:00 PM               │
│   Thursday Smash Club · 6 enrolled    │
│ ☐ Tue, Dec 15 · 5:30 PM               │
│   Tuesday Intermediate · 3 enrolled   │
│                                       │
│ [ Cancel ]               [ Continue ] │  Continue disabled until ≥1 date
└───────────────────────────────────────┘
```

### Step 2: cover or cancel, one block per chosen class date

```
┌───────────────────────────────────────┐
│ COACH IS SICK                  2 of 3 │
│ Tue, Dec 8 · 5:30 – 6:30 PM           │
│ Tuesday Intermediate · 3 enrolled     │
│                                       │
│ (•) Assign cover                      │  radio group
│     FREE AT THIS TIME                 │
│     ( ) Demo Coach                    │  radio list, 44px rows
│     ( ) Jordan Kim                    │
│     TEACHING THEN                     │
│      –  Priya Nair · Junior Beginners │  not selectable, slate
│         5:00 – 6:00 PM                │
│ ( ) Cancel this class date            │
│ ( ) Leave as it is                    │
│ ───────────────────────────────────── │
│ ☑ Tell the families about the cover   │  D-21, ticked by default;
│   coach (3 families, by email and in  │  applies to every date set to
│   the app)                            │  "Assign cover"
│                                       │
│ [ Back ]                   [ Review ] │
└───────────────────────────────────────┘
```

If nobody is free: under FREE AT THIS TIME, "No other coach is free at this time. Cancel the class date, or leave it and call a coach." Assign cover is disabled for that date.

### Step 3: review (the consequence summary), then confirm

```
┌───────────────────────────────────────┐
│ COACH IS SICK                  3 of 3 │
│ Check before you confirm              │
│ ┌───────────────────────────────────┐ │
│ │ Tue, Dec 8 · Tuesday Intermediate │ │
│ │ Demo Coach covers for Casey Lee.  │ │
│ │ Demo Coach is told in the app.    │ │
│ │ 3 families are emailed:           │ │
│ │ Alvarez, Patel, Walkin            │ │
│ └───────────────────────────────────┘ │
│ ┌───────────────────────────────────┐ │
│ │ Thu, Dec 10 · Thursday Smash Club │ │
│ │ This class date is cancelled.     │ │
│ │ Credits                           │ │
│ │ Brown, Tasha            $20.00    │ │  from the cancel preview
│ │ Kim, Min                $20.00    │ │
│ │ Garcia, Leo    no credit (free)   │ │
│ │ Total credited          $40.00    │ │
│ │ The coach is not paid for it.     │ │
│ │ Reason (families see this)        │ │
│ │ [ Coach unwell                 ]  │ │  required, prefilled, editable
│ │ ☑ Email the families and the coach│ │  existing cancel option
│ └───────────────────────────────────┘ │
│ [ Back ]                  [ Confirm ] │
└───────────────────────────────────────┘
```

Confirm is the only button that changes anything. It is the confirmation tier for this action (it reaches other people), so no second `ConfirmActionDialog` is stacked on top. Add the flow to the confirm-high-impact source test.

### After confirm

The modal shows the result per class date, then a single `Done`:

```
│ ✓ Tue, Dec 8: Demo Coach is covering. 3 families emailed.
│ ✓ Thu, Dec 10: cancelled. 2 families credited $40.00. 6 families emailed.
│ ✕ Tue, Dec 15: could not assign cover. Try again.        [ Retry ]
```

Each date is applied separately; one failure does not undo the others, and the failed one can be retried in place. Today refetches on `Done`.

### Desktop

Same modal at 512px. Steps 2 and 3 scroll inside the modal body (70vh cap).

## 4. Coach flow

```
Class page header                       Dialog (RallyModal sm)
┌──────────────────────────────┐        ┌──────────────────────────────┐
│ Tuesday Intermediate         │        │ CLASS DATE                   │
│ Tue, Dec 8 · 5:30 – 6:30 PM  │        │ Can't make Tue, Dec 8?       │
│ Court 2                      │        │ This tells Demo Academy you  │
│ I can't make it              │  →     │ cannot teach Tuesday         │
└──────────────────────────────┘        │ Intermediate at 5:30 PM.     │
                                        │ The class is not cancelled   │
After sending, the link is replaced by: │ and families are not told.   │
┌──────────────────────────────┐        │ The academy will arrange     │
│ ● COVER REQUESTED            │        │ cover or cancel it.          │
│ You told the academy at      │        │ Reason (optional)            │
│ 7:42 AM. If it is urgent,    │        │ [ Unwell                   ] │
│ call (309) 555-0142.         │        │ [ Keep my class ] [ Tell the │
└──────────────────────────────┘        │                    academy ] │
                                        └──────────────────────────────┘
```

Once cover is assigned the class leaves the coach's list as it does today, and S44 sends "You are no longer teaching…" to their inbox; if it is cancelled it shows struck through with the reason (existing #777 behaviour).

## 5. States

| State | Front desk | Coach |
|---|---|---|
| Loading | Step 1: coach select skeleton; step 2: "Checking who is free…" with skeleton rows; step 3: "Working out credits…" on cancelled dates, Confirm disabled until every preview has loaded | Button shows "Sending…" |
| Empty | Coach has no class dates in 14 days: "Casey has no class dates in the next two weeks." | n/a |
| Error | Availability or preview fails: inline "We could not check this class date." + Retry; that date cannot be confirmed | "We could not tell the academy. Check your connection, or call {phone}." Dialog stays open |
| Partial | Per-date results after confirm (section 3) | n/a |
| Success | Result list + toast "Cover sorted for {n} class date(s)." | Toast "The academy has been told." and the COVER REQUESTED block |
| Already requested | Class card shows the amber chip until cover is assigned or the date is cancelled | The block, never a second button |
| Too late | n/a | Class date has started: the link is not shown |
| Offline | Flow cannot open: "This needs a connection." | Link disabled with "Needs a connection. Call {phone}." (never queued) |
| Date changed underneath | 409 from the write: "This class date changed while you were working. Review it again." and step 2 reloads | n/a |

## 6. Exact copy

Family cover notice (posted as a class announcement and emailed when the box is ticked):
> `{Class} on {Tue, Dec 8} at {5:30 PM} will be taught by Coach {Demo Coach} instead of Coach {Casey}. Same time, same place.`

Coach's message to the academy inbox:
> `{Casey Lee} can't make {Tuesday Intermediate} on {Tue, Dec 8} at {5:30 PM}. Reason: {Unwell}.` (the last sentence only when a reason was typed)

Buttons and labels: `Coach is sick`, `Assign cover`, `Cancel this class date`, `Leave as it is`, `Tell the families about the cover coach`, `Review`, `Confirm`, `Find cover`, `I can't make it`, `Tell the academy`, `Keep my class`. Chips: `COVER REQUESTED` (coach), `COACH CAN'T MAKE IT` (Today card). Words: "class date" for one dated meeting, "cover" for the replacement coach in everything people read (the code keeps `replacement`/`substitute`).

## 7. Components

Reuse: `RallyModal`, `DialogActions`, `DialogError`, `Field`, `Button`, `Chip`, `Skeleton`, `FormField` (`frontend/components/ds/`); `listAdminUsers("coach")` + `assignableCoaches` (`frontend/lib/admin/coach-roles.ts`) for the coach select; the cancel mutation `cancelSessionOccurrence` and replacement mutation used by `CancelOccurrenceDialog` / `OccurrenceReplacementDialog` in `frontend/app/(admin)/admin/sessions/[id]/SessionEditing.tsx`; coach `getCoachAcademy` for the phone.

New: `frontend/components/admin/sessions/cover-flow.tsx`; `frontend/components/coach/cant-make-it.tsx`.

## 8. Data

### 8.1 New: `GET /api/v2/admin/coach-cover/options?coach_id=…` and `?occurrence_ids=a,b`

Module `backend/v2/interfaces/admin/coach_cover_routes.py`, wiring `backend/v2/composition/coach_cover.py`. Admin and owner; tenant scoped; unknown or other-academy ids are 404.

- With `coach_id`: that coach's scheduled class dates from now to +14 days (lead, cover or assistant): `[{occurrence_id, session_id, title, start_at, end_at, enrolled_count}]`.
- With `occurrence_ids` (max 10): per class date:

```json
{"occurrence_id": "…", "title": "Tuesday Intermediate", "start_at": "…", "end_at": "…",
 "scheduled_coach": {"coach_id": "…", "name": "Casey Lee"},
 "enrolled_count": 3,
 "families": [{"parent_id": "…", "family_name": "Alvarez", "has_email": true}],
 "free": [{"coach_id": "…", "name": "Demo Coach"}],
 "busy": [{"coach_id": "…", "name": "Priya Nair", "class_title": "Junior Beginners", "start_at": "…", "end_at": "…"}]}
```

Availability rule (use-case tested): candidates are active users with the coach or assistant-coach role in this academy, **excluding** the class date's scheduled coach and its current cover. A candidate is busy when any non-cancelled class date overlaps `[start_at, end_at)` where they are the scheduled coach, the cover, the actual coach or an assistant. Everyone else is free. There is no availability calendar; "free" means "not teaching then", and the screen says so with the heading "Free at this time".

### 8.2 New: `GET /api/v2/admin/session-occurrences/{occurrence_id}/cancel-preview`

Same module. Calls the existing `CancelSessionOccurrence.preview_missed` (`contexts/enrollment/application/use_cases/cancel_session_occurrence.py`), which prices every family and writes nothing. Returns `{families: [{student_name, family_name, amount_cents, outcome}], credit_total_cents, credit_skips, schedule_changed}`. If `schedule_changed` is true the UI shows the existing "billing has not laid out this date" message and blocks cancel for that date. No money arithmetic in the frontend.

### 8.3 Writes (existing routes, two small extensions)

- Assign cover: `PATCH /api/v2/admin/session-occurrences/{id}/replacement` with `{replacement_coach_id, reason, notify_families}`. `UpdateOccurrenceReplacementRequest` gains `notify_families: bool = False` (default False keeps the class-page dialog's current behaviour). The server rejects, with 409, a coach who is the scheduled coach or is busy under the 8.1 rule (re-checked at write time). When `notify_families` is true it posts the cover notice through `SessionAnnouncementService.post` (`composition/session_announcements.py`) as a **routine** announcement with email on: add an `email: bool | None = None` argument (None keeps today's "email only when urgent"). The response gains `families_notified: int`, `email_failed: int`.
- Cancel: `POST /api/v2/admin/session-occurrences/{id}/cancel` with `{reason, notify}`; unchanged. The result's `credits_issued` and `credit_total_cents` feed the result line.
- The cover coach and the sick coach are told by the S44 schedule-notice handler (in-app and push); this flow adds nothing for them.
- Audit: the replacement use case already records actor and reason; the reason sent is `Cover: coach unavailable` unless the admin typed one.

### 8.4 New: `POST /api/v2/coach/cover-requests`

Module `backend/v2/interfaces/coach/cover_request_routes.py`. Auth `require_coach_surface()`, and the caller must be the class date's scheduled coach, cover or an assistant (`CoachAssignedSessionLookup`; a supervisor passes as elsewhere but the UI does not offer it to them). Body `{"occurrence_id": "…", "reason": "string ≤ 200, optional"}`. 404 when not assigned or other academy; 409 when the class date has started or is cancelled.

Effect: one message in the academy inbox (see `parent-messaging.md` 7.1): `kind="dm"`, `sender_persona="coach"`, `recipient_id=None`, `inbox_thread_id=<coach id>`, `scope_type="cover_request"`, `scope_id=<occurrence_id>`, body as in section 6. Idempotent: if this coach already has a cover-request message for this class date, return it with 200 instead of inserting. **Nothing else happens**: no cancellation, no replacement, no family message, no email. Response `{"requested_at": "…"}`.

`GET /api/v2/coach/cover-requests?occurrence_id=…` returns `{requested_at | null}` for the caller only, so the class page can draw the COVER REQUESTED block after a reload. Path is outside the service worker's coach cache; query key `["coach","cover-request",occurrenceId]`, excluded from persistence (it must never show a stale "requested").

Front-desk visibility: the admin Today read sets `cover_requested: true` on a class date that has such a message **and** still has the same teaching coach and is not cancelled (so the chip clears itself when cover is assigned). The admin attention list gets the line "{Coach} can't make {class}, {date}" linking to `/admin?cover=<id>`. In Messages, a message with `scope_type="cover_request"` renders a `Find cover` button.

Security matrix rows: "Request cover for own class date | Coach: assigned only", "Assign cover / read cover options | Admin: Yes".

## 9. Accessibility

- Steps announce themselves: the modal title region is `aria-live="polite"` ("Step 2 of 3").
- Each class date in step 2 is a `<fieldset>` with the date as `<legend>`; the three choices are a native radio group; the free-coach list is a nested radio group that is `disabled` unless "Assign cover" is selected. Busy coaches are plain text, not disabled radios.
- The credit list in step 3 is a table with headers (Family, Credit); "no credit (free)" is text.
- Results use ✓/✕ icons **with** words; failures have `role="alert"`.
- Coach dialog: focus starts on "Keep my class" (the safe choice); both buttons 50px; the phone number is a `tel:` link.
- All targets 44px on phone; checkboxes and radios have 44px row hit areas via their labels.

## 10. Out of scope

Coach-to-coach swaps; coaches accepting or declining cover; an availability calendar or time-off requests; "running late" from the coach (they call; the front desk has Running late for children); withdrawing a cover request in the app; SMS; automatic choice of a cover coach; cover across multiple academies; changing how cancellation credits are calculated; restoring a cancelled class date (D-13).

## 11. Acceptance checklist

admin-ops (seed K14: a second coach free at Tuesday's time, a third teaching then):
1. Today → Coach is sick → choose Casey → Tuesday is listed and ticked.
2. Step 2 shows the free coach under "Free at this time", the busy one under "Teaching then" with their class, and Casey herself nowhere.
3. Choose the free coach, leave "Tell the families" ticked, Review: it names the cover coach and lists the families who are emailed.
4. Confirm: "Demo Coach is covering. 3 families emailed." Today's card now shows the cover coach.
5. Repeat with "Cancel this class date": the review shows each family's credit and the total **before** Confirm, and a reason is required.
6. Untick "Tell the families": after Confirm, no announcement appears on the class and no family email is logged.
7. With two dates chosen, a failure on one still completes the other and offers Retry.

coach-new (Casey assigned to Tuesday):
8. Open Tuesday's class → "I can't make it" → the dialog says the class is not cancelled and families are not told → Tell the academy → "COVER REQUESTED" with the academy's phone.
9. Reload: still "COVER REQUESTED"; no second request can be sent.

admin-ops again:
10. Today shows "COACH CAN'T MAKE IT" on Tuesday with "Find cover →", one tap into step 2; Messages shows Casey's message with a Find cover button. Nothing is cancelled and no family has been told.

parent-busy:
11. Receives the cover notice (inbox and email) only in the run where the box was left ticked.
