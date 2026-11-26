// K05: Dev Patel (from k00) moved from the Saturday class to Wednesday the way
// the admin transfer does it: the enrollment's session_id changes in place, a
// "moved" lifecycle event is recorded and one seat moves across. His Sat Nov 21
// mark stays on the old class. Run k00 first. Used by S07, S25 and S27.
const A = "acad_demo_academy", SID = "seed_student_dev_patel", EID = `seed_enrollment_${SID}`;
const FROM = "demo_session_sat", TO = "demo_session_wed", now = new Date();

if (!db.enrollments.findOne({academy_id: A, enrollment_id: EID})) {
  print("k05: Dev Patel's enrollment is missing; run k00 first");
  quit(1);
}
// Filtered on the old session, so a re-run moves nothing and no seat twice.
const moved = db.enrollments.updateOne({academy_id: A, enrollment_id: EID, session_id: FROM},
  {$set: {session_id: TO, updated_at: now}}).modifiedCount;
if (moved) {
  db.sessions.updateOne({academy_id: A, session_id: FROM, reserved_seats: {$gt: 0}}, {$inc: {reserved_seats: -1}});
  db.sessions.updateOne({academy_id: A, session_id: TO}, {$inc: {reserved_seats: 1}});
}
db.enrollment_events.updateOne({academy_id: A, event_id: "kit_k05_move"}, {$setOnInsert: {
  event_id: "kit_k05_move", academy_id: A, event_type: "moved", enrollment_id: EID, session_id: TO,
  from_session_id: FROM, to_session_id: TO, student_id: SID, actor_id: "demo_user_owner",
  reason: "Moved to Wednesday (persona kit)", effective_at: now, occurred_at: now,
  billing_policy: "move_proration", billing_result: "skipped", metadata: {kit: "k05"}}}, {upsert: true});

// The Sat Nov 21 mark in the old class, kept for history.
const nov21 = db.session_occurrences.findOne({academy_id: A, session_id: FROM, occurrence_id: /:2026-11-21:/});
if (nov21) {
  db.attendance.updateOne({academy_id: A, occurrence_id: nov21.occurrence_id, student_id: SID},
    {$setOnInsert: {attendance_id: "kit_k05_att_nov21"}, $set: {session_id: FROM, marked_by: "demo_user_coach",
      marked_at: now, status: "present", client_app_version: "persona-kit", entry_source: "enrollment"}}, {upsert: true});
}
print(`k05: Dev Patel ${moved ? "moved" : "already"} on ${TO}; Nov 21 mark ${nov21 ? "kept" : "skipped (no occurrence)"}`);
