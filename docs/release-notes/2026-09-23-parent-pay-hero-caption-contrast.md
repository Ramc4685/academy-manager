# Parent pay hero "Secure checkout" caption meets WCAG AA contrast (UI-4)

PR: #954

## What changed

- On `/parent/payments`, the "Secure checkout via Stripe" caption under the Pay balance button now uses the `rally-subtle-ink` token instead of `rally-subtle`. Contrast on the night card goes from about 4.0:1 (fails AA) to over 7:1. The class is the only change; nothing else on the page changed.
- The D11 axe gate now scans the parent payments page with a balance due. A node contrast test also pins the caption to an AA-passing token.
- Test-only fix: the two-tenant isolation test's id map now includes `contact_id`, for the family contacts route added in #950. This makes the route-inventory check pass on main again.

## Deploy notes

- No migrations, no config or secrets, no owner steps. Frontend styling plus tests only.

## Risk / rollback

- Very low. It changes one CSS class on one caption. To roll back, revert this PR. The caption goes back to its old colour, which is readable but below AA contrast.
