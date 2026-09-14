// Shared sticky-actions-column classes for admin tables where the last
// column holds row actions (Approve/Deny/Review, etc). At narrow viewports
// these tables scroll horizontally; without this the actions column scrolls
// off-screen with everything else. `right-0` pins it to the visible edge,
// the negative-offset shadow signals "more content to the left", and the
// background keeps scrolled-under cells from showing through.
//
// Originally introduced for the session detail page (#716/#717); reused here
// (#747) by the admin approval queues (Makeups, Trials, Pauses, Level-ups,
// Registrations). See app/(admin)/admin/sessions/[id]/format.ts, which
// re-exports these same constants so its existing consumers are unaffected.
export const actionHeaderClass =
  "sticky right-0 z-10 bg-white shadow-[-12px_0_16px_-18px_rgba(15,23,42,0.5)]";
// Deliberately has no background baked in: some callers (e.g. RosterPanel)
// need to pair it with a row-specific tone class, others append `bg-white`
// themselves — see the consumers of this constant for the pattern to match.
export const actionCellClass =
  "sticky right-0 z-10 px-4 py-3 shadow-[-12px_0_16px_-18px_rgba(15,23,42,0.5)]";
