# WhatsApp Notification Channel — Design

**Status:** Proposed (design only, no code yet)
**Date:** 2026-10-23
**Owner:** RamC
**Touches:** `backend/v2/contexts/communications`, `backend/v2/contexts/identity` (phone), `backend/v2/composition/*_notifications.py`, a new webhook route
**Review gates:** `security-reviewer` subagent (webhooks, secrets, PII, tenant isolation), `boundary-reviewer` (new port + composition wiring)

## 1. Summary

Add WhatsApp as a **second, opt-in delivery channel** for a small set of parent
notifications (dues reminders, schedule changes, absences). Email stays the
system of record and always sends. WhatsApp is sent **in addition**, and only to parents who
have explicitly opted in with a valid number.

Messages go through the **official WhatsApp Cloud API** using pre-approved
*utility* templates, behind a new `WhatsAppSendPort` that mirrors
`EmailSendPort`: one construction site, the same send-time gate pattern, and a stub
in local and CI.

Unofficial gateways (OpenWA, whatsapp-web.js, Baileys) are rejected for this
product. See §4.

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
   - child marked absent (`NOTIFICATION`)
2. Opting in, opting out, `STOP` and number changes are all recorded and auditable.
3. No real WhatsApp sends from local or CI, enforced structurally like email.
4. Per-message delivery status (sent / delivered / read / failed) is recorded.

**Non-goals (v1)**

- Campaigns or marketing broadcasts. These fall in the *marketing* template category,
  which costs more and has stricter consent rules. Revisit after v1.
- Digests over WhatsApp. They are too long, and email handles them well.
- Two-way chat or a support inbox. Inbound messages are handled only for `STOP`/`START`
  and a fixed "this number isn't monitored" reply.
- Replacing class WhatsApp groups.
- WhatsApp as the *only* channel for anything.

## 4. Provider choice

| Option | Delivery / ban risk | Cost | Ops | Fit |
| --- | --- | --- | --- | --- |
| **Meta WhatsApp Cloud API (direct)** | Official, no ban risk if policy is followed | Per-message, utility rate | Meta app + WABA setup, template approval | **Recommended** |
| BSP (Bird, Twilio, etc.) on top of Cloud API | Same as above | Cloud API rate + BSP margin | Simpler onboarding and consoles, another vendor | Acceptable alternative |
| Unofficial gateway (OpenWA / whatsapp-web.js / Baileys) | Number can be restricted or banned; first message to a new contact may silently drop | Free software, heavy hosting (headless Chrome ~300–500 MB per number) | Stateful service with QR re-linking | **Rejected** |

**Why the unofficial gateway is rejected.** Dues reminders are exactly the
traffic those clients get flagged for: business-initiated messages to many
contacts who have never chatted with the number. The gateway's own maintainers say
not to rely on it for revenue-critical flows. In a multi-tenant SaaS we would also
be asking each academy to put a business number at risk. OpenWA is fine for a
personal experiment, but it's not a product dependency.

**Direct vs BSP.** The port isolates this choice, so it is cheap to reverse.
Default to the **Cloud API directly**: one fewer vendor, and Meta's webhook and
signature scheme are well documented. Revisit if template management or
per-academy onboarding (phase 2 below) turns out painful. This deserves a short ADR
(ADR-00NN "WhatsApp via official Cloud API") once accepted, because it constrains
downstream work.

**Sender identity.**

