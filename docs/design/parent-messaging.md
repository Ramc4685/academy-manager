# Parent "Message the academy" (S61 backend, S62 screens)

Decision applied: **D-18 option 1 plus contact details**. A parent writes to the academy, not to a coach. The message opens a thread in the admin Messages screen that every admin and owner can see and answer. Parents and coaches still cannot message each other.

## 1. Goal and the quotes it answers

A parent can ask the academy a question from the app and read the answer in the same place, and can always find a phone number and email.

- parent-busy: "A simple 'message the academy' box that gets an answer."
- parent-busy: "Messages: Empty; parent cannot send, only receive. No way to ask the academy a question."
- parent-new: "I could not find an address or a phone number I could call."
- admin-ops (front desk): "A parent lookup… showing kids, classes, balance and last message."

## 2. Entry points and navigation

- Parent header **Messages** icon (`/parent/messages`): a "Message the academy" card at the top, above announcements.
- Parent **Profile** (`/parent/profile`): new "Contact the academy" card (phone, email, hours, address) with a "Message the academy" button linking to `/parent/messages#academy`.
- Parent Home's existing academy card keeps its phone and email links; add the same "Message the academy" link.
- Admin: the existing **Messages → Direct messages** list (`/admin/messages`). A parent's message appears as a thread under the family's name. Today's attention list links to it (see `admin-today.md`).
- No new routes on either side.

## 3. Layout

### 3.1 Parent Messages, phone (375px)

```
┌───────────────────────────────────────┐
│ Messages                              │  h1
│ ┌───────────────────────────────────┐ │  Card id="academy"
│ │ MESSAGE THE ACADEMY               │ │  Overline
│ │ The front desk reads these. For   │ │  13px slate
│ │ anything urgent today, call       │ │
│ │ (309) 555-0142.                   │ │  tel: link
│ │ ┌───────────────────────────────┐ │ │
│ │ │        Sam will be 10 minutes │ │ │  my message: right, cobalt wash
│ │ │        late on Saturday.      │ │ │
│ │ │              You · 8:02 AM  ✓ │ │ │
│ │ └───────────────────────────────┘ │ │
│ │ ┌───────────────────────────────┐ │ │
│ │ │ Thanks, we'll tell the coach. │ │ │  reply: left, white, slate edge
│ │ │ Demo Academy · 8:15 AM        │ │ │
│ │ └───────────────────────────────┘ │ │
│ │ ┌───────────────────────────────┐ │ │
│ │ │ Write a message…              │ │ │  textarea, 3 rows, grows to 6
│ │ └───────────────────────────────┘ │ │
│ │ 0 / 1000                  [ Send ]│ │  counter + primary lg button
│ └───────────────────────────────────┘ │
│                                       │
│ THURSDAY, NOV 26                      │  existing day groups:
│ ┌ Announcement ─────────────────────┐ │  announcements only from here
│ │ Saturday class moves to Court 3   │ │
│ └───────────────────────────────────┘ │
└───────────────────────────────────────┘
```

The thread shows the last 20 messages oldest-to-newest, with "Show earlier messages" above when there are more. Direct messages no longer appear in the day-grouped list below (they live in the thread); announcements stay there unchanged.

### 3.2 Parent Messages, desktop

Same single column at `max-w-2xl`. Bubbles cap at 70% width.

### 3.3 Parent Profile, "Contact the academy" card (both widths)

```
│ ━━ CONTACT THE ACADEMY ━━━━━━━━━━━━━━ │
│ Demo Academy                          │
│ (309) 555-0142                        │  tel:
│ hello@demo.test                       │  mailto:
│ Mon–Sat 4–8 PM                        │  hours_text, if set
│ 12 Court Lane, Normal IL              │  address, if set
│ [ Message the academy ]               │  secondary button → /parent/messages#academy
```

Placed directly under the page heading, before "Your details".

### 3.4 Admin Messages thread (existing layout, three additions)

```
│ 01 Direct messages                                           │
│ ┌ list ───────────────┐ ┌ thread ─────────────────────────┐ │
│ │ ● Demo Parent       │ │ Demo Parent      Open family →   │ │  (a) link to /admin/families/<id>
│ │   ● NEEDS REPLY     │ │ Sam Demo, Alex Demo              │ │  (b) children line
│ │   Sam will be 10 mi…│ │ ┌ Sam will be 10 minutes late… ┐ │ │
│ │ Lee Family          │ │ │ Demo Parent · 8:02 AM        │ │ │
│ │   You: See you Sat  │ │ └──────────────────────────────┘ │ │
│ └─────────────────────┘ │ ┌ Thanks, we'll tell the coach.┐ │ │
│                         │ │ Marcus (front desk) · 8:15 AM│ │ │  (c) who replied
│                         │ └──────────────────────────────┘ │ │
│                         │ [ Write a reply…       ] [Send]  │ │
```

