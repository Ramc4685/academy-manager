# App-sent SMS and WhatsApp: design note (roadmap L12)

Status: **design only, no code.** Written 2026-09-24.

Owner decision (2026-09-20, recorded in `docs/design/people-crm/shape-brief.md`
§7 and `engineering-spec.md` §8 item 6): **handoff-and-log first.** Staff tap
WhatsApp or SMS, their own phone opens with the text pre-filled (`wa.me` and
`sms:` links), and the app asks "Did you send it?" to log it in
`family_contact_log`. The app itself sending SMS or WhatsApp is a **later
phase**. Until that phase ships, the compose sheet shows "Send from the app
(coming)" as a disabled channel with a one-line explanation, never as working.

This note is the plan for that later phase, so that when the owner says go the
build is a sequence of small PRs rather than a redesign. Nothing here changes
behaviour today.

## 1. What exists today (read before building)

| Piece | Where | What it does |
|---|---|---|
| `wa.me` link builder | `backend/v2/shared/comms/whatsapp.py` (`normalize_wa_number`) | Pure. Turns a free-text phone into bare international digits or refuses when ambiguous (trunk `0`, too short). Reuse it for E.164 normalisation; do not write a second normaliser. |
| Contact links (frontend) | `frontend/lib/contact-links.ts`, `frontend/components/ds/contact-links.tsx` | `tel:`, `mailto:`, `wa.me` hrefs; renders nothing for a missing value. |
| WhatsApp dues reminder links | Collections tab (`frontend/app/(admin)/admin/payments/buckets/CollectionsTab.tsx`) | Backend builds a per-family `wa.me` URL; the admin presses send in WhatsApp. |
| Class WhatsApp groups | `backend/v2/contexts/communications/application/whatsapp_groups_block.py` | Invite links to `chat.whatsapp.com` groups inside emails. Not a send channel. |
| Handoff-and-log store | `family_contact_log` (People CRM spec §5, Messages tab, L4c) | `{log_id, academy_id, parent_id or contact_id, channel, direction, body?, author_id, logged_at, sent_confirmed}`. Channel `whatsapp`, `sms`, `call`, `in_person`. |
| Email send seam | `communications/application/send_gate.py`, `infrastructure/gated_send_port.py` | Every email goes through one gated port; each `RecipientGate` (preferences #555, suppressions #556) is consulted once per recipient and must not raise. |
| Email categories | `communications/domain/email_category.py` | `TRANSACTIONAL`, `DIGEST`, `CAMPAIGN`, `NOTIFICATION`; only the last three are unsubscribable. |
| Email preferences | `email_preferences` (`domain/email_preferences.py`) | Absence of a row means opted in. Records decisions with `source` and `opted_out_at`. |
| Suppressions | `email_suppressions` (`infrastructure/mongo_suppression_repo.py`) | Provider-observed facts. Deliberately **not** tenant-scoped because the sending domain is shared. |
| Provider webhook dedup | `email_provider_events` (`infrastructure/mongo_provider_event_repo.py`) | Insert-first claim on a unique `event_id`; failed attempts are reclaimed. |
| Per-send logs | `message_deliveries`, `parent_digest_sends`, `coach_digest_sends`, `absence_notice_sends`, `enrollment_hold_notice_sends`, `win_back_notice_sends`, `invoice_contact_email_sends` (0197), `invoices.email_provider_message_id` | One row per attempted email, with provider message id and status. The CRM Messages tab reads all of these. |
| Sender identity | `backend/v2/shared/comms/sender_identity.py` (L9a) | Per-academy display name and reply-to; the From address stays platform-owned. |
| Lead consent | `crm_contacts.consent` (`crm/domain/models.py`, 0192) | `{contact_about_request, marketing, captured_at, privacy_notice_url}`. Email/phone contact about the request only; says nothing about SMS or WhatsApp specifically. |
| Family contacts | `family_contacts` (0196) | Second adults with `phone`, `phone_digits`, `gets_notices`, `gets_invoices`. |
| Preferred channel | `family_details.preferred_channel` | `email`, `phone`, `sms`, `whatsapp`. A display hint, not consent. |
| Staff tiers | `backend/v2/shared/auth/staff_tiers.py`, `crm/application/money_visibility.py` (L2a) | owner, admin, billing, front_desk. |

The phase below **extends** these; it does not replace any of them.

## 2. Provider options

Prices move and differ by country; the figures below are the shape of the cost,
not a quote. Re-check the provider pricing pages on the day the owner decides.

### SMS

**Twilio Programmable Messaging** is the default recommendation.

- Per-segment price plus carrier pass-through fees. A 160-character GSM-7
  message is one segment; any emoji or non-Latin character switches to UCS-2 and
  a segment drops to 70 characters, so templates must be written to stay GSM-7.
- **US: A2P 10DLC registration is mandatory** for application-sent SMS from a
  local number. That means a brand registration (the academy's legal business
  details, EIN) and a campaign registration (use case, sample messages, opt-in
  description), each with a one-off fee and a monthly campaign fee, and a
  review that can take days to a few weeks. Unregistered traffic is blocked or
  heavily filtered by carriers.
- Toll-free numbers need their own verification; short codes cost far more
  and take months. Neither is worth it at one to a few academies.
- Other countries have their own sender rules (alphanumeric sender ids, DLT
  registration in India, and so on). Treat each new country as its own
  onboarding task.

Alternatives (Vonage, MessageBird/Bird, Plivo, Telnyx) are cheaper per message
in some markets but add a second vendor relationship. Twilio also covers
WhatsApp (below), which is why it is the default.

### WhatsApp

Business-initiated WhatsApp needs the **WhatsApp Business Platform** (the Cloud
API). The consumer WhatsApp and WhatsApp Business apps cannot be driven by an
app; automating them breaks Meta's terms.

Two ways in:

| Option | Pros | Cons |
|---|---|---|
| **Twilio as a WhatsApp Business Solution Provider** | One vendor, one webhook format, one status callback for SMS and WhatsApp; Twilio handles the embedded signup. | Twilio's per-message fee on top of Meta's. |
| **Meta Cloud API directly** | No middleman fee; newest features first. | A second integration and webhook format; the platform must manage Meta Business verification, system-user tokens and app review itself. |

Either way:

- Each academy needs a **Meta Business Portfolio** (ideally verified) and a
  **WhatsApp Business Account** with its own phone number. A number already
  registered in the WhatsApp app must be migrated off it, so the academy's
  current WhatsApp number usually cannot be reused without losing that app's
  chat history. This is often the single biggest objection; raise it early.
- The display name is reviewed by Meta against the business name.
- Meta prices **per delivered template message**, by template category
  (marketing, utility, authentication) and by the recipient's country code.
  Free-form (non-template) replies are allowed only inside the 24-hour customer
  service window after the parent last messaged the business, and are not
  charged per message. Utility templates sent inside an open window are also
  free under current pricing.
- New numbers start with a daily cap on business-initiated conversations that
  rises with quality rating and volume; a quality drop (blocks, reports) can
  lower it or pause templates.

**Recommendation:** Twilio for both channels in the first build, behind a
`MessagingSendPort` so Meta direct can replace the WhatsApp half later without
touching use cases.

## 3. Consent: capture and storage

Rule: **no app-sent SMS or WhatsApp without a recorded, channel-specific,
un-revoked consent for that phone number.** Email consent, `preferred_channel`
and `crm_contacts.consent.contact_about_request` do not count. The handoff flow
needs no consent record because a human sends from their own phone; that is
the whole reason it ships first.

What is recorded, per phone number per channel per academy:

- `channel`: `sms` or `whatsapp`
- `scope`: `transactional` (invoices, dues, absence and hold notices, class
  changes) or `marketing` (campaigns, win-back, open-class promotions).
  Marketing implies transactional; transactional never implies marketing.
- `status`: `opted_in` or `opted_out`
- `captured_at` (UTC), `source`, `captured_by` (staff user id when staff
  recorded it, else null), `wording_version` (which exact consent text was
  shown), `evidence` (form id, message id of an inbound `START`, or the staff
  note for a verbal opt-in).

Sources, in order of preference:

1. **Parent portal** toggle (the parent ticks it, the parent is logged in).
2. **Registration and public trial-request forms**: an unticked checkbox per
   channel with the approved wording and a link to the privacy notice. The
   public tenant page (`crm_contacts`) gets the same fields so a lead can opt
   in before an account exists.
3. **Inbound keyword** (`START`, `UNSTOP`, or a WhatsApp reply to an opt-in
   prompt).
4. **Staff-recorded** consent (the parent said yes at the desk). Allowed, but
   shows the staff member and is flagged as weaker evidence. Owner decision
   below on whether to allow it at all for marketing.

Consent belongs to the **phone number**, not the family: a family with two
adults has two numbers and two decisions (`family_contacts` rows carry their own).

## 4. Opt-out

- **SMS keywords.** Twilio's default opt-out handling (`STOP`, `STOPALL`,
  `UNSUBSCRIBE`, `CANCEL`, `END`, `QUIT`; `START`/`UNSTOP` to resume; `HELP`) is
  on at the messaging-service level and blocks further sends at Twilio. The app
  must **also** record the opt-out from the inbound webhook, so the UI shows it
  and the send gate refuses before calling the provider (a blocked send still
  costs an API error and hides the reason from staff).
