# Coach home: "My week" and first-login welcome (S68)

No owner decision is needed for this step. It builds on S16 (shared coach empty state and academy phone and email on the coach academy read), S44 (in-app notice when a coach is assigned) and S15 (plan tab).

## 1. Goal and the quotes it answers

A coach who opens the app on a day with no class, or for the first time, learns three things without texting anyone: when their next classes are, who to call, and what the academy teaches at each level.

- coach-new: "On day one every screen just says 'No ...' and I don't know if I did something wrong."
- coach-new: "First-login welcome/checklist for coaches: who to contact, how assignments arrive, set availability, add payment info, read the curriculum."
- coach-new: "'Session skill board / Badminton Skill Pathway' is the only badminton content; no explanation of levels."
- coach-new: "A coach library I can read the night before."
- coach-veteran: "The teaching plan… is better than I expected, but I only found it by accident."

## 2. Entry points and navigation

- `/coach/today` (bottom tab **Today**). When the selected day has no class, the page body becomes **My week**. When it has classes, today's list renders as now and a compact "Later this week" list follows it.
- **Welcome card**: top of `/coach/today` until finished or hidden.
- New route `/coach/pathway` (**What we teach**): linked from the welcome card, from My week, and from a new row on `/coach/profile`. Back link "← Today" or "← Profile" (browser back). No bottom-tab entry.
- Contact card: on My week and (from S16) on Profile.

## 3. Layout

### 3.1 Today with no class: My week, phone (375px)

```
┌───────────────────────────────────────┐
│ ‹  Thu, Nov 26  ›                     │  existing day stepper
│ ┌───────────────────────────────────┐ │  Welcome card (3.3), if not done
│ │ WELCOME TO DEMO ACADEMY     1 of 3│ │
│ │ …                                 │ │
│ └───────────────────────────────────┘ │
│ No class today.                       │  15px ink
│                                       │
│ ━━ MY WEEK ━━━━━━━━━━━━━━━━━━━━━━━━━━ │  LaneHeader
│ ┌───────────────────────────────────┐ │
│ │ TUE, DEC 1 · IN 5 DAYS            │ │  Overline
│ │ Tuesday Intermediate              │ │  16px semibold
│ │ 5:30 – 6:30 PM · Court 2          │ │
│ │ 3 children                        │ │  S15 headcount
│ │ [ Read the plan ]  [ Open class ] │ │  secondary lg, 2 columns
│ └───────────────────────────────────┘ │
│ ┌───────────────────────────────────┐ │
│ │ SAT, DEC 5                        │ │
│ │ Junior Beginners (assisting)      │ │
│ │ 9:00 – 10:00 AM · Court 1         │ │
│ └───────────────────────────────────┘ │
│ All upcoming classes →                │  → /coach/sessions
│                                       │
│ ━━ WHO TO CALL ━━━━━━━━━━━━━━━━━━━━━━ │
│ Demo Academy                          │
│ (309) 555-0142                        │  tel:
│ hello@demo.test                       │  mailto:
│ Running late or unwell? Call first.   │
│ You can also tap "I can't make it"    │
│ on the class.                         │
│                                       │
│ ━━ WHAT WE TEACH ━━━━━━━━━━━━━━━━━━━━ │
│ Level 1 · Grip and Control            │  first two levels, one line each
│ Level 2 · Net and Movement            │
│ See all 6 levels and lessons →        │  → /coach/pathway
└───────────────────────────────────────┘
```

"My week" lists class dates from today through the next 7 days. If there are none in 7 days but there is a later one, the lane shows that single next class with "Your next class". The existing "next-class" and "unfinished-recap" blocks on the empty day are replaced by this layout; the unfinished-recap prompt stays, above the lane.

### 3.2 My week with nothing assigned (first day)

```
│ No class today.                       │
│ ━━ MY WEEK ━━━━━━━━━━━━━━━━━━━━━━━━━━ │
│ You have no classes yet.              │  EmptyState, compact
│ Demo Academy adds you to classes.     │
│ When they do, you get a message here  │
│ and the class appears on this screen. │
│ Nothing for you to do until then.     │
│ ━━ WHO TO CALL ━━━━ … (as above)      │
│ ━━ WHAT WE TEACH ━━ … (as above)      │
```

