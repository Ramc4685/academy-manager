# batch-6-backend-n-plus-one

PR: #802

## What changed

- Fixes #531 — Fixed the parent-digest N+1 in `backend/v2/composition/digests.py`. `_ParentDigestProvider` now memoizes the academy doc and default-program resolution once per academy per provider instance (`build_view` is called once per parent, so a run of N parents no longer triggers N academy fetches plus N pairs of curriculum queries), and the cached academy doc is reused for the reply-to lookup, which previously issued its own redundant `find_by_id` per parent. Added a new batched-occurrence path: `_occurrences_for_run(on_date)` fetches every non-cancelled occurrence for the academy in one exact-window query via a new `MongoSessionOccurrenceRepository.list_between`, using the digest's own timezone-aware `_day_bounds_utc` (rather than `list_on_date`'s wider ±1-day window) to avoid any behavior drift. Results are grouped in memory by both `session_id` and `template_session_id` (mirroring the `$or` used by `list_for_session_between`) and cached by `on_date`; `_session_today` now looks up this in-memory map instead of issuing one `list_for_session_between` call per enrollment. Per-family output is unchanged — the existing 13 digest tests pass unmodified in behavior, only their fixture shape updated to add `session_id` fields.
- Fixes #545 — Fixed two of the three N+1 fans described in the issue. (1) `admin_registration_review.list_pending()` now fetches the registration waiver template once per call instead of once per pending application row (`_row` takes an optional pre-fetched `template` kwarg). (2) `mongo_session_repo.available_for_parent_catalog()` now computes `enrolled_count` for all sessions on the page with a single `$group` aggregation over `enrollments` instead of one `count_documents` call per session. Output is unchanged in both cases. The third item in the fix plan — batching `_active_existing_student_id`'s 3-lookups-per-application student-match queries into bulk `StudentRegistrationQuery` methods — was deliberately not implemented; it needs new Protocol methods across `ports.py`/`mongo_student_repo.py` and careful preservation of the per-application ambiguous-match/MANUAL_REVIEW short-circuit semantics, a materially riskier change than this P3 nice-to-have justifies without a design decision. Flagged as follow-up work, not part of this PR.

## Deploy notes

No migrations. No manual env var or config changes.

## Risk / rollback

Both fixes are read-path performance changes with output deliberately held constant (existing tests assert unchanged per-family/per-row shape; #531's fixture change is shape-only, not behavior). The new `list_between` query and the `$group` aggregation are additive query-side changes, not schema changes. If anything regresses in prod, revert this PR's merge commit — no data migration to unwind.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
