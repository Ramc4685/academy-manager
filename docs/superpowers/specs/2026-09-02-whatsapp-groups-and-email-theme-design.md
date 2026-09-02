# WhatsApp class groups in outbound email + unified email theme

**Date:** 2026-09-02
**Status:** Approved (design interview 2026-09-02), slice 1 in progress

## Problem

Each class at the academy has its own WhatsApp group. Parents and coaches are
expected to be in the groups for the classes they attend or teach, and in no
others. Today nothing in the product knows those groups exist: the only
WhatsApp support is a `wa.me` click-to-chat link on the admin dues report.
Admins chase families by hand, and families drift into stale groups when a
child moves class.

Separately, the outbound emails are built from three different visual systems
(billing shell, coach digest, parent digest) plus four copy-pasted style
blocks, none of which use the app's Rally design palette. Several copy bugs
were found while reviewing them (see *Style findings*).

## Goals

1. Every recurring class email tells the recipient which WhatsApp groups they
   belong in, with a one-tap join link, and asks them to leave any other class
   group.
2. The group link lives on the session (one group per class) and is entered by
   the admin on the session form. Emails read it from there.
3. All outbound email shares one theme derived from the app's Rally palette,
   one header/footer shell, and a plain-text alternative.

## Non-goals

- Verifying who is actually in a WhatsApp group (needs the paid Business API).
- Sending WhatsApp messages automatically.
- Tracking "joined" state per enrollment.
- Redesigning campaign authoring beyond a single merge tag.

## Decisions from the design interview

| Question | Decision |
|---|---|
| What is one group? | One group per session (class). |
| Where is the link stored? | On the session, entered via the admin session form. |
| Which emails carry the block? | Parent daily digest, coach daily digest, new enrollment confirmation email, admin campaigns via merge tag. |
| "Leave wrong groups" mechanism | Plain instruction text under the list. No tracking. |
| Frequency in digests | Compact strip in every digest, no state. |
| Theme | Use the app (Rally) theme; keep it email-safe and readable. |
| Review | Show rendered mockups before any template ships. |

## Architecture

```
admin session form ──► Session.whatsapp_group_url (enrollment context)
                                   │
                                   ▼
        composition data providers (parent digest, coach digest,
        enrollment confirmation, campaign merge)
                                   │  list[WhatsAppGroupLink]
                                   ▼
   communications: render_whatsapp_groups_block(links, persona) ── pure HTML+text
                                   │
                                   ▼
        shared/comms/email_theme.py  ── palette, fonts, shell, button, text twin
```

Contexts may not import each other (ADR-0005, layering test). The theme
module therefore lives in `backend/v2/shared/comms/`, which every context and
the composition root may import. The WhatsApp block renderer is a pure
function in the communications context; the composition root assembles the
input list from enrollment data, the same way the digest providers work today.

## Slices

Each slice is its own PR against `main`, in this order. Slices 4 and 5 may be
deferred without blocking the others.

### Slice 1 — session field + admin form

- `Session.whatsapp_group_url: str | None = None` in
  `contexts/enrollment/domain/models.py`.
- Validation: blank/None allowed; otherwise must match
  `https://chat.whatsapp.com/<token>` where token is 1–64 URL-safe chars. Any
  other host is rejected with a domain error (`InvalidWhatsAppGroupUrl`, HTTP
  422). Rationale: `wa.me` and phone links are personal chats, not groups, and
  a typo here would send every family a dead link.
- Mongo repo reads/writes the field; missing field reads as `None` so
  existing documents need no migration.
- Admin create-session and edit-session commands, request models, and views
  carry the field. Parent and coach session views expose it read-only
  (`whatsapp_group_url`) so the portal can show a join link later.
