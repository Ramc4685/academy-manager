# Email sender: each Resend sender uses its own API key

PR: #991

## What changed

- The Resend email adapter used to store its API key in the Resend library's single shared setting. If two senders with different keys ever ran in the same server (one per academy, which is the plan once academies bring their own Resend account), every email would go out under whichever key was set last. Each sender now keeps its own key and sends through its own HTTP request. The shared setting is no longer read or written.
- The request sent to Resend is the same as before: same address (`https://api.resend.com/emails`), same headers, same JSON body, same 30-second timeout. Resend's error replies raise the same errors as before, so failed sends and the boot-time key check behave as they did.
- The hardcoded fallback sender `noreply@academy.app` is gone. That domain is not ours. The From address is now `SENDER_EMAIL` if set, otherwise `noreply@<FRONTEND_URL host>`. Production resolves to the same address as today.
- Tests can no longer reach the real Resend API. A suite-wide guard fails any request that a test has not routed to a fake.

## Deploy notes

- No migration.
- No setting change is needed in production. `FRONTEND_URL` is already `https://academy.courtmastr.com`, so the sender stays `noreply@academy.courtmastr.com`, or `SENDER_EMAIL` if that secret is set.
- New: a production boot now fails loudly if email delivery is on and neither `SENDER_EMAIL` nor `FRONTEND_URL` is set. Before, it would quietly send from `noreply@academy.app`.

## Risk / rollback

- Low. Every email goes through the new request code, so a mistake there would stop mail. Tests check the exact production request (address, headers, body, From), and the boot-time key check still runs on deploy and alerts if the key is rejected.
- Rollback: revert this PR. Nothing is stored, so there is nothing to undo.