- **WhatsApp.** There is no carrier keyword layer. The app treats an inbound
  `STOP` (and a small list of equivalents in the academy's language) as an
  opt-out, and every marketing template carries a quick-reply "Stop messages"
  button that does the same. A user block reported by Meta is recorded as an
  opt-out for that number.
- **Portal and staff.** Parents can switch either channel off in the portal;
  staff can record an opt-out on the family page (never an opt-in on the
  parent's behalf without the evidence above).
- An opt-out is **per channel**: `STOP` on SMS does not stop WhatsApp, and the
  UI says so. A transactional-scope opt-out stops everything on that channel
  (unlike email, where transactional cannot be opted out of, because email is
  the fallback that must always work).
- Opt-outs are never deleted, only superseded by a later opt-in with evidence.

## 5. WhatsApp template approval

- Every business-initiated WhatsApp message is a **pre-approved template** with
  numbered variables. Templates are submitted per WhatsApp Business Account, so
  per academy; approval is usually minutes to a day, and Meta can re-categorise
  a "utility" template as "marketing" (which changes the price).
- The platform ships a **fixed starter set** mirroring existing email notices,
  written in plain language with no money amounts beyond what the email already
  shows: invoice ready, payment due reminder, payment received, absence notice
  received, class cancelled or moved, hold started or ended, trial booked,
  welcome. Marketing templates (win-back, new class open) are a separate,
  opt-in set.
- A `messaging_templates` row tracks each template's provider name, language,
  category, variables, and approval status (`pending`, `approved`, `rejected`,
  `paused`). A send whose template is not `approved` fails fast with a clear
  reason; it never falls back to free text.
- Free-form WhatsApp from the Messages compose is allowed only while the
  24-hour customer service window is open (the app tracks the last inbound
  message time per number). Outside the window the compose sheet offers only
  approved templates, or the existing handoff.
- SMS has no approval step, but reuses the same template registry so the copy
  is reviewed once and the 10DLC sample messages match what is actually sent.

## 6. Quiet hours

- Per-academy quiet hours in the **academy's timezone** (the same zone
  sessions use), default 20:00 to 08:00, editable by the owner.
- Marketing messages are never sent in quiet hours; they are queued to the
  next allowed minute. Transactional messages triggered by a person's own
  action (payment received, trial booked) go immediately; scheduled
  transactional sends (reminders, digests) are held like marketing.
- Class-cancelled notices for a session starting within the next few hours may
  bypass quiet hours; that is an owner decision below.
- Quiet hours are evaluated at send time by the worker, not at queue time, so a
  retry cannot land at 03:00.

## 7. Delivery status webhooks

- One inbound endpoint per provider (`POST /api/v2/webhooks/twilio/messaging`,
  and `/webhooks/meta/whatsapp` if Meta direct is chosen). No path parameter
  and not an admin, coach or parent route, so the two-tenant isolation test
  (`backend/v2/tests/contract/test_two_tenant_isolation.py`) does not
  enumerate it; any new family-scoped admin route that does take a path
  parameter (for example a consent endpoint under `/admin/families/{id}`) must
  be seeded in `_ids()` or `UNSEEDED_PARAMS`.
- Signature verification first (Twilio `X-Twilio-Signature`, Meta
  `X-Hub-Signature-256`), then an insert-first dedup claim modelled on
  `email_provider_events`: a new `messaging_provider_events` collection with a
  unique `event_id` (Twilio `MessageSid` + status, or Meta's status id), the
  same "reclaim a failed attempt" rule, and a 200 on duplicates.
- Status mapping onto the send row: `queued` -> `sending` -> `sent` ->
  `delivered` or `failed` / `undelivered` (with the provider error code);
  WhatsApp adds `read`. Statuses can arrive out of order; the update only moves
  forward (`delivered` never goes back to `sent`).
- The webhook carries no tenant. It finds the send row by provider message id
  (globally unique) and scopes the write with that row's `academy_id`, the same
  way the Resend webhook finds suppressions.
- Inbound messages (replies, `STOP`, `START`) hit the same endpoint, update the
  consent and service-window state, and appear in the family's Messages thread
  as an inbound row. Unknown numbers are stored against no family and shown in
  an "unmatched replies" list; they never create a lead automatically.
- Error codes that mean the number is dead (Twilio 21211, 21614, and the
  WhatsApp "not a WhatsApp user" error) write a **messaging suppression** for
  that number and channel, so the gate stops retrying.

## 8. Per-academy sender

- **SMS:** one Twilio Messaging Service per academy (holds that academy's
  numbers, opt-out settings and 10DLC campaign). The platform owns the Twilio
  account; each academy is a subaccount or a messaging service inside it. The
  academy's name is in the message body ("CourtMastr for <academy display
  name>: ..."), because an SMS has no display name.
- **WhatsApp:** one WhatsApp Business Account and phone number per academy,
  onboarded by the owner through embedded signup. The display name is the
  academy's, reviewed by Meta.
- Stored in a new `messaging_senders` document per academy (below), set by the
  owner in Settings, and read at send time the way `resolve_sender` reads
  `email_sender_name`. **Credentials are never stored in Mongo**: the platform's
  Twilio auth token (or Meta system-user token) lives in Fly secrets; per
  academy rows hold only ids (messaging service SID, phone number id, WABA id).
- An academy with no configured sender simply does not see the app-sent option;
  handoff-and-log keeps working.

## 9. Data model sketch

All tenant-scoped (`TenantScopedRepository`; `academy_id` stamped from the
tenant context, never caller input), every unique index leads with
`academy_id`, partial filters use `{"$gt": ""}`, no `$or` across
partial-indexed fields. Migration ids are assigned at build time (next free
after the highest on `origin/main`).

### `messaging_consents` (new)

`{consent_id, academy_id, phone_e164, channel, scope, status, captured_at,
source, captured_by?, wording_version, evidence?, parent_id?, contact_id?,
crm_contact_id?, superseded_at?}`

- Current state is the latest row per `(academy_id, phone_e164, channel)`;
  rows are append-only so the history is the audit trail.
- Index `(academy_id, phone_e164, channel, captured_at desc)` for the gate's
  one-read lookup.
- Index `(academy_id, parent_id, captured_at desc)` partial
  `{"parent_id": {"$gt": ""}}` for the family page.

### `messaging_suppressions` (new)

`{suppression_id, academy_id, phone_e164, channel, reason, provider_error_code?,
first_seen_at, last_seen_at}`. Unique `(academy_id, phone_e164, channel)`.

Unlike `email_suppressions` this **is** tenant-scoped: SMS and WhatsApp
senders are per academy, so one academy's dead-number signal is about that
academy's sender. (If the platform ever shares one sender across academies,
revisit this exactly as #556 did for email.)

### `messaging_senders` (new)

One document per academy: `{academy_id, sms_messaging_service_sid?,
sms_numbers[], sms_10dlc_status?, whatsapp_waba_id?, whatsapp_phone_number_id?,
whatsapp_display_name?, whatsapp_quality_rating?, quiet_hours_start,
quiet_hours_end, updated_by, updated_at}`. Unique `(academy_id)`.

### `messaging_templates` (new)

`{template_id, academy_id, key, channel, language, category, body,
variables[], provider_template_name?, approval_status, rejected_reason?,
updated_at}`. Unique `(academy_id, channel, key, language)`.

### `message_sends` (new): the per-message send log

`{send_id, academy_id, channel, direction, parent_id?, contact_id?,
crm_contact_id?, phone_e164, template_key?, body_rendered, category,
source_kind, source_ref, status, provider, provider_message_id?,
error_code?, queued_at, sent_at?, delivered_at?, read_at?, failed_at?,
attempts, author_id?}`

- `source_kind` + `source_ref` name what caused it (`invoice`/`invoice_id`,
  `absence_notice`/`notice_id`, `campaign`/`campaign_id`, `manual`/`log_id`).
- Unique `(academy_id, source_kind, source_ref, channel, phone_e164)` partial
  `{"source_ref": {"$gt": ""}}`: the same notice is never sent twice to the
  same number on the same channel, the same insert-first idempotency every
  existing `*_sends` collection uses.
- Unique `(academy_id, send_id)`.
- Index `(academy_id, parent_id, queued_at desc)` for the Messages thread.
- Lookup `(provider_message_id)` partial `{"provider_message_id": {"$gt": ""}}`
  for the webhook. This is the one index that does not lead with `academy_id`,
  because the webhook has no tenant; it is **not** unique across academies in
  the index (uniqueness is guaranteed by the provider), so it cannot trip the
  global-unique-index trap from #849.

### `messaging_provider_events` (new)

Same shape and rules as `email_provider_events`: not tenant-scoped, unique
`event_id`, insert-first claim, reclaim on failure.

### What it extends rather than duplicates

- **`family_contact_log`** stays the store for handoff sends, calls and in-person
  talks. When app-sent ships, the handoff row and the app-sent row are
  different stores with different truths ("staff says they sent it" versus
  "the provider says it was delivered"), and the Messages tab merges both,
  labelled differently. An app-sent message never writes `family_contact_log`.
- **The CRM Messages / timeline aggregation** (L4a/L4c) gains `message_sends`
  as one more source next to `message_deliveries`, the notice `*_sends`
  collections and `invoices.email_provider_message_id`.
- **`message_campaigns`** gains a `channels` list (`email` default, plus `sms`
  and `whatsapp`); `SendCampaign` fans out per channel. The audience resolver
  is reused unchanged; the per-channel consent gate drops recipients without
  consent, and the campaign summary shows "skipped: no SMS consent" counts.
- **The notice senders** (absence, hold, win-back, invoice, dues reminder)
  each gain an optional channel list read from the academy's settings; email
  stays the default and always-on fallback.
- **`RecipientGate`**: a parallel `MessagingGate` protocol, applied in one
  gated send port exactly like email, with one deliberate difference: the
  email gate fails open, but for SMS and WhatsApp a gate that cannot read
  consent must **refuse** (fail closed),
  because sending without consent is a legal exposure while not sending only
  loses a nudge that email already carries.
- **`crm_contacts.consent`** gains optional `sms` and `whatsapp` booleans with
  `wording_version`, written into `messaging_consents` by the conversion flow.

## 10. Roles

- **Send a one-off message from the app** (Messages compose): owner, admin,
  front desk. Front desk templates never include amounts (front desk sees an
  "owes money" flag only). Billing may send billing templates.
- **Campaigns over SMS or WhatsApp**: owner and admin only.
- **Configure senders, quiet hours, templates, budget cap**: owner only.
- **Record or clear consent**: owner and admin; front desk may record an
  opt-out but not an opt-in.
- Coaches: no messaging access (unchanged).

## 11. Cost controls

- Per-academy monthly cap (messages or currency) in `messaging_senders`; the
  worker stops sending non-transactional messages at the cap and posts an ops
  alert. Transactional continues up to a hard ceiling.
- The campaign preview shows the recipient count per channel and an estimated
  cost before the owner confirms.
- Who pays is an owner decision (platform absorbs, passes through at cost, or
  bundles into the flat monthly fee).

## 12. Build order when the owner says go

1. Consent capture only: `messaging_consents`, portal toggles, registration and
   trial-form checkboxes, staff opt-out. No sending. (Consent collected early
   is consent that exists on launch day.)
2. Sender settings and Twilio SMS for **transactional** notices behind the
   `MessagingGate`, `message_sends`, the status webhook and inbound `STOP`.
   Feature-flagged per academy.
3. Messages compose "Send from the app" for SMS (enables the disabled option).
4. WhatsApp: sender onboarding, template registry and approval sync,
   service-window tracking.
5. SMS and WhatsApp campaigns (marketing scope), quiet-hours queue, cost cap.

Each step is its own PR with its own migration; each is reversible by switching
the academy's flag off, which falls back to handoff-and-log.

## 13. Open owner decisions

1. **Provider**: Twilio for both (recommended), or Twilio SMS plus Meta Cloud
   API for WhatsApp.
2. **Budget and who pays**: monthly cap per academy, and whether message costs
   are absorbed, passed through, or priced into the plan.
3. **Consent wording**: the exact checkbox text for SMS and WhatsApp,
   transactional and marketing, and the privacy-notice link. Needs a legal read
   for each country the academy operates in.
4. **Staff-recorded opt-in**: allowed for transactional only, for both, or not
   at all.
5. **WhatsApp number**: a new number per academy (keeps the academy's current
   WhatsApp app and chats) or migrating the existing one.
6. **Quiet hours** default and whether class-cancelled notices may bypass them.
7. **First channel**: SMS first (simpler onboarding, 10DLC wait), WhatsApp
   first (what families already use), or both together.
8. **10DLC brand owner**: registered under each academy's legal entity
   (recommended; the academy is the sender) or under the platform.

## 14. Out of scope

Two-way chat inbox beyond logging replies into the family thread; chatbots or
automatic replies other than `HELP`; voice calls; MMS and media messages;
WhatsApp group management by API (groups stay invite links); any change to
handoff-and-log.
