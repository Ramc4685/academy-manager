// K05: Kiran Patel (not "Dev": the base seed already has a Dev Patel) moved
// from the Saturday class to the Wednesday clinic (a
// transfer keeps the enrollment and changes its class), with an Absent mark on
// Sat Nov 21 left behind in the old class. Used by S07, S25, S27.
// Not covered here: the past one-off date on his schedule (S07/S27 add it).
const A = "acad_demo_academy", now = new Date();
const PARENT = "kit_k05_user_parent_patel", STUDENT = "kit_k05_student_dev";
const OCC = "demo_session_sat:2026-11-21:09:00";

db.users.updateOne({user_id: PARENT}, {
  $setOnInsert: {user_id: PARENT, created_at: now},
  $set: {academy_id: A, display_name: "Priya Patel", name: "Priya Patel", email: "patel.family@example.com",
    normalized_email: "patel.family@example.com", phone: "555-0150", role: "parent", roles: ["parent"],
    global_status: "active", status: "active", is_active: true, stripe_customer_id: null, updated_at: now}},
  {upsert: true});
db.academy_memberships.updateOne({academy_id: A, user_id: PARENT}, {
  $setOnInsert: {membership_id: "kit_k05_membership_patel", created_at: now, accepted_at: now},
  $set: {roles: ["parent"], status: "active", updated_at: now}}, {upsert: true});
db.students.updateOne({student_id: STUDENT}, {
  $setOnInsert: {created_at: now},
  $set: {academy_id: A, first_name: "Kiran", last_name: "Patel", full_name: "Kiran Patel", date_of_birth: "2015-03-14",
    parent_id: PARENT, parent_user_id: PARENT, emergency_contact_name: "Priya Patel",
    emergency_contact_phone: "555-0150", medical_notes: "__none_declared__", skill_level: "Beginner",
    waiver_accepted: true, waiver_date: now, status: "active", is_deleted: false}}, {upsert: true});
// The transfer: the enrollment now points at the Wednesday class.
db.enrollments.updateOne({enrollment_id: "kit_k05_enrollment_dev"}, {
  $setOnInsert: {enrolled_at: new Date("2026-10-01T15:00:00Z")},
  $set: {academy_id: A, session_id: "demo_session_wed", student_id: STUDENT, parent_id: PARENT,
    parent_user_id: PARENT, billing_type: "Standard", approval_status: "approved", status: "active",
    is_deleted: false, updated_at: now}}, {upsert: true});

const occ = db.session_occurrences.findOne({academy_id: A, occurrence_id: OCC});
if (occ) {
  db.attendance.updateOne({academy_id: A, occurrence_id: OCC, student_id: STUDENT}, {
    $setOnInsert: {attendance_id: "kit_k05_att_dev_1121"},
    $set: {session_id: "demo_session_sat", marked_by: "demo_user_coach", marked_at: occ.end_at,
      status: "absent", client_app_version: "persona-kit", entry_source: "enrollment"}}, {upsert: true});
}
print(`k05: Kiran Patel on the Wednesday clinic; Sat Nov 21 mark ${occ ? "set" : "skipped (no such date in this DB)"}`);