- Admin session edit page gets a "WhatsApp group invite link" input with
  helper text ("Paste the group's invite link from WhatsApp › Group info ›
  Invite link") and inline validation error.
- Tests: domain validation unit test, repo round-trip, admin route 422 on bad
  host, edit-page e2e extended with the new field, route-manifest audit tests
  updated if a route is added (none expected).

### Slice 2 — shared theme + WhatsApp block + digest wiring

**Theme module** `shared/comms/email_theme.py`, single source for:

| Token | Value | Rally source |
|---|---|---|
| font | `Manrope, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif` | `--font-manrope` (Manrope is not loadable in most clients; the stack degrades to system sans) |
| ink | `#0f172a` | rally.ink |
| muted | `#64748b` | rally.muted |
| line | `#e2e8f0` | rally.line |
| paper | `#f8fafc` | rally.paper |
| cobalt | `#2563eb` | rally.cobalt.600 |
| cobalt-hover | `#1d4ed8` | rally.cobalt.700 |
| cobalt-soft | `#eff6ff` | rally.cobalt.50 |
| volt | `#facc15` | rally.volt.400 |
| volt-soft | `#fef9c3` | rally.volt.100 |
| night | `#0a0f1c` | rally.night |
| status green/amber/red | `#ecfdf5/#065f46`, `#fffbeb/#92400e`, `#fef2f2/#991b1b` | status.* |
| max width | 560px | (compromise between the three current widths) |

Exports: `shell(academy_name, inner_html, *, brand_color=None, logo_url=None,
footer_note=None)`, `button(label, url, *, variant="primary"|"secondary")`,
`chip(text, tone)`, and `html_to_text(html)` for the plain-text twin. The
shell renders a slim header (logo if present, else academy name), a 3px
cobalt rule with a volt accent, the body, and a footer with the academy name
and contact email/phone when the academy record has them. `brand_color`
overrides cobalt when the academy has set one.

Every email in the inventory switches to the shell. Identity and billing
emails delete their inline copies of the style block. The Resend adapter
gains a `text` part generated from the HTML.

**WhatsApp block** `contexts/communications/application/whatsapp_groups_block.py`:

```python
@dataclass(frozen=True, slots=True)
class WhatsAppGroupLink:
    label: str      # e.g. "Tue/Thu 6:00 PM · Beginner @ YWCA"
    url: str        # validated chat.whatsapp.com link
    child_name: str | None = None   # parent persona only

def render_whatsapp_groups_block(
    links: Sequence[WhatsAppGroupLink], *, persona: Literal["parent", "coach"]
) -> str: ...
```

Returns `""` when `links` is empty. Otherwise a card on `paper` background
with a WhatsApp-green (`#25d366`) left border, heading "Your class WhatsApp
groups", one row per link (label + "Join" button, secondary variant), and
the instruction line:

- parent: "Please join the group for each class above if you haven't
  already. If you're in a group for a class your child no longer attends,
  please leave it so you only get messages for your class."
- coach: "Join the group for each class you teach if you haven't already.
  Leave groups for classes you no longer coach."

Links are deduplicated by URL (two children in the same class show one row
with both names).

**Digest wiring**

- Parent digest: composition provider gathers every *active* enrollment for
  the family (not just today's), maps session → link where
  `whatsapp_group_url` is set, and passes `links` on `ParentDigestView`. The
  block renders after the child cards and before the dues block.
- Coach digest: provider gathers every active session where the coach is
  `coach_id`, same mapping, passed to `render_coach_digest`. Block renders
  after the sessions and before the playlist footer.
- Sessions with no link are silently skipped. If no session has a link the
  block is absent and the email is unchanged.

**Copy fixes shipped in the same slice** (both renderers are being edited):

- Capitalise "Your kids have practice today".
- Dues block: red only when `due_date < today`; otherwise cobalt-soft with
  "due September 10". Variant B copy switches "was due" / "is due" the same
  way. `DuesView` gains `is_overdue: bool`.
- Coach digest gets a header line with the date and academy name; the empty
  footer rule when no playlist is removed.
- All amounts use one formatter: `$60.00` (symbol from currency; fall back
  to `USD 60.00` only for currencies without a symbol map).
- Invoice heading becomes "Your September 2026 invoice", shows due date, and
  drops the "disregard" line from the shell footer for non-reminder mails.

**Mockup gate:** rendered screenshots of every changed template (phone width,
sample data) are shared with the owner before the PR is opened. The render
script from the review session (`render_previews.py` + Playwright) is
checked in under `backend/v2/tests/fixtures/email_previews/` so it can be
re-run.

### Slice 3 — enrollment confirmation email (new)

- Trigger: enrollment becomes `active` via admin roster add, checkout
  approval (`TransitionApplication` → enrolled), or waitlist promotion. Emitted
  as an `Enrollment.EnrollmentActivated` event handled in
  `composition/event_handlers.py`, same pattern as `DunningNoticeRequested`.
- Recipient: the student's parent (active membership, has email).
- Subject: `{child} is enrolled in {session title}`.
- Body: shell + greeting, class card (title, schedule in the session
  timezone, location, coach name), WhatsApp block for that one session
  (primary-variant "Join the class WhatsApp group" button), portal link.
- Category `TRANSACTIONAL`; no unsubscribe footer.
- Idempotent per `enrollment_id` via the existing idempotency store so a
  replayed event does not double-send.
- Tests: use-case test for each trigger path, renderer test, event handler
  contract test.

### Slice 4 — campaign merge tag

- `send_campaign` already renders per recipient. Add `{{whatsapp_groups}}`
  substitution: resolved through the same provider as the parent/coach digest
  according to the recipient's role in the audience. Unknown tags are left
  verbatim. Admin campaign composer shows the tag in its helper text.

### Slice 5 — portal surfaces (optional)

Parent portal enrollment card and coach session page show a "Join WhatsApp
group" link from `whatsapp_group_url`. Not required for the email goal.

## Data model change

```
sessions.whatsapp_group_url : string | null   (new, optional)
```

No migration. No index.

## Error handling

- Invalid URL on save → 422 with field-level message; the rest of the session
  save is rejected (no partial write).
- Provider failure while gathering links for a digest → log at warning, send
  the digest without the block. The block is never allowed to fail a digest.
- Plain-text generation failure → send HTML only, log at warning.

## Style findings (from the 2026-09-02 render review)

| # | Email | Finding | Fixed in |
|---|---|---|---|
| 1 | Parent digest | "Good morning! your kids…" lowercase | slice 2 |
| 2 | Parent digest A/B | Upcoming dues shown red / "was due" for a future date | slice 2 |
| 3 | All | `$60.00` vs `USD 120.00` | slice 2 |
| 4 | All | HTML only, no text part | slice 2 |
| 5 | All | Three palettes, three widths, four copies of the style block | slice 2 |
| 6 | Digests | No academy name, logo, or date in body | slice 2 |
| 7 | Coach digest | No greeting/date; double empty rule | slice 2 |
| 8 | Invoice | Generic heading, no due date, "disregard" footer on a fresh invoice | slice 2 |
| 9 | Footer | Unsubscribe link colour differs from body links | slice 2 |

## Open items

- Manrope in email: most clients will fall back to system sans. Accept.
- Academy `brand_color` is free text today; slice 2 validates it as a hex
  colour before using it in the shell, otherwise falls back to cobalt.
