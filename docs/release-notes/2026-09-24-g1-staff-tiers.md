# Front desk "owes money" flag and Families reads for staff tiers

PR: #961

## What changed
Billing and front desk staff can now read the Families list, its counts and a family's record row (#553, L2b). The server decides what money each caller sees: owner, admin and billing get amounts; front desk gets only an "Owes money" yes/no, never an amount, and cannot sort or filter by balance. The Families list, the family record header and the Overview card show the flag for front desk. Owners get a "Viewing as" picker (Owner, Billing, Front desk) on the Families pages to preview what each tier sees; it only hides, it never reveals more. Every other admin page, the family Billing tab and money reports stay closed to billing and front desk as before. Also drops a duplicate dictionary key in the two-tenant isolation test that failed ruff on main.

## Deploy notes
No migration id (none added; no migration ids ship in this PR). No owner steps are needed to deploy. No env vars. Staff with only the billing or front desk role still cannot open the admin app shell; that comes in a later slice, so today the flag is visible through the API and through the owner's preview.

## Risk / rollback
If wrong, a front desk member could see a balance amount on the three Families reads, or an admin could lose the balance column. Payload tests per role guard both. Owner-only money actions are unchanged. Roll back by reverting the PR; no data changes.
