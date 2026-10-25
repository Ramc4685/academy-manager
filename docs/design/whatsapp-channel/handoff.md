# Handoff — WhatsApp via OpenWA, phase 1 (local slice)

Paste the **Prompt** section into a new Claude Code session opened in
`~/Documents/Code/academy-manager`.

## Where things stand (2026-10-25)

- **Branch:** `docs/whatsapp-channel-design`. Docs: `docs/design/whatsapp-channel/{design.md,prd.md,handoff.md}`.
  The branch was cut from `fix/release-note-title-766` (its upstream is gone). Rebase onto `main` before any PR.
- **OpenWA** `ghcr.io/rmyndharis/openwa:0.25.0` runs in Docker on the Mac:
  - container `openwa-api`, API and dashboard at `http://localhost:2785` (bound to 127.0.0.1 only)
  - helper container `openwa-docker-proxy`; data volume `openwa_openwa-data`
  - compose project lives in a temporary session folder. **Before the old session is deleted, copy the
    compose setup somewhere permanent** (or recreate it from the upstream repo with the pinned image).
- **Session** `academy-test` (id `92e82544-6b5d-4821-a2be-c5a1f2927f88`) is **linked to the owner's
  personal number** (…9243), status `ready`. A test message was sent and received.
- **Admin API key:** `docker exec openwa-api cat /app/data/.api-key` (drop the trailing `%` zsh shows).
  It appeared in a chat transcript once, so **rotate it before any server deployment**.
- **Known quirks seen:**
  - WhatsApp once refused linking with "Can't link new devices right now". It worked later from the dashboard.
  - OpenWA logs a WhatsApp Web build mismatch warning (running build ≠ pinned build).
- **Corrections already folded into the docs:** academy-manager's absence emails confirm absences the
  *parent reported* (#616). There is no "marked absent by coach" notice.

## Prompt

```text
Read AGENTS.md, then docs/design/whatsapp-channel/prd.md and design.md.

Goal: build PRD phase 1, "urgent session announcement → post to the class WhatsApp group via
OpenWA", tested locally against a test group, without ever risking email delivery.

Context:
- OpenWA runs locally in Docker at http://localhost:2785 (session "academy-test", already linked).
  From the academy-manager backend container it is reachable at host.docker.internal:2785
  (verify; otherwise put both on a shared Docker network).
- Relevant code: backend/v2/composition/session_announcements.py (post(), _fan_out,
  AnnouncementPostResult), backend/v2/composition/digests.py (_build_email_sender, the single
  construction-site pattern), backend/v2/contexts/communications/application/ports.py,
  backend/v2/tests/structural/test_email_sender_construction.py, the Session.whatsapp_group_link
  field (enrollment/domain/models.py), backend/v2/shared/config/settings.py.
- OpenWA API: POST /api/sessions/{id}/messages/send-text {"chatId","text"}; group ids end in @g.us;
  GET /api/sessions/{id}/groups/join-info?code=<invite code> resolves an invite link; auth header
  X-API-Key. Use an OPERATOR key scoped to the one session, never the admin key.

Constraints:
- Repo rules say local/test never call real providers. P0-2 proposes a sandbox exception
  (real OpenWA only for chat ids in WHATSAPP_SANDBOX_CHATS). Confirm with me before implementing it,
  and update docs/agent/backend-api-rules.md to match.
- Email fan-out must be unaffected: WhatsApp runs after email, with a short timeout, never raises.
- Follow the repo's TDD and verification skills (academy-verification); run the security-reviewer
  subagent before merge (new secrets + outbound provider).

Steps: plan first (P0-1…P0-8 in prd.md), show me the plan, then implement on a new branch off main.
Done = a urgent post on a test session appears in my test WhatsApp group; stopping OpenWA still
sends email and returns whatsapp_status=failed; all backend checks green.
```

## Checklist for the owner before starting

- [ ] Create a WhatsApp group "AM test" with yourself and one other phone. Copy its invite link.
- [ ] In the OpenWA dashboard → API Keys, create an **operator** key limited to `academy-test`.
- [ ] Decide on the sandbox exception (P0-2): yes or no.
- [ ] Keep the Mac awake and Docker running during tests.
- [ ] Optionally unlink your personal number when not testing (*Settings → Linked devices*).

## What we'll learn for the server (fill in during phases 1–2)

| Item | Value found in testing |
|---|---|
| RAM used by OpenWA with one session | |
| Disk used by `openwa-data` after 2 weeks | |
| OpenWA env vars actually needed | |
| How the backend reaches OpenWA (URL, network) | |
| Re-link procedure that worked (QR or pairing code) | |
| Messages per day at pilot volume | |
| Any WhatsApp warnings or restrictions | |
