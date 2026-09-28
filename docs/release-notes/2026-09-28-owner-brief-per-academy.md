# Owner daily brief: one brief per academy, sent to its owners

PR: #989

## What changed

- The 07:30 owner brief (issue #776) used to add up every academy's numbers into one email and send it to `OWNER_BRIEF_EMAIL` (or `OPS_ALERT_EMAIL`). Each academy now gets its own brief. Every count (new enrollments, students who left, registrations waiting, failed payments, open invoices, missing waivers, families we can no longer email) covers only that academy's data.
- Each academy's brief goes to its active owners. BLNO's recipient does not change: while `OWNER_BRIEF_EMAIL` or `OPS_ALERT_EMAIL` is set, BLNO's brief (the house academy) still goes to exactly that address, as before. Those addresses never receive another academy's brief. An academy with no owner email is skipped and logged.
- "Families we can no longer email" now counts only bounced addresses that belong to that academy's families (the parents of its students, plus its family contacts). The suppression list itself is still shared across academies.
- The subject and heading now include the academy name, e.g. `Academy brief 2026-09-28 — action needed · BLNO Badminton Academy`. The `Academy brief <date> — ...` prefix is unchanged, so existing inbox filters keep matching.
- If one academy's brief fails, it is logged and reported to Sentry, and the rest still send.
- The brief no longer needs a cross-tenant exception in the tenant-scope guard test. A new test keeps that exception from being added back.

## Deploy notes

- No migration and no new setting. `OWNER_BRIEF_EMAIL`, `OPS_ALERT_EMAIL` and `HOUSE_ACADEMY_ID` mean the same as before. If `HOUSE_ACADEMY_ID` is unset, the runtime academy counts as the house academy.
- Same cron (07:30 scheduler time), the same 30-minute lease and the same send path as before.

## Risk / rollback

- Low. The brief only reads data. The main change is who receives it: owners of any other academy now get their own brief each morning. BLNO's recipient does not change while the env address is set.
- The loop covers every row in `academies`, the same list every other per-academy job uses, in single-academy mode too. If production holds any academy row besides BLNO that has an active owner membership with an email, that owner starts getting a brief for that academy.
- The subject now ends with the academy name. A filter that matched the whole subject exactly would need updating. Filters that match on the prefix are unaffected.
- Rollback: revert this PR. The brief goes back to one combined email sent to the env address.
