// K27 (S27, from K03 + K05): Kiran Patel also in the $80 Saturday class, so the
// re-test can move him to the unpriced "Tuesday Intermediate" (k03) and see
// "$80.00/month to No price set" with a required tick. Run after k03 and k05.
const A = "acad_demo_academy", now = new Date();
const STUDENT = "kit_k05_student_dev", PARENT = "kit_k05_user_parent_patel";
if (!db.students.findOne({academy_id: A, student_id: STUDENT})) throw new Error("k27: run k05 first");
if (!db.sessions.findOne({academy_id: A, session_id: "kit_k03_session_tue"})) throw new Error("k27: run k03 first");
db.enrollments.updateOne({enrollment_id: "kit_k27_enrollment_dev_sat"}, {
  $setOnInsert: {enrolled_at: new Date("2026-10-01T15:00:00Z")},
  // Re-asserted every run: a re-test moves this row, re-running puts it back.
  $set: {academy_id: A, session_id: "demo_session_sat", student_id: STUDENT, parent_id: PARENT,
    parent_user_id: PARENT, billing_type: "Standard", approval_status: "approved", status: "active",
    is_deleted: false, updated_at: now}}, {upsert: true});
print("k27: Kiran Patel on the $80 Saturday class (move him to Tuesday Intermediate)");