### 3.3 Welcome card (shown until all three are done, or hidden)

```
┌───────────────────────────────────────┐
│ WELCOME TO DEMO ACADEMY       1 of 3 ✕│  ✕ = "Hide this"
│ Three things before your first class  │
│ ☑ Check your phone number             │  → /coach/profile
│   So the academy can reach you.       │
│ ☐ Save the academy's number           │  → scrolls to WHO TO CALL
│   Who to call if you are late or ill. │
│ ☐ Read what Level 1 teaches           │  → /coach/pathway
│   The skills and lesson plans.        │
│ How you hear about classes: the       │  13px slate, not a checkbox
│ academy assigns you, and you get a    │
│ message in the app.                   │
└───────────────────────────────────────┘
```

Each row is a 44px link. A row ticks when its destination has been opened (the phone row ticks only if the profile has a phone number). When all three are ticked the card shows "You're set." for that visit and never appears again.

### 3.4 What we teach, `/coach/pathway`, phone

```
┌───────────────────────────────────────┐
│ ← Today                               │
│ What we teach                         │  h1
│ Badminton Skill Pathway · 6 levels    │  program name
│ Children move up a level when they    │
│ pass that level's skills. You record  │
│ passes on the class's Skills tab.     │
│ ┌───────────────────────────────────┐ │
│ │ LEVEL 1                         ▾ │ │  <details>, first level open
│ │ Grip and Control                  │ │
│ │ Holding the racket and controlling│ │  level description, one line
│ │ the shuttle.                      │ │
│ │ SKILLS                            │ │
│ │ Thumb grip · V grip · Grip change │ │
│ │ · Ready position · Shuttle control│ │
│ │ LESSONS                           │ │
│ │ ▸ 1 · Grips                       │ │  nested <details> per lesson card
│ │ ▾ 2 · Ready position              │ │
│ │   Goal: balanced, racket up…      │ │  goal_summary
│ │   Teaching points                 │ │
│ │   • Feet shoulder width           │ │
│ │   • Racket in front               │ │
│ │   Equipment: rackets, shuttles    │ │
│ │   Safety: space between pairs     │ │
│ │   Activity: mirror drill in pairs │ │
│ └───────────────────────────────────┘ │
│ ┌ LEVEL 2 · Net and Movement      ▸ ┐ │
│ ┌ LEVEL 3 · Serve and Lift        ▸ ┐ │
└───────────────────────────────────────┘
```

### 3.5 Desktop

The coach shell stays single column (`max-w-xl`) at every width. My week cards keep their stacked layout; the two buttons sit on one row. Pathway levels use the same accordion.

### 3.6 Today with classes

Unchanged list, then a quiet "Later this week" lane with the same cards minus the buttons (tap opens the class). The welcome card, if still active, sits above today's list.

## 4. States

| State | My week | Welcome card | What we teach |
|---|---|---|---|
| Loading | Two card skeletons; contact block skeleton lines | Not drawn until the profile read returns (no flash) | Level skeleton blocks |
| Empty | Section 3.2 text | n/a | "The academy has not set up its levels yet. Ask the owner what to teach, or use the plan on your class." |
| Level with no lesson cards | n/a | n/a | Under LESSONS: "No lesson plans for this level yet." |
| Error | Existing coach `RetryButton` with "We could not load your classes." Contact block still renders if its own read succeeded | Hidden | "We could not load the levels." + Retry |
| Offline | Cached classes render (coach schedule is an offline read) with the existing sync-status line | Works (device state) | Cached copy renders if it was opened before; otherwise the error text. This content is not private, so it may be persisted |
| Partial (no academy phone or email) | "Who to call" shows what exists; with neither: "Ask the person who invited you for the academy's number." | Row 2 reads "Find out who to call" and ticks when the block is seen | n/a |
| Success: newly assigned | The S44 inbox message and push arrive; the schedule query is refetched when the app regains focus and on the Messages poll, so the class appears in My week without logging out | n/a | n/a |
| Finished or hidden | n/a | Gone for this coach on this device | n/a |

