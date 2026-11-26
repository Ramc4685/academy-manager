// K36 (S36): Junior Beginners reads "9 paying of 11 enrolled". Of k00's
// Saturday kids, Lena and Felix Schmidt go not billed (a scholarship and the
// coach's child), so 11 are enrolled and 9 pay. Run after k00 (k00 re-sets
// billing_type to Standard).
const A = "acad_demo_academy", now = new Date();
[["seed_enrollment_seed_student_lena_schmidt", "scholarship"],
 ["seed_enrollment_seed_student_felix_schmidt", "coach_child"]].forEach(([id, reason]) => {
  const r = db.enrollments.updateOne({academy_id: A, enrollment_id: id, session_id: "demo_session_sat"},
    {$set: {billing_type: "NoCharge", not_billed_reason: reason, not_billed_note: null, updated_at: now}});
  print(`k36: ${id} ${r.matchedCount ? "not billed (" + reason + ")" : "missing; run k00 first"}`);
});
const enrolled = db.enrollments.countDocuments({academy_id: A, session_id: "demo_session_sat", status: "active",
  is_deleted: {$ne: true}});
const notBilled = db.enrollments.countDocuments({academy_id: A, session_id: "demo_session_sat", status: "active",
  is_deleted: {$ne: true}, billing_type: {$in: ["NoCharge", "Waived"]}});
print(`k36: Junior Beginners ${enrolled - notBilled} paying of ${enrolled} enrolled`);
