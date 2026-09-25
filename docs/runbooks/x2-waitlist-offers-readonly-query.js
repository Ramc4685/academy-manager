// X2 follow-up — READ-ONLY. Families affected by waitlist offers nobody could
// confirm (live since migration 0183, ~2026-09-14).
// Run: mongosh "<prod uri>" --quiet --file docs/runbooks/x2-waitlist-offers-readonly-query.js
// Only aggregate() reads; nothing here writes.
const ACADEMY = "blno";
const SINCE = ISODate("2026-09-14T00:00:00Z");

const join = (from, localField, foreignField, as, project) => ({
  $lookup: {
    from, as,
    let: { k: "$" + localField, a: "$academy_id" },
    pipeline: [
      { $match: { $expr: { $and: [{ $eq: ["$" + foreignField, "$$k"] }, { $eq: ["$academy_id", "$$a"] }] } } },
      { $project: Object.assign({ _id: 0 }, project) },
      { $limit: 1 },
    ],
  },
});

print("== 1. Waitlist offers made since 2026-09-14 that were never confirmed ==");
printjson(db.waitlist.aggregate([
  { $match: { academy_id: ACADEMY, status: { $in: ["expired", "offered"] }, offer_expires_at: { $gte: SINCE } } },
  join("students", "student_id", "student_id", "student", { full_name: 1 }),
  join("users", "parent_id", "user_id", "parent", { display_name: 1, email: 1, phone: 1 }),
  join("sessions", "session_id", "session_id", "session", { title: 1, status: 1 }),
  { $project: {
      _id: 0, waitlist_id: 1, status: 1, offer_expires_at: 1, joined_at: 1,
      student: { $first: "$student.full_name" },
      parent_name: { $first: "$parent.display_name" },
      parent_email: { $first: "$parent.email" },
      parent_phone: { $first: "$parent.phone" },
      session: { $first: "$session.title" },
  } },
  { $sort: { offer_expires_at: 1 } },
]).toArray());

print("== 2. Held enrollments ENDED by a hold reclaim since 2026-09-14 ==");
print("   (requested_by 'waitlist_promotion:<id>' = reclaimed to make a waitlist offer)");
printjson(db.enrollment_events.aggregate([
  { $match: { academy_id: ACADEMY, event_type: "hold_reclaimed", occurred_at: { $gte: SINCE } } },
  join("enrollments", "enrollment_id", "enrollment_id", "enrollment", { status: 1, parent_id: 1, hold_reclaim_for: 1 }),
  join("students", "student_id", "student_id", "student", { full_name: 1, parent_id: 1 }),
  join("sessions", "session_id", "session_id", "session", { title: 1 }),
  { $addFields: {
      _parent_id: { $ifNull: [{ $first: "$student.parent_id" }, { $first: "$enrollment.parent_id" }] },
      // "waitlist_promotion:<id>" = reclaimed by a waitlist promotion. Before
      // the X2 fix that includes offers (harmful when the offer then expired);
      // a paused child resuming via the waitlist is legitimate. The offer row's
      // final status below tells them apart.
      _wl_id: { $cond: [
        { $eq: [{ $indexOfCP: [{ $ifNull: ["$metadata.requested_by", ""] }, "waitlist_promotion:"] }, 0] },
        { $substrCP: ["$metadata.requested_by", 19, 64] }, null] },
  } },
  join("waitlist", "_wl_id", "waitlist_id", "offer", { status: 1, offer_expires_at: 1, student_id: 1 }),
  join("users", "_parent_id", "user_id", "parent", { display_name: 1, email: 1, phone: 1 }),
  { $project: {
      _id: 0, occurred_at: 1, enrollment_id: 1,
      requested_by: "$metadata.requested_by",
      for_waitlist_offer: { $eq: [{ $indexOfCP: [{ $ifNull: ["$metadata.requested_by", ""] }, "waitlist_promotion:"] }, 0] },
      enrollment_status_now: { $first: "$enrollment.status" },
      offer_status: { $first: "$offer.status" },  // "expired"/"removed" = seat freed for nobody
      offer_expires_at: { $first: "$offer.offer_expires_at" },
      student: { $first: "$student.full_name" },
      parent_name: { $first: "$parent.display_name" },
      parent_email: { $first: "$parent.email" },
      parent_phone: { $first: "$parent.phone" },
      session: { $first: "$session.title" },
  } },
  { $sort: { occurred_at: 1 } },
]).toArray());

print("== 3. Current hold-reclaim policy (before the X2 fix, longest_held let an offer end a hold) ==");
printjson(db.enrollment_departure_policies.find({ academy_id: ACADEMY }, { _id: 0, hold_reclaim_policy: 1, updated_at: 1 }).toArray());
