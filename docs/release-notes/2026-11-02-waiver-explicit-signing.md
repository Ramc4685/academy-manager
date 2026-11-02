# waiver-explicit-signing

PR: #1110

## What changed
Signing a waiver is now a deliberate act. Parents type their full legal name and tick an unticked consent box ("I agree to sign electronically...") before Sign is enabled, both on the Waivers page and during registration; the server refuses a signature without them (422). A parent with several children can choose which children to sign for. Every signature now stores the typed name, the consent wording, IP address and device, and registration signatures carry the same evidence through to approval. Parents get a printable signed copy at `/parent/waivers/signatures/<id>` (exact text, signer, time, IP, device, SHA-256), admins see the same copy on the signature detail page, and the signer gets one receipt email per signing act with a link to each signed copy. A retry that signs nothing new sends no email. The client-IP helper moved from the payment routes to `backend/v2/shared/http/client_ip.py` and now follows the rate limiter's rule: `CF-Connecting-IP` when the BFF proxy vouches with the shared secret, else `Fly-Client-IP`. `X-Forwarded-For` is no longer read, so a client can no longer forge the recorded IP (checkout audit rows too).

## Deploy notes
No migration. **Before deploying, set the proxy secret pair**, or every recorded IP (and every rate-limit bucket, already today) is Cloudflare's egress address: generate one random value and set it as `PROXY_SHARED_SECRET` on Fly app `courtmastr-academy-api` and `BFF_PROXY_SHARED_SECRET` on Worker `academy-next`. It was not set on Fly as of 2026-11-02. Deploy backend and frontend together: the accept endpoint now requires `consent: true`, so a parent on a cached old frontend gets a "type your name and tick the box" error until they reload. Older signatures without a typed name or consent show "Not recorded" on the signed copy. The receipt goes through the existing gated email sender (stub outside production).

## Risk / rollback
Medium-low: changes the parent signing step and adds two read routes (parent and admin signed copy, both 404 for anyone but the signer's family or the academy's staff). Existing signatures are untouched. Registration approvals do not send a separate receipt; those signatures appear on the parent's Waivers page with a signed-copy link. Revert this PR to roll back; signatures recorded meanwhile keep their extra fields harmlessly.
