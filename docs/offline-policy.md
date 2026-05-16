# Offline Policy (Coach Attendance)

**Status:** Authoritative. Implementation spec for Wave 1B.
**Ticket:** P0-10
**Last reviewed:** 2026-05-16

The coach uses this app on a phone, on court, on bad wifi. The offline policy below defines exactly what is allowed offline and how conflicts resolve when connectivity returns.

**Scope reminder:** Wave 1A ships **offline reads only**. Wave 1B ships **offline attendance writes** with this conflict model. Until Wave 1B exits, the mutation queue and conflict UI in this document do not exist in production code.

## What is allowed offline

| Operation | Offline allowed? | Notes |
|---|:---:|---|
| Read today's sessions (last sync) | ✅ | Stale-while-revalidate cache, max 24h. |
| Read roster for today's sessions | ✅ | Same cache. |
| Mark attendance (present / absent / late) | ✅ (Wave 1B) | Queued mutation; sync on reconnect. |
| Edit roster (add/remove student) | ❌ | UI disables; "Reconnect to edit roster." |
| Transfer student between sessions | ❌ | |
| Issue refund | ❌ | |
| Modify payment status | ❌ | Coach UI never references payment status anyway. |
| Create / edit session | ❌ | |
| Read lesson plan (last sync) | ✅ | Same cache. |
| Create / edit lesson plan | ❌ | Defer to Wave 2/3. |
| Create progress note | ❌ | Defer; not on Coach Today path. |

UI rule: disabled-but-visible. The coach can see what they can't do, with a clear "You're offline" indicator.

## Conflict cases and resolution

These six cases cover the realistic conflicts. Each has a deterministic server-side resolution and a documented UX outcome.

| # | Conflict | Server Response | Coach UI |
|---|---|---|---|
| 1 | Same student marked twice while offline | Single mutation queued (last-write-wins on device) | One toggle state shown; second tap silently updates the queued state |
| 2 | Coach marked attendance; admin **cancelled the session** while coach offline | `409 SessionCancelled` | "This session was cancelled. Your marks for *{N}* students were not saved." Tap to view + export the queued data. |
| 3 | Coach marked attendance; admin **removed the student** from roster while coach offline | `409 StudentNotEnrolled` | "{Student name} is no longer in this session. Mark not saved." Goes to "Needs review" tray. |
| 4 | Two devices, same coach, both mark the same student differently while offline | First arrival wins (`201`); second returns `409 ConflictAttendanceExists` | Surfaces both states ("Device A marked present at 10:04, Device B marked absent at 10:07") with a "Use Device A" / "Use Device B" choice. |
| 5 | Coach marked wrong session (stale session_id, e.g., schedule changed) | `409 SessionNotAssigned` | "This session is no longer assigned to you. Marks not saved." Logged to local audit. |
| 6 | Payment status changes while coach offline | Not applicable — coach UI never reads or writes payment. | — |

## Sync protocol

Every offline mutation carries:

```json
{
  "mutation_id": "01HXYZ...",          // client-generated ULID
  "session_id": "...",
  "student_id": "...",
  "status": "present" | "absent" | "late",
  "marked_at_client": "2026-05-16T15:43:21.000Z",  // device clock
  "client_app_version": "1.4.2"
}
```

- **Server idempotency** keyed on `mutation_id`. Replays are no-ops returning the original result.
- **Server timestamp wins** for the audit record (`marked_at`). The client timestamp is preserved as `marked_at_client` for forensic clarity.
- **Sync is serial per device** to keep ordering simple. A burst of 50 mutations on reconnect dispatches one at a time.
- **No automatic retry on 4xx** — those are conflicts, not transient failures. Each 4xx surfaces in the "Needs review" tray.
- **Retry on 5xx / network error** with exponential backoff: 1s, 4s, 16s, capped at 60s. After 5 attempts in a single sync run, sync pauses and surfaces a banner. Coach can tap to retry.

## The "Needs review" tray

A coach-side surface listing all mutations that did not apply cleanly. For each:

- The original action (session, student, status, time).
- The reason it didn't apply (one of the six cases above).
- An option: dismiss, export to email, or — for case #4 — choose which device wins.

The tray is the **only** UX surface for offline-write failure. Toasts at sync time are noisy and easy to miss.

## What the server enforces

The server is the source of truth. The client cannot override the server's conflict response — it can only:

- Choose between server-offered options (case #4).
- Dismiss / export (cases #2, #3, #5).
- Replay automatically on transient failure (5xx, network).

Server-side validations (in `coaching.mark_attendance` use case):

1. `mutation_id` deduplication via `@idempotent`.
2. Session must exist, not be cancelled (`SessionCancelled`).
3. Session must be assigned to the requesting coach for the date (`SessionNotAssigned`).
4. Student must be enrolled in the session at the time of the request (`StudentNotEnrolled`).
5. No prior attendance row for `(session_id, student_id)` with a different `mutation_id` (`ConflictAttendanceExists`).

Validation 5 prevents the case where two devices both mark the same student before either syncs.

## Data lifecycle on the device

- **Cached reads** (today + roster + lesson plans): IndexedDB via TanStack Query persistence plugin. Max 7 days. Per-coach scoped.
- **Queued mutations**: IndexedDB via a custom Serwist queue. Max 200 pending; if exceeded, oldest non-conflict mutations are dropped after surfacing in the tray.
- **Reviewed dismissals**: stored locally only. Server never sees dismissed mutations.

On logout, all coach IndexedDB stores are cleared.

## Out of scope for the offline policy

- **Offline-first reconciliation across multiple coaches at the same session.** If a co-coach is added to a session that the original coach is already viewing, the original coach must reconnect to see the second coach's marks. This is acceptable.
- **Time travel.** Coaches cannot mark attendance for past dates while offline. The session_id implies the date, and old sessions are filtered server-side.
- **Anonymous mutations.** Every queued mutation carries the authenticated coach's identity from the cached token. Tokens stale beyond their refresh window invalidate the queue.

## Acceptance for Wave 1B exit

Per [Wave 1B exit gate](tickets/wave-1a-coach-today.md#wave-1b-coach-offline-attendance-writes):

- Each of the six conflict cases above has an automated test and a documented UX outcome (this file).
- 48h soak with synthetic offline coaches produces zero phantom marks.
- Bundle budget regression is zero relative to Wave 1A baseline (W1A-01).

## Change process

Adding a new offline-allowed operation requires:

1. PR updating this document with the conflict cases.
2. PR adding the use-case-level validations.
3. PR adding the device-side queue handling and tray entries.
4. PR adding tests for each new conflict case.

A new offline-allowed operation may not ship until all four merge.