## 5. Exact copy

- `No class today.` / `My week` / `Your next class` / `All upcoming classes`.
- Day overline: `{TUE, DEC 1}` plus `· TODAY`, `· TOMORROW`, or `· IN {n} DAYS`.
- Role suffix: `(assisting)`, `(covering)`; nothing for the lead.
- Buttons: `Read the plan` (→ `/coach/today/plan?date=<class date>`), `Open class`.
- Empty: as in 3.2, with the academy's name.
- Who to call: `Running late or unwell? Call first. You can also tap "I can't make it" on the class.`
- Welcome: title `Welcome to {academy}`, subtitle `Three things before your first class`, rows and sub-lines as in 3.3, finished `You're set.`, close button label `Hide this`.
- Pathway: `What we teach`; intro sentence as in 3.4; headings `Skills`, `Lessons`, `Teaching points`, `Equipment`, `Safety`, `Activity`.
- Profile row: `What we teach` with sub-line `Levels, skills and lesson plans`.
- Words: "class" and "class date"; never "session", "occurrence" or "curriculum" in headings ("What we teach" is the name).

## 6. Components

Reuse: `Card`, `LaneHeader`, `Overline`, `Button`, `EmptyState`, `Skeleton`, `ContactLinks` (`frontend/components/ds/`); `RetryButton` (`frontend/components/coach/RetryButton.tsx`); the shared coach empty state S16 adds; `getCoachSchedule` (`queryKeys.coach.schedule()`), `getCoachAcademy`, `getCoachProfile` (`frontend/lib/api/coach.ts`); `formatAcademyDay`, `formatAcademyTimeRange` (`frontend/lib/format/academy-time.ts`). Native `<details>/<summary>` for the accordions (no new accordion component).

New: `frontend/components/coach/my-week.tsx`, `frontend/components/coach/welcome-card.tsx`, page `frontend/app/(coach)/coach/pathway/page.tsx`, API function `getCoachPathway()`.

## 7. Data

| Element | Source |
|---|---|
| My week cards | Existing `GET /api/v2/coach/sessions` (`CoachScheduleEntry`: title, location, start/end, occurrence id). Filter to the next 7 days on the client using the academy timezone on each entry (presentation only). Headcount and role come from the fields S15 adds to this read (`headcount`, `my_role: lead \| cover \| assistant`); if S15 did not add `my_role`, add it here in `sessions_routes.py`. |
| Who to call | `GET /api/v2/coach/academy`: `contact_phone`, `contact_email` (added by S16; if absent, add them to `CoachAcademyView` here, read from the same academy profile the parent academy view uses). |
| Welcome row 1 | `GET /api/v2/coach/profile` → `phone` non-empty. |
| Welcome progress | `localStorage["coach-welcome:" + user_id]` = `{contact: bool, pathway: bool, hidden: bool}`. Read and written in `welcome-card.tsx` inside try/catch; if storage is unavailable the card simply shows every time. `shortcut: per device, so a coach on a new phone sees it again; move to a profile field if that annoys anyone.` Cleared on logout is **not** required (it holds no personal data). |
| What we teach (teaser and page) | New `GET /api/v2/coach/pathway`. |

### 7.1 New: `GET /api/v2/coach/pathway`

Add to `backend/v2/interfaces/coach/academy_routes.py` (it is academy reference content, not student data). Auth `require_coach_surface()`; tenant = request academy. Reads the academy's programs, levels, skills and lesson cards through the existing curriculum use cases the admin routes call (`curriculum.list_programs`, the pathway read, `curriculum.list_lesson_cards` in `backend/v2/interfaces/admin/pathway_routes.py`). Read-only; no student or progress data.

