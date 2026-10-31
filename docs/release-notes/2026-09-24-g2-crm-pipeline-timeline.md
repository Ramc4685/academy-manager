# People CRM: trial outcome, Pipeline board, auto follow-up, unified timeline and Messages tab (L3, L4)

PR: #965

## What changed

- **Trial Came / Didn't come (L3a):** coaches (coach Today) and admins (Inbox) mark an approved trial's outcome. The trial becomes `completed` with `outcome` `came` or `no_show`. New routes: `POST /admin/self-service/trials/{request_id}/outcome` and `POST /coach/trials/{request_id}/outcome`.
- **Pipeline card moves (L3a):** `POST /admin/crm/contacts/{contact_id}/pipeline-move` records a staff override with author and time. A card can move forward one column at a time and back any number. It is never moved to Enrolled by hand.
- **Pipeline board (L3b):** `/admin/families?view=pipeline` shows Inquiry / Trial booked / Trial done / Registered / Enrolled, a phone stage switcher, and quick add lead (`POST /admin/crm/contacts`). Cards show no money.
- **Auto follow-up (L3c):** a new daily job, `create_trial_follow_ups` (04:50), adds one "Trial passed, no registration" follow-up per trial marked Came 7 to 60 days ago when the family has not registered. It is idempotent per trial.
- **Unified family timeline (L4a/L4b):** `GET /admin/families/{parent_id}/timeline` merges billing, attendance, requests, coach notes, allowlisted admin audit actions (including moved-family entries) and CRM records. It collapses duplicates, pages with a cursor, and redacts money for front desk.
- **Family Messages tab (L4c):** a thread of app-sent messages plus staff-logged contacts, with WhatsApp / SMS / email handoff and a "Did you send it?" log. The app sends nothing new.

## Deploy notes

- Run the production migrate job for **0201_crm_follow_up_source_key** (unique partial `family_follow_ups (academy_id, source_key)`), **0202_family_timeline_indexes** (six timeline lookup indexes on `audit_logs`, `absence_notices`, `pause_requests`, `makeup_requests`) and **0203_family_contact_log** (`family_contact_log` indexes). They apply after the pending 0192-0200.
- Owner step: apply 0201 before the first 04:50 run of `create_trial_follow_ups` if possible. Without the index, the job still writes through an upsert on `(academy_id, source_key)`, but concurrent runs are not protected by a unique key.
- No new secrets, feature flags, Stripe or DNS changes.

## Risk / rollback

- Risk is moderate and limited to the admin CRM surfaces and the trial outcome writes. The trial and pipeline writes are compare-and-swaps scoped to the tenant. The timeline and Messages reads turn a failing source into a warning, never a 500.
- Rollback: revert the PR and redeploy. The new indexes and the `family_contact_log` collection are additive and can stay in place. Follow-ups the job created are ordinary follow-ups that staff can mark done. Trial rows marked `completed` keep their outcome fields, which older code ignores.
