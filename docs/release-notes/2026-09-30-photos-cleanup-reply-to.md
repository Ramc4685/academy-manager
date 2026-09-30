# Public page photo cleanup and effective reply-to on the Email card

PR: #TBD

## What changed

- Uploaded public page photos (hero, gallery, coach) are now deleted from storage after a settings save removes or replaces them, unless the same photo is still used elsewhere on the page. Only objects this academy uploaded for that purpose are ever deleted; logos are never touched. A failed delete is logged and does not fail the save.
- Settings > Integrations > Email now shows the reply-to that emails actually use: the explicit reply-to, else the support email marked "(support email)", else "Not set". `GET /admin/academy` gains read-only `effective_reply_to` and `effective_reply_to_source`, computed by the same resolver the senders use. Closes #1014.

## Deploy notes

No migration. No new configuration; photo cleanup uses the existing media storage bucket.

## Risk / rollback

Photo deletion is irreversible once a save commits; it is limited to URLs that pass the anchored provenance check. Revert the PR to restore the old behavior (orphaned files then accumulate again). The API fields are additive.
