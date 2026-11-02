# level-certificate

PR: #PENDING

## What changed
Finishing a level now gives families a real certificate: a parent screen at `/parent/progress/certificates/{certId}` (from the evening win email's "See the certificate" button, the journey's "View certificate" win and the Certificates list) shows a printable Letter-landscape certificate with the academy's logo and brand colour, the student's name, "Level N · level name", the program, the level's required skills, the completion date (in the academy's timezone) and the certificate number, plus "Print or save as PDF", "Share with family" (the phone's share sheet; print where there is none) and an "Up next" link. Admins get the same rendering from a "View / print" link on the student's progress page. Backed by two new read routes, `GET /api/v2/parent/students/{id}/certificates/{certId}` (own child only) and `GET /api/v2/admin/students/{id}/certificates/{certId}`. No coach is recorded on a certificate, so the academy signs it ("Awarded by").

## Deploy notes
None. No migration, no new settings. The logo comes from the academy's existing Settings logo (`logo_url`, https only); with no logo the academy's monogram is shown.

## Risk / rollback
Read-only. If the page misbehaves, roll back this PR: the email button reverts to the progress page and the certificate list rows to plain rows. Emails already sent with a certificate link would then land on a 404 page until the rollback is reverted.