(a), (b): header shows the family's children and a link to the family record. (c): each staff reply names its author, because any admin can answer. The list row shows a `NEEDS REPLY` chip (Let Amber family) when the newest message in the thread is from the parent. On a phone the existing behaviour holds: the thread replaces the list, with "← Back".

## 4. States

| State | Parent | Admin |
|---|---|---|
| Loading | Card with 3 skeleton lines; composer disabled | existing `MessageSkeleton` |
| Empty thread | Intro text plus: "Ask a question or tell us something. Your message and the reply stay here." | "No DM threads yet." (existing) |
| Sending | Send shows "Sending…", textarea read-only; the bubble appears only after the server accepts it (no optimistic bubble: a message that silently failed is worse than a short wait) | same as today |
| Sent | Bubble appended with ✓, textarea cleared, toast "Message sent to {academy name}." (`meta.success`), focus returns to the textarea | toast "Reply sent." |
| Send failed | Text stays in the box. Inline alert under it: "Your message was not sent. Check your connection and try again." | existing error toast |
| Too many | 429: "You have sent a lot of messages in a short time. Please wait a little, or call {phone}." Send disabled for 60 seconds | n/a |
| Too long | Counter turns red at 1000; Send disabled; "Messages can be up to 1000 characters." | n/a |
| Load error | Existing "Failed to load messages." with Retry; composer hidden | existing |
| Partial | Thread loads but mark-read fails: no visible error (retried on next poll) | same |
| Academy has no phone | The "For anything urgent today, call…" sentence is dropped | n/a |
| New reply arrives | Appears on the existing 30-second poll; unread dot on the header Messages icon (existing shell poll); push where enabled | List row moves to top with `NEEDS REPLY` |

## 5. Exact copy

Parent:
- Card overline `MESSAGE THE ACADEMY`.
- Intro: `The front desk reads these. For anything urgent today, call {phone}.`
- Placeholder `Write a message…`; button `Send`; counter `{n} / 1000`.
- My bubble meta `You · {time}`; reply meta `{academy name} · {time}` (the parent sees the academy's name, never the staff member's).
- Profile card title `Contact the academy`; button `Message the academy`.
- Empty state for the page when there are no announcements either: keep the card, then "No announcements yet."

Admin:
- Chip `NEEDS REPLY`. Reply placeholder `Write a reply…`.
- Attention line on Today: `{n} family message(s) waiting for a reply`.
- Reply meta `{staff display name} · {time}`.

Words: "academy" for the organisation, "message" (not "DM", "ticket" or "chat") in everything a parent reads.

## 6. Components

Reuse: `Card`, `Overline`, `Button`, `Skeleton`, `EmptyState`, `Chip`, `FormField`, `ContactLinks`, `LaneHeader`, `useToast` / mutation `meta.success` (`frontend/components/ds/`); the admin page's existing `DmThreadRow`, `MessageBubble`, `DmComposer` in `frontend/app/(admin)/admin/messages/page.tsx`; `getParentAcademy` (`queryKeys.parent.academy()`), which already returns `contact_phone`, `contact_email`, `hours_text`, `address`.

Changed: `frontend/components/messages/PersonaInbox.tsx` gains an optional `thread` slot prop (rendered above the day groups) and an `excludeDirect` flag. The coach inbox passes neither and is unchanged.

New: `frontend/components/messages/academy-thread.tsx` (thread bubbles and composer for the parent). `sendParentMessage(body)` in `frontend/lib/api/v2/messages.ts`.

## 7. Data

### 7.1 Store change (`backend/v2/shared/comms/messages.py`)

Add one field to `Message`: `inbox_thread_id: str | None = None`: the user id of the family (or coach, see `coach-sick.md`) whose conversation with the academy this message belongs to. No migration: existing documents have no field and behave as today.

- Parent → academy message: `kind="dm"`, `sender_persona="parent"`, `sender_id=<parent>`, `recipient_id=None`, `inbox_thread_id=<parent>`.
- Admin reply (existing `POST /admin/messages/dm`): when the recipient is a parent in this academy, the route also stamps `inbox_thread_id=recipient_id`. Nothing else about that route changes.
- `_visibility_filter` gains one branch: `{"kind": "dm", "sender_id": recipient_id, "inbox_thread_id": recipient_id}` so a parent reads back what they sent. Replies already match the first branch (`recipient_id`).
- `for_admin` gains one branch: `{"kind": "dm", "inbox_thread_id": {"$ne": None}}` so every admin sees every academy-inbox thread, both directions. Private admin-to-admin or admin-to-coach DMs (no `inbox_thread_id`) stay visible to the sender and recipient only.
- `_message_view` in `admin/comms_routes.py`: `counterparty_id` is `inbox_thread_id` when set. The frontend's thread grouping then needs no change. Add `author_display_name` to the admin view for staff replies.