```json
{"programs": [{
  "program_id": "…", "name": "Badminton Skill Pathway",
  "levels": [{
    "level_id": "…", "sequence": 1, "name": "Grip and Control", "description": "…",
    "skills": [{"skill_id": "…", "name": "Thumb grip"}],
    "lessons": [{"card_id": "…", "lesson_number": 1, "title": "Grips", "goal_summary": "…",
                 "teaching_points": ["…"], "equipment": ["…"], "safety_notes": ["…"],
                 "activity_summary": "…", "video_url": null}]
  }]
}]}
```

- Retired levels and skills are excluded. Citation-only fields on lesson cards (`source`, `module_name`, `lesson_range`, PDF reference links) are not returned; `video_url` is the card's first resource link that has a URL, else null (shown as a "Watch the drill" link).
- If the academy has more than one program, the page shows a program select above the levels; the teaser on My week uses the first program.
- Caching: this is not private. Query key `["coach","pathway"]`; it may be persisted by the coach persister (default behaviour) so it reads offline. The path is outside the service worker's `(today|sessions)` matcher, which is fine.
- Security matrix: "Read the academy's levels and lesson plans | Admin: Yes | Coach: Yes | Parent: No".

### 7.2 Route bookkeeping

New route `/coach/pathway`: manifest entry (role `coach`; states `loading`, `empty`, `error`) and the two hard-coded route counts. S60 adds `/coach/profile/pay` in the same way; if both land together the counts go up by two.

## 8. Accessibility

- My week is a list (`<ul>`); each card's heading is the class name (`<h3>`), with the day as text before it so a screen reader hears "Tuesday, December 1, in 5 days. Tuesday Intermediate."
- Welcome card: a `<section aria-labelledby>`; rows are links, with done state as text for assistive tech ("Done: Check your phone number"), not only a tick glyph. "Hide this" is a labelled 44px button; hiding moves focus to the page heading.
- Accordions are native `<details>`, keyboard-operable by default; summaries are at least 44px tall.
- Lesson lists are real `<ul>`s; headings inside a level are `<h3>`/`<h4>` in order.
- Phone and email are real links. All targets 44px (`min-h-touch`), sticky header safe-area respected.
- No motion beyond the existing fade; respects `prefers-reduced-motion`.

## 9. Specified here, not built in S68

These two were asked for by both coaches. They are recorded so a later step has a starting point.

- **Availability and time off.** A coach marks weekly unavailable blocks and dated time off on Profile; the cover flow's "Free at this time" list (`coach-sick.md` 8.1) would then also exclude unavailable coaches and label them "Not available". Needs a new store and an owner decision on whether availability is binding. Until then, "free" means "not teaching then".
- **Payment details.** A coach records how they want to be paid (bank transfer, Zelle handle, check) on Profile, visible to the owner on Payouts. It is sensitive financial data: it needs its own never-cached endpoint, masking in the UI, an audit row on change, and a security-matrix row before it is built. No bank numbers are collected anywhere today.

## 10. Out of scope

Drill videos, a searchable drill library, court boards, season plans; editing the pathway from the coach app; a head-coach "shadow mode"; a "first week" video guide; coach-to-coach or coach-to-parent messages; email notice of assignment (S54); pay (see `coach-pay.md`); health alerts (S50).

## 11. Acceptance checklist

coach-new (seed: Casey with no class today, one next week; lesson cards for Level 1; academy phone and email set):
1. First login, no classes at all: Today says "You have no classes yet" and explains that the academy assigns classes and a message will arrive. Nothing reads like an error.
2. She can name who to call: the academy phone is on the same screen and is tappable.
3. The welcome card shows three items; opening Profile (with a phone saved), the contact block, and What we teach ticks them; the card then disappears and stays gone after a reload.
4. What we teach: Level 1 is open, has a one-line description, its skills, and lesson cards with goal, teaching points, equipment and safety.
5. After the admin assigns her to Tuesday (no logout): a message arrives, and returning to Today shows Tuesday Intermediate under My week with "IN {n} DAYS".
6. "Read the plan" opens that class date's teaching plan; "Open class" opens the class.
7. On a day she does have a class, today's list is first and "Later this week" follows.

coach-veteran:
8. With a class today, nothing about Today's existing list has moved or disappeared; the welcome card can be hidden with one tap.
