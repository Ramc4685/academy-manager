# recoverable-class-pass

PR: #1240

## What changed
A class recap now saves each child's skill passes along with the taught skills and practice, and each pass counts once per class, child and skill. Retrying a save, two coaches saving at once, or a save that stopped part way all end with one test attempt, one N_TRIES try and one `SkillPassed` event, without relying on the idempotency cache. A pass that is still finishing, or one a stopped save never reached, shows "Pass still saving" in the coach's recap, and any later save completes it. A coach's take-back closes a class pass that was still finishing, so a later save never restores it. A counted pass cannot be removed by editing the recap; that needs a formal reassessment. A pass the skill rules never counted (a child who is not placed, for example) can be taken off. Later edits keep every pass, never re-run a landed pass's level-up, and never revive an old pass that was later reassessed. An N_TRIES skill shows "Counted as a try" until its Nth try. An undone try no longer counts toward a later class's pass. Formal tests still store every attempt. The step-2 `POST .../class-demonstrations` route is replaced by `passes` on the recap save (`PUT .../class-recap`).

## Deploy notes
Migration `0247_test_attempts_observation_key` adds a partial unique index on `test_attempts` (`academy_id`, `observation_key`), covering only rows that have a key. Existing attempts have no key, so the index builds without conflicts, and it applies automatically through the release command. Outbox appends with a duplicate `event_id` are now treated as already queued. Deploy backend and frontend together (the normal Fly release): a new frontend on an old backend would have its passes ignored, while an old cached app on the new backend keeps passes unchanged.

## Risk / rollback
If the index build fails, the deploy stops before new code serves traffic; rerun after checking for duplicate keys, of which there should be none. If passes misbehave, revert this PR. Stored passes stay in recap documents and attempts stay valid history, and the index can stay in place because it is inert without the key. Unmarking an off-level class pass is still not possible (a known gap from step 2).