- **Phase 1:** one **platform-owned** WhatsApp Business number. Templates
  carry the academy name as a parameter ("{{academy}}: payment of {{amount}} is
  due {{date}}").
- **Phase 2 (optional):** per-academy numbers via Meta Embedded Signup (Tech
  Provider). Each academy then needs a `phone_number_id` → `academy_id` mapping
  for webhook tenant resolution. Design the webhook (§9) to resolve the tenant by
  `phone_number_id` from day one, so phase 2 needs no rework.

## 5. Send port

WhatsApp business-initiated messages **must be templates** (free-form text only
works inside the 24 h customer-service window). The port therefore takes a
template reference and parameters, not a `subject` and `body`.

```python
# communications/application/ports.py (new)

@dataclass(frozen=True, slots=True)
class WhatsAppRecipient:
    user_id: str
    academy_id: str
    phone_e164: str            # always normalized, see §8

class WhatsAppSendPort(Protocol):
    async def send_template(
        self,
        *,
        recipient: WhatsAppRecipient,
        template: WhatsAppTemplate,          # see §6
        params: Mapping[str, str],
        category: EmailCategory = EmailCategory.TRANSACTIONAL,
    ) -> SendOutcome: ...
```

- **Reuse `SendOutcome`** unchanged, including `suppressed=True` for gate
  refusals (terminal, never retried).
- **Reuse `EmailCategory`** as the category axis. Renaming it to
  `MessageCategory` is tempting, but it's a wide rename for no behaviour change.
  Note the debt and do it separately if ever.
- **Adapters:**
  - `CloudApiWhatsAppSendPort` (infrastructure; httpx call to Meta Graph API)
  - `StubWhatsAppSendPort` (records in memory, mirrors `StubEmailSendPort`)
  - `GatedWhatsAppSendPort` (decorator applying the consent, preference and suppression gates from §7, the
    single place gates run)
- **Single construction site:** `_build_whatsapp_sender(settings, db)` next to
  `_build_email_sender`, with the same rules: real adapter only when
  `whatsapp_delivery_enabled` and credentials are set **and** `env` is in the
  real-send set. Extend `test_email_sender_construction.py` (or add a sibling)
  so constructing `CloudApiWhatsAppSendPort` anywhere else fails CI.

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
- **Absences** in `composition/absence_notifications.py`. The email path and its gates stay
exactly as they are. **A WhatsApp failure never fails or retries the email send.**

## 6. Templates

- A code registry, e.g. `communications/domain/whatsapp_templates.py`:
  `WhatsAppTemplate(name, language, meta_category="utility", params=("academy", "amount", "due_date"))`.
- Template **text lives in Meta** (approved out of band). The registry pins
  name, language and parameter order, so a param mismatch fails a unit test rather than
  failing at Meta.
- Version by name suffix (`dues_reminder_v2`). Never edit an approved template
  in place, because approval resets and sends fail during review.
- Every template ends with an opt-out line ("Reply STOP to stop WhatsApp
  messages").

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
5. A hard failure from Meta that means "not a WhatsApp user / undeliverable"
   writes a suppression for that number, mirroring the email suppression list.

**Storage:** a new tenant-scoped collection `whatsapp_consents`:

| field | notes |
| --- | --- |
| `academy_id`, `user_id` | tenant scoping is mandatory on every read and write |
| `phone_e164` | the number consent was given for |
| `status` | `opted_in` / `opted_out` |
| `source` | `parent_portal` / `admin_on_behalf` / `inbound_stop` / `inbound_start` |
| `consent_text_version` | which wording the parent agreed to |
| `opted_in_at`, `opted_out_at`, `updated_at` | audit |

Unique index on `(academy_id, user_id, phone_e164)`.

**Capture points**

- **Parent portal profile:** a checkbox with the consent text, shown only when the
  phone normalizes to a valid number. This is the primary path.
- **Admin on behalf:** allowed only with `source=admin_on_behalf` recorded, for
  academies that collect consent on paper. Flag this for product/legal review;
  if in doubt, drop it from v1.
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
  matching). Never match on the raw string.

## 9. Webhook: delivery status and inbound

A new route, e.g. `interfaces/whatsapp_webhook_routes.py`, modelled on
`email_webhook_routes.py` and `ingest_email_provider_event.py`:

1. `GET` verification handshake (`hub.verify_token`).
2. `POST`: **verify `X-Hub-Signature-256`** (HMAC-SHA256 of the raw body with
   the app secret) **before any write**.
3. **Resolve the tenant** from `metadata.phone_number_id`. In phase 1 it maps to the
   platform number, and the academy comes from the stored outbound message. In
   phase 2 it maps directly to the academy. Never trust an academy id from the payload.
4. **Claim** each status or message id insert-first in a
   `whatsapp_provider_events` collection (unique index). A duplicate gets a 200.
5. **Apply:** status updates write `whatsapp_messages` rows (sent / delivered /
   read / failed + Meta error code). Permanent-failure codes write a suppression.
   An inbound `STOP`/`START` updates consent. Anything unrecognised is stored as `ignored`
   and gets a 200.

Store outbound sends in a new `whatsapp_messages` collection
(`academy_id, user_id, phone_e164, template, provider_message_id, status, error_code, timestamps`)
rather than stretching the email-shaped, campaign-scoped `Delivery`.

## 10. Security and privacy

- Secrets: `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_APP_SECRET`,
  `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` as Fly secrets, listed in
  `DEPLOYMENT.md` and `.env.example` by name only.
- Phone numbers are PII. Mask them in logs (`+1******1234`), and never put them in URLs or
  metrics labels.
- Every repository method takes and filters by `academy_id` (ADR-0006/0007).
  The `security-reviewer` subagent reviews the webhook route, consent gate and
  tenant resolution before merge.
- Message content: templates should not include a child's full name with
  attendance details beyond what the email already contains. Keep it to first
  name and session.

## 11. Rollout

1. Phone normalization + backfill + admin "invalid number" hint. This is useful on
   its own and has no WhatsApp dependency.
2. Consent model + parent portal opt-in UI (no sends yet). This measures demand:
   how many parents opt in?
3. Port, stub, gate, construction-site test, `ParentNotifier` wired to the
   stub only.
4. Meta setup: business verification, platform number, template approval.
5. Cloud API adapter + webhook, behind `WHATSAPP_DELIVERY_ENABLED` **and** a
   per-academy toggle. Pilot one academy, starting with dues reminders.
6. Add schedule-change and absence templates once the pilot shows clean
   delivery status.

Step 2 is the cheap go/no-go: if few parents opt in, stop there.

## 12. Testing

- Unit: E.164 normalization table (US local, `+` international, junk, too
  long), consent gate (no row / opted out / number changed / store down →
  deny), template registry parameter order.
- Structural: the real WhatsApp adapter is constructed only in
  `_build_whatsapp_sender`, and local/test always gets the stub.
- Contract: webhook signature verification (valid, tampered body, missing
  header → no state change), duplicate event → 200 with no second write, `STOP` → opt-out.
- Integration: `ParentNotifier` sends email even when WhatsApp raises.
- No test, local or CI path ever calls Meta.

## 13. Open questions

1. Direct Cloud API or a BSP? The default is direct (§4). Decide in the ADR.
2. Phase 1 platform number vs per-academy numbers: do academies want messages to come
   from *their* number badly enough to justify Embedded Signup?
3. Is admin-on-behalf consent acceptable, or must consent always come from the
   parent?
4. Current utility-template pricing for US and other recipient countries. Check
   Meta's rate card before committing; this design assumes utility category only.
5. Quiet hours: schedulers run in `settings.scheduler_tz`, not academy-local
   time. Is that acceptable for WhatsApp, which feels more intrusive than email at 7am?
