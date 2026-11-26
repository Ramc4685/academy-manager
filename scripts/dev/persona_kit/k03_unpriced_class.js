// K03: "Tuesday Intermediate" with no price (amount_cents null, not 0) and two
// enrolled students, beside the explicitly free Wednesday clinic the base seed
// already has. Used by S10, S27, S42. Run after k00 (it enrolls two k00 kids).
const A = "acad_demo_academy", SID = "kit_k03_session_tue", now = new Date();
const base = db.sessions.findOne({academy_id: A, session_id: "demo_session_sat"});
if (!base) throw new Error("k03: run the base demo seed first (demo_session_sat missing)");

const {_id, ...copy} = base;
db.sessions.updateOne({academy_id: A, session_id: SID}, {
  $setOnInsert: {...copy, session_id: SID, created_at: now},
  // Re-asserted every run: the point of the kit is a class nobody priced.
  $set: {title: "Tuesday Intermediate", name: "Tuesday Intermediate", days_of_week: ["Tue"],
    skill_level: "Intermediate", amount_cents: null, monthly_price: null, status: "scheduled",
    updated_at: now, kit: "k03"}}, {upsert: true});

// Its dates: the Saturday class's dates moved back to the Tuesday before.
let dates = 0;
db.session_occurrences.find({academy_id: A, session_id: "demo_session_sat", kit: {$exists: false}}).forEach(o => {
  const start = new Date(o.start_at.getTime() - 4 * 864e5), end = new Date(o.end_at.getTime() - 4 * 864e5);
  const id = `${SID}:${start.toISOString().slice(0, 10)}:${o.occurrence_id.split(":").slice(2).join(":")}`;
  const {_id: _o, ...occ} = o;
  db.session_occurrences.updateOne({academy_id: A, occurrence_id: id}, {
    $setOnInsert: {...occ, occurrence_id: id, session_id: SID, template_session_id: SID,
      start_at: start, end_at: end, kit: "k03"}}, {upsert: true});
  dates++;
});

let enrolled = 0;
[["seed_student_hana_kim", "seed_user_parent_kim"], ["seed_student_lena_schmidt", "seed_user_parent_schmidt"]]
  .forEach(([student, parent]) => {
    if (!db.students.findOne({academy_id: A, student_id: student})) return;
    const id = `kit_k03_enrollment_${student}`;
    db.enrollments.updateOne({enrollment_id: id}, {
      $setOnInsert: {enrolled_at: new Date(now - 14 * 864e5)},
      $set: {academy_id: A, enrollment_id: id, session_id: SID, student_id: student, parent_id: parent,
        parent_user_id: parent, billing_type: "Standard", approval_status: "approved", status: "active",
        is_deleted: false}}, {upsert: true});
    enrolled++;
  });
print(`k03: ${SID} unpriced, ${dates} dates, ${enrolled} enrolled${enrolled < 2 ? " (run k00 first)" : ""}`);
