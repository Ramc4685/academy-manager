# whatsapp-class-group-announcements

PR: TBD

## What changed
Urgent session announcements can also be posted to the class WhatsApp group (the session's saved WhatsApp group link) through a self-hosted OpenWA gateway. Email is unchanged and always goes first; the WhatsApp post is best-effort and its result (`whatsapp_status`: sent / skipped / failed) is shown next to the email result on the admin and coach announcement panels. Off unless `V2_WHATSAPP_DELIVERY_ENABLED` and the OpenWA settings are configured. In local dev, real posts only reach chat ids on `V2_WHATSAPP_SANDBOX_CHATS`.

## Deploy notes
None for production: the channel stays off until OpenWA runs on an always-on host (see `docs/design/whatsapp-channel/prd.md`). Removes the unused `TWILIO_*` placeholders from `backend/.env.example`.

## Risk / rollback
OpenWA is an unofficial gateway; the linked number can be restricted by WhatsApp. Turning `V2_WHATSAPP_DELIVERY_ENABLED` off disables the channel with no other effect; reverting the PR removes it.
