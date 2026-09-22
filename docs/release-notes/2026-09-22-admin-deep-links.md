# admin-deep-links

PR: #917

## What changed

- Sidebar regroup PR4: the deep links the regrouped admin sidebar relies on, plus one gating fix the same audit surfaced.
- User detail page: the pay-rate and sessions panels now show for anyone holding a coaching role (`coach` or `assistant_coach`) in `user.roles`, not only when the primary role is `coach`. A parent who also coaches, or an assistant coach, could not be paid or assigned from their own page before. New pure helper `frontend/lib/admin/coach-roles.ts` with a unit test.
- Family page: the recurring-discount link opens the student's Sessions tab (`?tab=sessions`) instead of the Overview.
- Sessions page: a `Waitlist` link to `/admin/inbox?tab=waitlist`, where the waitlist queue lives. The old sidebar entry pointed at `/admin/waitlist`, which has never been a page.
- Messages page: in-page lane anchors (`#direct`, `#broadcast`, `#campaign`) with a labelled jump nav, so the page can be entered mid-way on a phone. The design-system `Card` gains an optional `id` prop for this.
- Billing setup roster (`backend/v2/composition/admin.py`): students with an empty `parent_id` no longer produce a parent row keyed on nothing. The file stays at 4,485 lines against the 4,500 structural cap.
- No routes added or removed; the route count stays at 92.
- Tests: `backend/v2/tests/unit/test_billing_setup_roster_adapter.py` pins the empty-parent guard against the real composition roster (fails on the pre-fix line); Playwright assertions in `admin-session-creation-ui.spec.ts` (Waitlist link href) and `admin-messages.spec.ts` (lane jump links resolve to the three lane cards).

## Deploy notes

None. No migrations, no environment changes, no new endpoints. Frontend and backend deploy together as usual.

## Risk / rollback

Low. The frontend changes are links and a display gate; the backend change skips a row that was malformed. Rollback is reverting the PR. If the roles-aware gate shows the coach panels for a user who should not see them, the primary-role behaviour is one line in `frontend/app/(admin)/admin/users/[userId]/page.tsx`.
