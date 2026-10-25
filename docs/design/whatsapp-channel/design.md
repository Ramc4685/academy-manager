# WhatsApp Notification Channel — Design

**Status:** Proposed (design only, no code yet)
**Date:** 2026-10-23 (provider switched to OpenWA 2026-10-25)
**Owner:** RamC
**Touches:** `backend/v2/contexts/communications`, `backend/v2/contexts/identity` (phone), `backend/v2/composition/*_notifications.py`, a new webhook route, a new self-hosted OpenWA service
**Review gates:** `security-reviewer` subagent (webhooks, secrets, PII, tenant isolation), `boundary-reviewer` (new port + composition wiring)

## 1. Summary

Add WhatsApp as a **second, opt-in delivery channel** for a small set of parent
notifications (dues reminders, schedule changes, absences). Email stays the
system of record and always sends. WhatsApp is sent **in addition**, and only to parents who
have explicitly opted in with a valid number.

Messages go through **[OpenWA](https://github.com/rmyndharis/OpenWA)**, a
self-hosted, MIT-licensed WhatsApp gateway that we run ourselves. It sits behind
a new `WhatsAppSendPort` that mirrors `EmailSendPort`: one construction site,
the same send-time gate pattern, and a stub in local and CI.

OpenWA connects through **unofficial, reverse-engineered WhatsApp clients**.
The number it uses can be restricted or banned by WhatsApp at any time, and
some messages may silently not arrive. The whole design is built so that this
outcome is survivable: WhatsApp is never the only copy of a message, and the
provider can be swapped for the official Cloud API by changing one adapter
(§4.3).

## 2. Context: what exists today

- All outbound parent messaging is email via Resend, behind `EmailSendPort`
  (`communications/application/ports.py`).
- `GatedEmailSendPort` (`communications/infrastructure/gated_send_port.py`) is
  **the** seam where suppressions (#556) and unsubscribe preferences (#555) are
  applied, so no send loop can forget a check.
- `_build_email_sender` in `composition/digests.py` is the single construction
  site for a real sender. It enforces "real provider only in staging/prod with the
  delivery flag and key set", and `tests/structural/test_email_sender_construction.py`
  pins that.
- `EmailCategory` (`TRANSACTIONAL` / `DIGEST` / `CAMPAIGN` / `NOTIFICATION`)
  is the axis every gate reasons over. `TRANSACTIONAL` can never be
  unsubscribed.
- Provider webhooks (`ingest_email_provider_event.py`) follow a fixed order:
  verify the signature first, claim the event id insert-first (the duplicate key is
  the idempotency guard), then classify and apply. Unknown events are stored and
  get a 200, never a 500.
- Parent phone lives on the identity `User` as `phone: str | None`. It is free-form,
  admin-editable and capped at 40 characters (`identity/application/use_cases/admin_directory.py`).
  It is **not normalized** and **not verified**.
- WhatsApp appears today only as **group-invite links** rendered into emails
  (`whatsapp_groups_block.py`). This design does not change that.
- There is no per-academy country or timezone setting. Schedulers run on
  `settings.scheduler_tz`.
- `Delivery` rows (`domain/models.py`) are campaign-scoped and email-shaped
  (`recipient_email`). Event notifications (absence, hold, roster) call
  `EmailSendPort` directly and don't write `Delivery` rows.

## 3. Goals and non-goals

**Goals (v1)**

1. Parents who opt in get a WhatsApp message for:
   - dues reminder / dunning notice (`TRANSACTIONAL`)
   - session cancelled or rescheduled (`TRANSACTIONAL`)
   - confirmation of an absence the parent reported (`TRANSACTIONAL`, see
     `composition/absence_notifications.py`, #616). academy-manager has no
     "child marked absent by the coach" notice today.
2. Opting in, opting out, `STOP` and number changes are all recorded and auditable.
3. No real WhatsApp sends from local or CI, enforced structurally like email.
4. Per-message delivery status (sent / delivered / read / failed) is recorded.
5. A banned or disconnected WhatsApp number is **detected and surfaced**, not
   silently ignored.

**Non-goals (v1)**

- Campaigns or bulk broadcasts. Bulk messaging to many contacts is the
  behaviour most likely to get the number restricted.
- Digests over WhatsApp. They are too long, and email handles them well.
- Two-way chat or a support inbox. Inbound messages are handled only for
  `STOP`/`START`.
- Replacing class WhatsApp groups.
- WhatsApp as the *only* channel for anything. This matters more with an
  unofficial gateway than it would with the official API.

## 4. Provider: OpenWA

### 4.1 What it is

OpenWA is a NestJS service with a REST API, a web dashboard, webhooks and
multi-session support (several WhatsApp numbers on one instance). It is
self-hosted in Docker from the published `ghcr.io/rmyndharis/openwa` image. We
pin an exact version (0.25.0 at time of writing), never `latest`.

A WhatsApp number is linked to OpenWA by scanning a QR code in the dashboard,
the same way WhatsApp Web is linked. After that, academy-manager talks to OpenWA
over HTTP:

| Need | OpenWA API |
| --- | --- |
| Send a message | `POST /api/sessions/{sessionId}/messages/send-text` with `{"chatId": "<digits>@c.us", "text": "..."}` |
| Check a number is on WhatsApp | `GET /api/sessions/{sessionId}/contacts/check/{number}` |
| Session health | `session.status` / `session.disconnected` / `session.restriction` webhook events |
| Delivery status | `message.sent` / `message.ack` / `message.failed` webhook events |
| Inbound replies | `message.received` webhook event |
| Auth | `X-API-Key` header, a key scoped to the one session it may use |

### 4.2 Engine choice

OpenWA offers two engines:
- **`whatsapp-web.js`** drives a real headless Chromium. It looks like genuine
  WhatsApp Web, so it has the **lower ban risk**, but costs about 300–500 MB of RAM per session.
- **`baileys`** speaks the protocol directly. It uses about 30–80 MB, but is easier for
  WhatsApp to fingerprint.

**Use `whatsapp-web.js`.** We run very few sessions, so memory is cheap
compared with losing the number.

### 4.3 Risks we accept, and the guardrails for each

| Risk | Guardrail in this design |
| --- | --- |
| The number gets restricted or banned | Dedicated number only, never an academy's main or personal number (§4.4). Email always sends (§5). `session.restriction`/`session.disconnected` alerts the platform admin (§9). |
| The first message to a new contact silently doesn't arrive (WhatsApp server-side policy; OpenWA reports success anyway) | Opt-in flow asks the parent to message the number first (§7). WhatsApp is never relied on as the only copy. |
| Bulk sending gets flagged | No campaigns in v1. OpenWA send pacing is **on** (§4.5). Dues reminders spread over time, not one burst. |
| A WhatsApp protocol change breaks OpenWA until upstream patches it | Pinned version, upgraded deliberately. Session health alerts. Email fallback. |
| The gateway itself is a new attack surface (an API key that can message parents) | Private network only, session-scoped API key, CIDR allowlist, secrets in Fly (§10). |
| Compliance: OpenWA's maintainers advise against it where regulatory compliance matters | Narrow v1 scope (operational notices to opted-in parents), explicit consent records, documented here. Revisit before expanding to marketing or to regulated academies. |

**Exit path.** Because everything goes through `WhatsAppSendPort`, moving to
Meta's official Cloud API later means writing a new adapter, registering
message templates with Meta, and changing the webhook mapping. Consent, phone
normalization, gates, `ParentNotifier` and the data model stay. Keep message
text short and template-like now (§6) so that move is cheap.

### 4.4 Sender identity

- **Phase 1:** one **platform-owned dedicated number** on one OpenWA session.
  Message text starts with the academy name ("Smash Academy: …").
- **Phase 2 (optional):** a dedicated number per academy, one OpenWA session each.
  OpenWA supports multiple sessions on one instance. Each academy needs an
  `openwa_session_id` → `academy_id` mapping for webhook tenant resolution.
  Design the webhook (§9) to resolve the tenant by session id from day one, so
  phase 2 needs no rework. Academies must use a spare number, never their main
  business line.

**Warm-up.** A fresh number is used like a normal phone for several days before
automation: profile photo, a few real conversations. Then volume ramps slowly,
which OpenWA's pacing enforces (§4.5).

### 4.5 OpenWA configuration we rely on

| Setting | Value | Why |
| --- | --- | --- |
| Engine | `whatsapp-web.js` | Lower ban risk (§4.2) |
| `SEND_PACING_ENABLED` | `true` (default is off) | Per-session daily cap that grows with the session's age |
| `SEND_PACING_WARMUP_SCHEDULE` | OpenWA's default ramp, reviewed before go-live | Limits sends while the number is new |
| `SEND_PACING_COLD_DAILY_CAP` | Conservative | Caps first-ever messages to new contacts, the riskiest kind |
| `SEND_PACING_BREAKER_*` | Defaults | Stops sending after repeated failures |
| `API_KEY_PEPPER` | Set before first boot | Otherwise stored API-key hashes are plain SHA-256 |
| Swagger / MCP | Off in production | Smaller surface |
| Database | Postgres or SQLite on a persistent volume | The linked-device auth state must survive restarts, or the number must be re-paired |

### 4.6 Hosting

OpenWA runs as its **own Fly app** (e.g. `courtmastr-whatsapp`) in the same
region as the API, with a persistent volume and **no public HTTP exposure**.
The backend reaches it over Fly's private network (`*.internal`). OpenWA posts
webhooks back to the backend's webhook route over the same private network.

The dashboard is reached only through `flyctl proxy` by a platform admin, for
QR re-pairing. Budget about 1 GB of RAM for one `whatsapp-web.js` session plus
the service.

The default compose file also starts a Docker-socket proxy container for
OpenWA's infra features. We don't need those features, and on Fly there is
no Docker socket, so we don't deploy it.

## 5. Send port

Unlike the official API, OpenWA sends **free text**, so there is no template
approval step. The port still takes a **message key plus parameters**, not raw
text. This keeps wording reviewed in code, testable, and ready for templates
if we ever move to the official API.

```python
# communications/application/ports.py (new)

@dataclass(frozen=True, slots=True)
class WhatsAppRecipient:
    user_id: str
    academy_id: str
    phone_e164: str            # always normalized, see §8

class WhatsAppSendPort(Protocol):
    async def send_message(
        self,
        *,
        recipient: WhatsAppRecipient,
        message: WhatsAppMessage,           # see §6
        params: Mapping[str, str],
        category: EmailCategory = EmailCategory.TRANSACTIONAL,
    ) -> SendOutcome: ...
```

- **Reuse `SendOutcome`** unchanged, including `suppressed=True` for gate
  refusals (terminal, never retried). A pacing refusal from OpenWA maps to
  `ok=False` with a `failed_reason` of `rate_limited`, and is not retried that day.
- **Reuse `EmailCategory`** as the category axis. Renaming it to
  `MessageCategory` is tempting, but it's a wide rename for no behaviour change.
  Note the debt and do it separately if ever.
- **Adapters:**
  - `OpenWaWhatsAppSendPort` (infrastructure; `httpx` call to OpenWA's
    `send-text`, `chatId` built from `phone_e164` without the `+`, plus `@c.us`)
  - `StubWhatsAppSendPort` (records in memory, mirrors `StubEmailSendPort`)
  - `GatedWhatsAppSendPort` (decorator applying the consent, preference and
    suppression gates from §7, the single place gates run)
- **Single construction site:** `_build_whatsapp_sender(settings, db)` next to
  `_build_email_sender`, with the same rules: real adapter only when
  `whatsapp_delivery_enabled`, `openwa_base_url` and `openwa_api_key` are set
  **and** `env` is in the real-send set. Extend
  `test_email_sender_construction.py` (or add a sibling) so constructing
  `OpenWaWhatsAppSendPort` anywhere else fails CI.
- **Local development** uses the stub, like email. A developer who wants to see
  real messages runs OpenWA locally with a spare phone. That is a manual
  experiment outside the app's send path, never wired into local composition.

### Fan-out: where WhatsApp gets called

Don't add a WhatsApp branch inside every send loop. Add one small application
service:

```python
class ParentNotifier:
    """Email always; WhatsApp additionally when the parent is eligible."""
    email: EmailSendPort
    whatsapp: WhatsAppSendPort | None   # None when the channel is off for this academy
    eligibility: WhatsAppEligibility    # consent + normalized phone lookup, §7
```

v1 wires `ParentNotifier` into three call sites only:

- **Dues and dunning.** `process_dunning_retries.py` sends through billing's own
  notifier port (`send_dunning_notice`). Hook WhatsApp into that port's
  composition-side implementation, not into the billing use case.
- **Urgent session announcements** ("class cancelled tonight") in
  `composition/session_announcements.py`.
- **Parent absence-notice confirmations** in `composition/absence_notifications.py`.

**Pilot order (see [prd.md](prd.md)):** the first slice posts urgent session
announcements into the class **WhatsApp group** (one message per class, no
per-parent consent needed), before any of the per-parent sends above.

The email path and its gates stay exactly as they are. **A WhatsApp failure
never fails or retries the email send**, and a disconnected OpenWA session must
not slow the email path down: use a short timeout on the OpenWA call.

## 6. Messages

- A code registry, e.g. `communications/domain/whatsapp_messages.py`:
  `WhatsAppMessage(key="dues_reminder", text="{academy}: payment of {amount} for {child} is due {due_date}. Pay at {link}. Reply STOP to stop WhatsApp messages.")`.
- **The text lives in code**, reviewed like any other copy. A unit test renders every
  message with its declared parameters, so a missing parameter fails CI rather
  than producing a broken message.
- Keep messages **short, plain and template-shaped**. No marketing tone, no
  emoji walls, no link shorteners. This lowers ban risk and lets the text map
  one-to-one to official templates if we ever switch (§4.3).
- Every message ends with the opt-out line.
- Vary nothing per recipient beyond the parameters. Identical-looking bulk text
  is expected for notices like these. What gets numbers flagged is volume to
  cold contacts, which pacing and opt-in address.

## 7. Consent and eligibility

WhatsApp consent is **channel-level and explicit**. This is a deliberate
difference from email, where absence of a row means opted in.

**Rules**

1. **No consent row → no WhatsApp send, for every category including
   `TRANSACTIONAL`.** The invoice still reaches the parent by email, so nothing
   is lost.
2. Category opt-outs from `EmailPreferences` **also apply** to WhatsApp. A
   parent who turned off absence notices (`NOTIFICATION`) gets none on either
   channel. One preference model, two channels.
3. Consent is bound to the **number**. If `phone_e164` changes, consent lapses
   and the parent must opt in again. Otherwise a mistyped admin edit would send
   a child's absence notice to a stranger.
4. `STOP` (and common variants) received by the webhook records an opt-out
   immediately. `START` re-opts in only if a consent row for that number exists.
5. A number that OpenWA's contact check reports as not on WhatsApp, or that
   repeatedly fails, gets a suppression for that number, mirroring the email
   suppression list.

**Opt-in completes when the parent messages us first.** After ticking the
checkbox, the parent sees a "Message us on WhatsApp" button: a `wa.me` link
to the platform number with a prefilled text such as `START Smash Academy`.
The consent row becomes `opted_in` only when that inbound message arrives
through the webhook. This does three things at once:
- it proves the number is theirs and on WhatsApp;
- it makes our later messages replies to a known contact, not cold sends,
  which is the most effective protection against restriction;
- it avoids the "first message to a new contact never arrives" problem.

**Storage:** a new tenant-scoped collection `whatsapp_consents`:

| field | notes |
| --- | --- |
| `academy_id`, `user_id` | tenant scoping is mandatory on every read and write |
| `phone_e164` | the number consent was given for |
| `status` | `pending` (box ticked, awaiting their first message) / `opted_in` / `opted_out` |
| `source` | `parent_portal` / `admin_on_behalf` / `inbound_stop` / `inbound_start` |
| `consent_text_version` | which wording the parent agreed to |
| `requested_at`, `opted_in_at`, `opted_out_at`, `updated_at` | audit |

Unique index on `(academy_id, user_id, phone_e164)`.

**Capture points**

- **Parent portal profile:** a checkbox with the consent text, shown only when the
  phone normalizes to a valid number, followed by the "Message us on WhatsApp"
  step. This is the primary path.
- **Admin on behalf:** allowed only with `source=admin_on_behalf` recorded, and
  it still needs the parent's first inbound message before any send. Flag this
  for product/legal review; if in doubt, drop it from v1.
- **Not** auto-granted on enrollment or from existing phone numbers.

**Gate:** `WhatsAppConsentGate` implements the same never-raise contract as
`RecipientGate`, but checked against the **number**: a store outage logs and,
unlike email, **denies**. With email still going out, failing closed costs nothing,
while failing open would message people without consent. Call this out in the
gate docstring, because it is the opposite of the email gates on purpose.

## 8. Phone normalization

- Normalize to **E.164** with the `phonenumbers` library (new backend
  dependency; do the usual health check before adding).
- **Default region:** there is no academy country today. Add
  `default_phone_region` (ISO 3166 alpha-2, default `"US"`) to academy settings.
  Numbers entered with a leading `+` ignore it.
- **Store both:** keep `phone` as entered (it is what admins see and edit) and
  add `phone_e164: str | None`, written on every phone write in
  `mongo_user_repo` (the `set_doc["phone"]` path) and backfilled by a
  migration. Invalid or unparseable numbers get `phone_e164 = None` and are
  simply not WhatsApp-eligible.
- **Surface it:** the admin student and family view shows "not a valid mobile
  number for WhatsApp" next to a phone that failed normalization, so fixing it
  is an admin task, not a silent drop.
- Use `phone_e164` for all lookups (consent, suppression, inbound `STOP`
  matching). Never match on the raw string. OpenWA's `chatId` is derived from it
  (digits only, then `@c.us`).
- **LID caveat:** WhatsApp increasingly identifies inbound senders by a privacy
  id (`…@lid`) instead of a phone number. OpenWA keeps a mapping table between the two.
  The webhook handler must resolve an inbound sender to a phone via OpenWA
  before matching consent, and treat an unresolvable `@lid` as unknown, never
  as a guessed number.

## 9. Webhook: delivery status, inbound and session health

A new route, e.g. `interfaces/whatsapp_webhook_routes.py`, modelled on
`email_webhook_routes.py` and `ingest_email_provider_event.py`. OpenWA is
configured with a webhook per session, a shared `secret`, and the events
`message.received`, `message.sent`, `message.ack`, `message.failed`,
`session.status`, `session.disconnected` and `session.restriction`.

1. **Verify `X-OpenWA-Signature`** (`sha256=<hex>`, HMAC-SHA256 of the exact raw
   body with the webhook secret, compared in constant time) **before any write**.
2. **Resolve the tenant** from the OpenWA session id. In phase 1 that is the
   platform session, and the academy comes from the stored outbound message or
   the consent row. In phase 2 the session maps directly to the academy. Never
   trust an academy id from the payload.
3. **Claim** each delivery using `X-OpenWA-Delivery-Id`, inserted first into a
   `whatsapp_provider_events` collection with a unique index. A duplicate gets a 200.
4. **Apply** by event type (`X-OpenWA-Event`):
   - `message.sent` / `message.ack` / `message.failed` → update the
     `whatsapp_messages` row; repeated failures write a suppression.
   - `message.received` → `START …` completes a pending opt-in, and `STOP` opts out.
     Anything else is ignored. No auto-reply in v1, so the number isn't chatting
     with strangers.
   - `session.disconnected` / `session.restriction` / a `session.status` other than
     ready → mark the channel **degraded**, stop handing messages to OpenWA
     (`ParentNotifier` skips WhatsApp while degraded), and alert the platform
     admin by email to re-pair or replace the number.
   - Anything unrecognised is stored as `ignored` and gets a 200.

Store outbound sends in a new `whatsapp_messages` collection
(`academy_id, user_id, phone_e164, message_key, provider_message_id, status, failed_reason, timestamps`)
rather than stretching the email-shaped, campaign-scoped `Delivery`.

## 10. Security and privacy

- **Secrets** (Fly secrets, listed in `DEPLOYMENT.md` and `.env.example` by
  name only):
  - backend: `OPENWA_BASE_URL`, `OPENWA_API_KEY`, `OPENWA_SESSION_ID`, `OPENWA_WEBHOOK_SECRET`
  - OpenWA app: `API_KEY_PEPPER`
- **OpenWA API key:** an operator key scoped to the single session
  (`allowedSessions`), not the admin key. The admin key is kept offline for
  dashboard use only.
- **Network:** OpenWA is reachable only on Fly's private network, with OpenWA's
  CIDR allowlist restricted to the backend. There is no public dashboard; access
  is through `flyctl proxy`.
- **Data held by OpenWA:** it stores chats and media for the linked number.
  Disable chat-media archiving where possible, and treat its volume as PII. It
  is in scope for backups, deletion requests and the security matrix.
- Phone numbers are PII. Mask them in logs (`+1******1234`), and never put them in
  URLs or metrics labels.
- Every repository method takes and filters by `academy_id` (ADR-0006/0007).
  The `security-reviewer` subagent reviews the webhook route, consent gate,
  tenant resolution and OpenWA network exposure before merge.
- Message content: no child's full name with attendance details beyond what the
  email already contains. Keep it to first name and session.

## 11. Rollout

1. Phone normalization + backfill + admin "invalid number" hint. This is useful on
   its own and has no WhatsApp dependency.
2. Consent model + parent portal opt-in UI (no sends yet). This measures demand:
   how many parents opt in?
3. Port, stub, gate, construction-site test, `ParentNotifier` wired to the
   stub only.
4. OpenWA on Fly (private, pinned, pacing on). Acquire and warm up the dedicated
   number for several days before any automation.
5. OpenWA adapter + webhook, behind `WHATSAPP_DELIVERY_ENABLED` **and** a
   per-academy toggle. Pilot one academy, starting with dues reminders.
6. Add schedule-change and absence messages once the pilot shows clean
   delivery status and no session restrictions.

Step 2 is the cheap go/no-go: if few parents opt in, stop there. Step 6 has a
second gate: if the number gets restricted during the pilot, stop and
reconsider the official Cloud API (§4.3) before going wider.

## 12. Testing

- Unit: E.164 normalization table (US local, `+` international, junk, too
  long), consent gate (no row / pending / opted out / number changed / store down →
  deny), message registry rendering, `chatId` building.
- Structural: the real OpenWA adapter is constructed only in
  `_build_whatsapp_sender`, and local/test always gets the stub.
- Contract: webhook signature verification (valid, tampered body, missing
  header → no state change), duplicate delivery id → 200 with no second write,
  `START` completes a pending opt-in, `STOP` → opt-out,
  `session.restriction` → channel degraded.
- Integration: `ParentNotifier` sends email even when OpenWA times out or
  returns an error.
- No test, local or CI path ever calls a real OpenWA instance. Manual
  exploration against a local OpenWA with a spare phone is fine, outside the
  app's send path.

## 13. Open questions

1. Phase 1 platform number vs per-academy numbers: is sending from a
   platform number acceptable to academies?
2. Is admin-on-behalf consent acceptable, or must consent always come from the
   parent?
3. Pacing values: what daily cap is enough for one academy's dues run once the
   number is warm? Measure during the pilot.
4. What is the trigger to move to the official Cloud API: the first restriction,
   a second academy, or a compliance requirement?
5. Quiet hours: schedulers run in `settings.scheduler_tz`, not academy-local
   time. Is that acceptable for WhatsApp, which feels more intrusive than email at 7am?
