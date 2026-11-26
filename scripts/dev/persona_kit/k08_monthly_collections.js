// K08: this month's collections and monthly-billing mix on the Saturday class.
// Seven kit families, one child each:
//   unbilled1, unbilled2  enrolled, no invoice yet this month (Generate monthly bills them)
//   paused                 enrollment paused (skipped)
//   free                   billing_type NoCharge (skipped)
//   overdue                open invoice, emailed, due 5 days ago
//   unsent                 open invoice, never emailed, due in 7 days  (S30: Send invoice)
//   emailed                open invoice, emailed, due in 7 days        (S30: Send reminder)
// Used by S30, S33, S34, S41. The default local stack runs with email delivery off, so
// Send invoice on `unsent` emails nothing: the row reads "Invoice was not emailed", the
// invoice stays not_sent, and the proof is the backend.log line "send_invoice: email port
// not configured" (not a dues-reminder line). Real sends need staging/prod email config.
const A = "acad_demo_academy", SESSION = "demo_session_sat", TZ = "America/Chicago", now = new Date();
const DAY = 864e5;
const local = Object.fromEntries(new Intl.DateTimeFormat("en-US", {timeZone: TZ, year: "numeric", month: "numeric"})
  .formatToParts(now).map(x => [x.type, Number(x.value)]));
const period = `${local.year}-${String(local.month).padStart(2, "0")}`;
const dateOnly = ms => new Date(new Date(ms).toISOString().slice(0, 10) + "T00:00:00Z");

const fams = [
  // [slug, parent name, child first name, enrollment status, billing_type, invoice]
  ["unbilled1", "Nora Lindqvist", "Ivy", "active", "Standard", null],
  ["unbilled2", "Omar Haddad", "Sami", "active", "Standard", null],
  ["paused", "Greta Moss", "Finn", "paused", "Standard", null],
  ["free", "Paulo Reyes", "Luca", "active", "NoCharge", null],
  ["overdue", "Wendy Clarke", "Theo", "active", "Standard", {due: -5, sent: true}],
  ["unsent", "Hiro Tanaka", "Yuki", "active", "Standard", {due: 7, sent: false}],
  ["emailed", "Maya Brooks", "Ella", "active", "Standard", {due: 7, sent: true}],
];

let invoices = 0;
fams.forEach(([slug, parent, child, status, billingType, inv], i) => {
  const last = parent.split(" ")[1], pid = `kit_k08_parent_${slug}`, sid = `kit_k08_student_${slug}`;
  const eid = `kit_k08_enrollment_${slug}`, email = `k08.${slug}@example.com`;
  db.users.updateOne({user_id: pid}, {$set: {user_id: pid, academy_id: A, display_name: parent, name: parent,
    email, normalized_email: email, phone: `555-018${i}`, role: "parent", roles: ["parent"], status: "active",
    global_status: "active", is_active: true, stripe_customer_id: null, updated_at: now},
    $setOnInsert: {created_at: now}}, {upsert: true});
  db.academy_memberships.updateOne({membership_id: `kit_k08_membership_${slug}`}, {$set: {membership_id:
    `kit_k08_membership_${slug}`, academy_id: A, user_id: pid, roles: ["parent"], status: "active",
    invited_by: "demo_user_owner", invited_at: now, accepted_at: now, updated_at: now},
    $setOnInsert: {created_at: now}}, {upsert: true});
  db.students.updateOne({student_id: sid}, {$set: {academy_id: A, student_id: sid, first_name: child, last_name: last,
    full_name: `${child} ${last}`, date_of_birth: "2016-04-0" + (i + 1), emergency_contact_name: parent,
    emergency_contact_phone: `555-018${i}`, medical_notes: "__none_declared__", skill_level: "Beginner",
    parent_id: pid, parent_user_id: pid, waiver_accepted: true, waiver_date: now, status: "active", is_deleted: false},
    $setOnInsert: {created_at: now}}, {upsert: true});
  db.enrollments.updateOne({enrollment_id: eid}, {$set: {academy_id: A, enrollment_id: eid, session_id: SESSION,
    student_id: sid, parent_id: pid, parent_user_id: pid, billing_type: billingType, approval_status: "approved",
    status, is_deleted: false}, $setOnInsert: {enrolled_at: new Date(now - 40 * DAY), created_at: new Date(now - 40 * DAY)}},
    {upsert: true});
  if (!inv) return;
  const invId = `kit_k08_invoice_${slug}_${period.replace("-", "_")}`, sentAt = inv.sent ? new Date(now - 3 * DAY) : null;
  db.invoices.updateOne({invoice_id: invId}, {$set: {academy_id: A, invoice_id: invId,
    invoice_number: `KIT-${period}-K08-${slug.toUpperCase()}`, parent_id: pid, student_id: sid, enrollment_id: eid,
    session_id: SESSION, period, status: "open", subtotal_cents: 8000, discount_cents: 0, total_cents: 8000,
    balance_due_cents: 8000, refunded_cents: 0, currency: "usd", due_date: dateOnly(+now + inv.due * DAY),
    delivery_status: inv.sent ? "sent" : "not_sent", sent_at: sentAt, last_sent_at: sentAt, finalized_at: new Date(now - 4 * DAY),
    version: 0, updated_at: now}, $setOnInsert: {created_at: new Date(now - 4 * DAY)}}, {upsert: true});
  db.invoice_lines.updateOne({line_id: `kit_k08_line_${slug}_${period.replace("-", "_")}`}, {$set: {academy_id: A,
    line_id: `kit_k08_line_${slug}_${period.replace("-", "_")}`, invoice_id: invId, line_type: "tuition",
    description: `Monthly tuition ${period}`, amount_cents: 8000, quantity: 1, unit_amount_cents: 8000},
    $setOnInsert: {created_at: now}}, {upsert: true});
  invoices++;
});

print(`k08: ${period} ${fams.length} kit families, ${invoices} kit invoices (overdue, unsent, emailed); ` +
  `unbilled1/unbilled2 have no ${period} invoice until Generate monthly runs`);
