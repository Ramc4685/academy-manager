# X2: parents can confirm waitlist seat offers; offers never end a held family's seat

PR: #976

## What changed
- Families can now answer a waitlist seat offer. The "a seat opened" email links to `/parent/requests?offer=<id>`, which shows the offer, a countdown, **Confirm seat** and **Decline** (with a second look), plus honest states for expired, closed or already-taken offers. New routes: `GET /api/v2/parent/waitlist`, `POST /api/v2/parent/waitlist/{id}/decline` (confirm already existed but nothing called it, so every offer since 0183 on ~2026-09-14 expired unclaimed).
- Admin session Waitlist tab and Inbox > Waitlist now show offered rows with "Held until …" (academy time) and a "Seats offered" count. Skip/Remove on an offer ("Withdraw offer") releases the held seat and offers it to the next family. Before, those rows were hidden and a bare status write would have leaked the seat.
- Owner decision 2026-09-25, reclaim on confirm: an offer no longer ends a held family's enrollment under `hold_reclaim_policy=longest_held`. If a class is full only of holds, the offer goes out without a seat, and the hold is reclaimed only when the family clicks Confirm. If the held family has come back by then, the waiting family stays first on the list. A seat that frees up goes to such an offer first.
- The expiry email no longer claims the child is "still on the waitlist". Expired entries are closed.

## Deploy notes
- No migration, no env vars. The new `waitlist.offer_holds_seat` field is optional; rows without it are treated as holding a seat, which is correct for every offer made before this deploy. The 0133/0183 validator does not restrict extra fields.
- Owner follow-up (read-only): run `mongosh "<prod uri>" --quiet --file docs/runbooks/x2-waitlist-offers-readonly-query.js`. It lists offers since 2026-09-14 that were never confirmed, and held enrollments ended by a reclaim. For `requested_by` of the form `waitlist_promotion:<id>` where the offer status is `expired` or `removed`, the family lost their held seat for nobody. Staff should contact both lists.

## Risk / rollback
- Touches seat arithmetic: offer, confirm, decline and sweep. Confirm, decline and the sweep now close an offer only by compare-and-set from `offered`, so at most one of them uses or releases its seat. There is a known residual: a process crash between confirm's claim and the enrollment write leaves a `promoted` row with no enrollment. The seat stays counted and the reserved-seat reconciler recovers it.
- If this is wrong, a class can be one seat off. Check `sessions.reserved_seats` against active, held and seat-holding offered rows.
- Rollback: revert this PR and redeploy backend and frontend. Rows written with `offer_holds_seat: false` would then be released by the old sweep as if they held a seat, so run the query above before rolling back.
