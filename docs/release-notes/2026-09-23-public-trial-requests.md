# Public trial request form: anonymous `POST /api/v2/public/trial-requests` into the CRM, with the owner alert and the page form (Lane B4)

PR: #939

## What changed

- **Endpoint.** `POST /api/v2/public/trial-requests` (`backend/v2/interfaces/public/trial_request_routes.py`), anonymous. The academy comes only from the request host via the existing tenant resolver (`request.state.resolved_academy_id`); any academy, tenant, slug, child name or staff field in the body is ignored. Unknown host or unpublished page: the same plain 404 as `GET /api/v2/public/academy`. `trials_open=false`: `409 Public.TrialsClosed` with a message the page shows. Body capped at 8 KB (413). Validation is server-side with per-field messages (`422 Public.InvalidTrialRequest`, `details.fields`) that never echo submitted values: name, email (required), phone (optional, 7-15 digits), player's age (free text), optional class, optional message (<= 1000 chars), and `contact_about_request` must be true. No child name is collected.
- **One contact, no second collection.** Writes through CRM `CreateContact` with `source="website"` via a thin `SubmitWebsiteInquiry` use case (`backend/v2/contexts/crm/application/use_cases/submit_website_inquiry.py`). A repeat submission dedupes to the row already on file (existing `crm_contacts` unique index from 0192). Consent is recorded per the CRM contract: `contact_about_request=true`, `marketing` off unless ticked, `privacy_notice_url` from the academy's `public_page` settings, `captured_at` stamped by `CreateContact`. Filed as `pipeline_status="trial"` when the chosen class (or, with none chosen, any listed class) has a free seat, else `"lead"` (waitlist / "tell me when classes open").
- **Class choice.** The optional class is B2's opaque `public_id`, resolved by `ResolvePublicClassChoice` (`backend/v2/contexts/enrollment/application/use_cases/public_class_choice.py`) against the academy's published, listable classes only; a private, finished or foreign class id is a 422.
- **Identical answers.** New request, repeat and honeypot hit all return the same `200 {"state":"received"}` with `Cache-Control: no-store`. The owner alert is always handed to FastAPI `BackgroundTasks` (for every accepted submission), and the adapter decides after the response to send only for a newly created contact, so the response path does the same work either way and a mail outage cannot fail or slow a submission.
- **Honeypot.** A filled `website` field gets the normal acknowledgement and writes nothing.
- **Owner alert.** `TrialRequestOwnerEmail` (`backend/v2/composition/public_trial_requests.py`, a new composition module; `admin.py` untouched) resolves the academy's owners through the communications `AudienceResolver` (role `owner`), falls back to the academy contact email when no owner address exists, renders with `shared/comms/email_theme.shell` (all form text HTML-escaped, nothing placed in links or attributes) and sends through the existing gated email send port as TRANSACTIONAL with `reply_to` set to the family's address.
- **Rate limits.** `shared/http/rate_limit.py`: the path joins `_PUBLIC_WRITE_PATHS` at 10 per client IP per 10 minutes, plus a new per-host ceiling of 100 per 10 minutes checked only after the per-IP limit passes.
- **CRM contract.** `crm_contacts` gains an optional `message` field (<= 1000 chars, plain text, not part of the dedupe key); documented in `backend/v2/contexts/crm/README.md` with a section on the public endpoint. Existing documents need no backfill (field defaults to null).
- **Frontend.** `frontend/components/public-page/TrialRequestForm.tsx` fills B3's `#trial` slot while trials are open (the trials-closed state still renders no form). Posts same-origin through the existing BFF proxy `app/api/v2/[...path]/route.ts` (no new route). Labels tied to inputs, `aria-describedby` errors, an error summary that takes focus and links to each field, an `aria-live` acknowledgement and a focused confirmation, a honeypot hidden from people and assistive technology, the two consent checkboxes and the privacy notice link. Client logic in `frontend/lib/public-page/trial-request.ts`.
- **Tests.** Backend unit/interface tests for the route (byte-identical new vs repeat, honeypot, host-only tenant, unpublished 404, trials closed, validation, oversized body, stage choice, email once and only for new, failing send does not change the answer), the notifier, class choice, the website inquiry use case, the message field and the rate limits; a real-mongod contract test for concurrent identical submissions (one row, one answer); the public no-leak structural test now covers the request allow-list and the acknowledgement DTO. Vitest for the form and client logic; Playwright `public-tenant-trial-form.spec.ts` (success, error summary, trials closed) against the extended e2e stub backend.

## Deploy notes

- No migration (reuses `crm_contacts` and its indexes from 0192).
- Owner alerts go out through the existing email sender (`_build_email_sender`); in environments with the stub sender nothing is emailed.
- Nothing is reachable until an owner publishes the page and leaves trials open (B1 defaults: page unpublished).

## Risk / rollback

- Low-medium: first anonymous write into `crm_contacts`. Abuse is bounded by the per-IP and per-host limits, the body cap, the honeypot and dedupe.
- The rate limiter is process-local, so limits are per machine.
- Rollback: revert the PR. Contacts already written stay in `crm_contacts` as ordinary `website` leads; nothing to undo in the schema.