### 7.2 New: `POST /api/v2/parent/messages`

In `backend/v2/interfaces/parent/messages_routes.py`. Auth `require_persona("parent")`; tenant = request academy; sender = `claims.user_id` (no recipient in the body).

Request `{"body": "string"}`. Validation: trimmed, 1–1000 characters, else 422. Rate limit, counted in Mongo so it holds across server instances: at most **10 per hour and 30 per day** per parent (count this sender's `inbox_thread_id` messages in the window); over the limit returns 429 with `Retry-After`. Response 201: the same `ParentMessageView` shape as the list, plus `mine: true`.

`ParentMessageView` gains `mine: bool` (true when `sender_id == caller`) so the client never compares ids.

Side effects: none beyond the insert. No email is sent to the academy and no push to staff in this version (see section 9); staff see it in Messages and on Today.

### 7.3 Reads

- Parent: existing `GET /api/v2/parent/messages` (already polled every 30 s). The thread is the `kind="dm"` rows; announcements are the rest.
- Admin: existing `GET /api/v2/admin/messages`. `needs_reply` is derived on the client from the newest message in each thread (`sender_id == counterparty_id`); it is display state, not a business rule.
- Admin Today count: `admin-today.md` section 7 returns `messages_waiting` from the backend.
- Replies push to the parent through the existing `message_push.direct_message` call in the admin DM route.

### 7.4 Security and caching

- Another family's thread: unreadable (the filter keys on the caller's id) and unpostable (no thread id is accepted from the client). Interface tests for both, plus cross-academy.
- Message bodies are never persisted on the device: parent queries are not in the persister, and `/api/*` is network-only in the service worker. Keep it that way; do not add the thread to any cache.
- `docs/security-matrix.md`: add "Send message to the academy | Admin: reads and replies | Coach: No | Parent: Yes (own thread only)".
- Bodies render as plain text (`whitespace-pre-wrap`), never as HTML, on both sides.

## 8. Accessibility

- The thread is a `<ol>` with `aria-label="Messages with {academy name}"`; each bubble's meta is read first ("You, 8:02 AM").
- New replies are announced through a visually hidden `aria-live="polite"` line ("New reply from {academy name}").
- The textarea has a visible label for screen readers (`<label class="sr-only">Message to the academy</label>`), `aria-describedby` on the counter and any error; errors use `role="alert"`.
- Send is 50px (`size="lg"`); the phone link is a 44px target.
- Sender is conveyed by alignment **and** the "You" / academy name text, not colour alone.
- Enter inserts a new line; Send is a button (no hidden keyboard shortcut on a phone). On desktop, Ctrl/Cmd+Enter sends.

## 9. Out of scope

- Parent ↔ coach messages (needs an academy policy first, per D-18).
- Attachments, photos, read receipts, typing indicators, editing or deleting a sent message.
- Email or push to staff when a parent writes; auto-replies; office-hours rules; assigning a thread to a staff member; closing a thread.
- Showing these messages in the family record's Messages tab (`GET /admin/families/{id}/messages`). The link from the thread to the family record is the bridge for now.
- A separate "Submit feedback" form: the message box is the feedback channel.

## 10. Acceptance checklist

parent-busy:
1. Messages shows "Message the academy" with a text box at the top, at 375px, without scrolling.
2. Send "Sam will be 10 minutes late on Saturday": it appears on the right as "You", the box clears, a toast confirms.
3. After the front desk replies, the reply appears on the left under the academy's name within 30 seconds, and the Messages icon showed an unread dot.
4. Profile shows the academy phone and email as tappable links and a "Message the academy" button.
5. Typing 1001 characters disables Send with the limit message; sending 11 messages in an hour shows the "wait a little" message.
6. Airplane mode: the text stays in the box and the error says it was not sent.

admin-ops:
7. The message appears in Messages under "Demo Parent" with `NEEDS REPLY`, and the thread header lists Sam and Alex with a link to the family.
8. He replies; the chip clears. Logged in as the owner, the same thread and Marcus's reply are visible.
9. A DM he sent to a coach is not visible to the owner (private DMs unchanged).

Security (tester or automated): a second parent cannot see or post into the first family's thread; another academy's admin sees nothing.
