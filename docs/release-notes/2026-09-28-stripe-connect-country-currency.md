# Stripe Connect accounts use the academy's country and currency

PR: #TBD

## What changed

- When an academy starts connecting its own Stripe account, the new account's country and default currency now come from the academy record instead of being fixed in code. An academy with no country or currency saved is treated as US and USD, which is what every academy is today.
- Only US academies billing in USD are supported. If an academy's record says anything else (for example Canada or CAD), connecting Stripe is refused with a clear message and no Stripe account is created. Both the owner settings page and the platform admin route return this as a 409 error.
- For US and USD academies, the request sent to Stripe is exactly the same as before.
- Existing connected accounts, the payment-liability setup, retry keys, and the rule that the house academy (BLNO) never connects its own account are all unchanged. BLNO charges on the platform account and never goes through this path.

## Deploy notes

- No migration and no new settings. Nothing to run before or after deploy.
- The academy `country` field is optional and read only here; no academy has it today, so all academies read as US.

## Risk / rollback

- Low risk. The only new refusal is for academies whose record says a country other than US or a currency other than USD, and none exist today.
- Rollback: revert this PR. No stored data changes, so nothing needs cleaning up.
