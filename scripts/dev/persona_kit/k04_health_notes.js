// K04 (S49, S50, S63): three children on Demo Coach's Junior Beginners roster
// with the three health answers. Sam Demo: "Peanut allergy, carries EpiPen"
// plus an emergency contact. Alex Demo: "none declared" (the base seed's
// value). Mia Kitwell (new, enrolled here): never answered (field empty).
// Fake people only; this is the one kit that writes a health note, on purpose.
const A = "acad_demo_academy", SESSION = "demo_session_sat", PARENT = "demo_user_parent";
const now = new Date();

db.students.updateOne({academy_id: A, student_id: "demo_student_sam"}, {$set: {
  medical_notes: "Peanut allergy, carries EpiPen", emergency_contact_name: "Rosa Demo",
  emergency_contact_phone: "(309) 555-0177"}});
db.students.updateOne({academy_id: A, student_id: "demo_student_alex"}, {$set: {medical_notes: "__none_declared__"}});

const SID = "kit_k04_student_mia";
db.students.updateOne({academy_id: A, student_id: SID}, {$setOnInsert: {academy_id: A, student_id: SID,
  first_name: "Mia", last_name: "Kitwell", full_name: "Mia Kitwell", date_of_birth: "2017-06-09",
  skill_level: "Beginner", parent_id: PARENT, parent_user_id: PARENT, waiver_accepted: true, waiver_date: now,
  status: "active", is_deleted: false, created_at: now}, $unset: {medical_notes: ""}}, {upsert: true});
const r = db.enrollments.updateOne({enrollment_id: "kit_k04_enrollment_mia"}, {$setOnInsert: {academy_id: A,
  enrollment_id: "kit_k04_enrollment_mia", session_id: SESSION, student_id: SID, parent_id: PARENT,
  parent_user_id: PARENT, billing_type: "NoCharge", approval_status: "approved", status: "active",
  enrolled_at: now, is_deleted: false}}, {upsert: true});
if (r.upsertedCount) db.sessions.updateOne({academy_id: A, session_id: SESSION}, {$inc: {reserved_seats: 1}});
print("k04: Sam declared (peanut allergy), Alex none declared, Mia Kitwell not answered, all on Junior Beginners");
