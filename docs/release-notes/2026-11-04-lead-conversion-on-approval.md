# lead-conversion-on-approval

PR: #1116

## What changed
Approving a registration now marks the academy's matching inquiry (same parent email, lower-cased) as enrolled on the People CRM pipeline and links it to the family, so the "Inquiry conversion by source" report stops reading 0% for website and phone leads. Inquiries with no matching email, and ones already enrolled, are left alone.

## Deploy notes
none (no migration; the write uses the existing `crm_contacts` email lookup index from 0198).

## Risk / rollback
If the match were wrong, an inquiry could be marked enrolled under the wrong parent id; the write is tenant-scoped and keyed on the exact normalised email, and a failure is logged and never fails the approval itself. Rollback is reverting the PR; rows already marked enrolled keep that status (an operator can correct them by hand, nothing else reads the two link ids yet).
