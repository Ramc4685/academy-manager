# payout-period-atomic-writes

PR: #1199

## What changed
A coach payout can no longer be approved, paid, reopened, recomputed or line-edited from a screen showing an older version of it. The payout page sends the version it shows; if someone else changed the payout since, nothing is saved and the page says "Someone else changed this payout — reload to see it." with a Reload button, instead of a raw error. Generating a period writes its lines before the period that points at them, so a crash or a reader in between never sees a total with no lines, and two simultaneous generates of the same month store one period and one audit entry. Lines can only be rewritten on a draft, even if a caller skips the use case's check. Approval is refused (409) while another payout period for the same coach overlaps its dates, whatever that period's status, so overlapping windows stored before generation refused them can no longer both be paid. Retrying an approve or a mark-paid whose response was lost (same payment details) returns the stored result instead of a 409. A coach swap's draft recompute retries once on a lost race and logs an error if the period was approved meanwhile. Every payout audit entry records the period version it produced.

## Deploy notes
- Migration `0239_payout_period_versions` (applied by the release command): sets `version: 0` on payout periods stored before #1192 and adds a unique index on `payout_period_lines` (academy, period, line set, occurrence). Both are small and idempotent.
- If the migration fails with "payout_period_lines has the same occurrence more than once in one line set", a pre-#1192 recompute race left an occurrence paid twice in a period. The error names academy/period/line set/occurrence. Decide which line is right, delete the others, recompute that period (if it is approved or paid, check whether the coach was overpaid), and redeploy. Nothing else is changed before the check runs.
- If a coach has overlapping payout periods from before #504, approving either now fails with "overlaps existing payout period"; delete or correct the wrong one first.
- `expected_version` is optional in the API, so the old frontend keeps working against the new backend during the deploy window.

## Risk / rollback
- Risk: an admin who leaves the payout page open while another owner (or Recompute month) changes the period gets a conflict and must reload; that is the intended behaviour.
- Rollback: revert the PR. The backfilled `version` and the unique index are compatible with the old code (it writes one line per occurrence per set and bumps `version`).
