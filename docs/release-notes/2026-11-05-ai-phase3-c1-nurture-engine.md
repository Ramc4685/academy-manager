# AI Phase 3 C1: lead follow-up email sequence

## What changed

- Academies can send up to three follow-up emails to new leads, 2, 7 and 21 days after they ask, written by the owner on Settings > Notifications with a preview. No AI is used.
- Only leads who ticked "news and offers" and are still a lead or trial get them, one sequence per inbox, and only leads who arrive after the switch is turned on.
- The emails stop when the lead replies (a pipeline reply or any logged contact), staff move the card, the lead unsubscribes, or the family enrolls. The instant acknowledgement is unchanged.
- Each email goes through the existing lead send path with the unsubscribe footer and opt-out check, at most once per lead per step, from a new daily job `send_nurture_steps` (10:25 academy time).

## Deploy notes

- The feature is off by default for every academy; nothing sends until an admin switches it on and writes at least one step.
- Apply migration 0225 (`0225_nurture_sends`, the unique claim index on `nurture_sends`) before deploying.
- The new job reports to Sentry Crons and the ops digest stale-job list as `send_nurture_steps`; add the Sentry monitor if monitors are created by hand.

## Risk / rollback

- Emails go only to leads with marketing consent and only after an academy opts in, so the exposure is limited to academies that turn it on. To stop sends without a deploy, switch it off in Settings.
- Rollback is a revert of this PR. The `nurture_sends` collection, its index and the `crm_nurture` field on academy documents can stay; nothing else reads them.

PR: #1156
