// K06: Casey Newcoach (k01) leads her own class, "Casey's Junior Starters", a
// copy of the Wednesday clinic, with Tej Walkin and two more active children
// enrolled and none of them placed on a level. Used by S13 and S52.
// Run k01 first (it creates Casey). Note: this gives Casey a class, so leave it
// out when re-testing her empty first day (S16).
const A = "acad_demo_academy", CASEY = "demo_user_coach2", BASE = "demo_session_wed";
const SID = "kit_session_casey", now = new Date();

if (!db.users.findOne({user_id: CASEY})) { print("k06: Casey is missing; run k01 first"); quit(1); }
const base = db.sessions.findOne({academy_id: A, session_id: BASE});
if (!base) { print("k06: the demo Wednesday class is missing; run the base demo seed"); quit(1); }

const {_id, ...tmpl} = base;
db.sessions.updateOne({academy_id: A, session_id: SID}, {$setOnInsert: {...tmpl, session_id: SID,
  name: "Casey's Junior Starters", title: "Casey's Junior Starters", reserved_seats: 0, created_at: now},
  $set: {coach_id: CASEY, assistant_coach_ids: [], updated_at: now}}, {upsert: true});

// Same dates as the Wednesday clinic, keyed on the new session id.
let occ = 0;
db.session_occurrences.find({academy_id: A, session_id: BASE, kit: {$exists: false}}).forEach(o => {
  const {_id: _oid, ...row} = o;
  const id = o.occurrence_id.replace(BASE, SID);
  db.session_occurrences.updateOne({academy_id: A, occurrence_id: id}, {$setOnInsert: {...row, occurrence_id: id,
    session_id: SID, template_session_id: SID, kit: "k06"}, $set: {scheduled_coach_id: CASEY}}, {upsert: true});
  occ++;
});

const kids = [["Tej", "Walkin", "2017-03-14"], ["Noor", "Haddad", "2016-08-02"], ["Owen", "Pryce", "2018-01-27"]];
let added = 0;
kids.forEach(([first, last, dob], i) => {
  const slug = `${first}_${last}`.toLowerCase(), sid = `kit_student_${slug}`, pid = `kit_user_parent_${last.toLowerCase()}`;
  const email = `${last.toLowerCase()}.family@example.com`;
  db.users.updateOne({user_id: pid}, {$setOnInsert: {user_id: pid, academy_id: A, created_at: now,
    display_name: `Sam ${last}`, name: `Sam ${last}`, email, normalized_email: email, phone: `555-016${i}`,
    role: "parent", roles: ["parent"], status: "active", global_status: "active", is_active: true,
    stripe_customer_id: null}}, {upsert: true});
  db.academy_memberships.updateOne({membership_id: `kit_k06_membership_${last.toLowerCase()}`}, {$setOnInsert: {
    membership_id: `kit_k06_membership_${last.toLowerCase()}`, academy_id: A, user_id: pid, roles: ["parent"],
    status: "active", invited_by: "demo_user_owner", invited_at: now, accepted_at: now, created_at: now}}, {upsert: true});
  db.email_suppressions.updateOne({email}, {$setOnInsert: {email, reason: "hard_bounce", created_at: now}}, {upsert: true});
  db.students.updateOne({student_id: sid}, {$setOnInsert: {academy_id: A, student_id: sid, first_name: first,
    last_name: last, full_name: `${first} ${last}`, date_of_birth: dob, emergency_contact_name: `Sam ${last}`,
    emergency_contact_phone: `555-016${i}`, medical_notes: "__none_declared__", skill_level: "Beginner",
    parent_id: pid, parent_user_id: pid, waiver_accepted: true, waiver_date: now, status: "active",
    is_deleted: false, created_at: now}}, {upsert: true});
  const r = db.enrollments.updateOne({enrollment_id: `kit_enrollment_${slug}`}, {$setOnInsert: {academy_id: A,
    enrollment_id: `kit_enrollment_${slug}`, session_id: SID, student_id: sid, parent_id: pid, parent_user_id: pid,
    billing_type: "Standard", approval_status: "approved", status: "active", enrolled_at: now, is_deleted: false}},
    {upsert: true});
  if (r.upsertedCount) { db.sessions.updateOne({academy_id: A, session_id: SID}, {$inc: {reserved_seats: 1}}); added++; }
  // Not placed: remove any level a previous run or the app gave them.
  db.student_level_progress.deleteMany({academy_id: A, student_id: sid});
});
print(`k06: ${SID} led by Casey, ${occ} dates, ${added} new enrollments; Tej, Noor and Owen unplaced`);
