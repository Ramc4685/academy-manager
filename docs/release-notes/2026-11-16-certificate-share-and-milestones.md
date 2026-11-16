# certificate-share-and-milestones

PR: #1195

## What changed
A parent can now make a public link for their own child's certificate. The certificate page has a "Public link" card with Create public link, Copy link and Stop sharing. The server builds the link as `/c/<token>` on the academy's own address (its `<slug>` subdomain of the deployment's frontend URL, the same rewrite the emails use), so a parent signed in on the shared product host still gets a link that opens. "Share with family" sends that public link once the parent has made one. The page shows only the child's first name (or first initial, if the academy chooses that), the level name, number and colour as they were when the certificate was issued, the certificate number, the issue date and the academy's name and logo. It never shows a surname, parent details, email or internal ids. Stop sharing, a revoked certificate, an unknown link and a link opened on another academy's address all show the same "not found" page. The page is never indexed by search engines, even while shared. The public read is rate limited per visitor across all links, and creating or stopping a link writes a `certificate.share_created` / `certificate.share_revoked` audit row (the token itself is never stored in the audit log).

Owners and admins get a new "Milestones and sharing" card in Settings > Curriculum. It is off with no milestones until the academy sets it up. Each milestone is "N skills mastered" or "N levels completed". Skills count real passes only (silent placement credits do not count) and levels count issued certificates, so a level closed by a placement does not count. A new milestone only counts what students reach after it is added, and turning milestones back on starts counting again from that moment; a milestone removed from the list stops showing. When milestones are on, a reached milestone shows on the parent's progress page and as a line in the evening wins email; when they are off, nothing new appears anywhere. The same card holds the share-name rule (first name or first initial) for public certificate links. Every change writes a `progress_settings.changed` audit row.

## Deploy notes
Migration `0241_student_milestones_index` runs through the release_command. It adds the partial unique index `student_milestones_one_per_key_uq` on the new `student_milestones` collection (one record per student per milestone). The collection starts empty, so there is nothing to check before deploying and no manual step.

The academy's milestone settings live in a new `progress_settings` field on the academy document, written with a targeted `$set`. Nothing is set until an owner or admin saves the card. An unreadable stored value reads as "off" and reports to Sentry instead of failing the page.

## Risk / rollback
Milestones are off by default, so no family sees anything new until an academy turns them on. A milestone row is created once and never changed; the email only mentions a milestone reached inside that evening's window, so turning milestones on does not send a backlog of old ones. Known limit: the evening email includes a milestone only when the child also had a pass or a certificate that evening.

Roll back by reverting the merge commit. Existing share links then stop resolving (the public route is gone) and the share card disappears; the `share_token` values stay on certificates harmlessly and account deletion still removes them. The `student_milestones` collection and its index can stay, or drop them.
