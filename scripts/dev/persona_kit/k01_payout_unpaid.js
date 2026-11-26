// K01: payouts. Last month, Demo Coach has one held Saturday class before any
// pay rate (unpaid, no_rate_configured) and one after a 50% percent-of-revenue
// rate starts (paid from the month's invoiced tuition). Casey Newcoach is an
// active coach with no held classes last month. Used by S01 and S32.
const A = "acad_demo_academy", COACH = "demo_user_coach", SESSION = "demo_session_sat";
const TZ = "America/Chicago", now = new Date();

// Chicago wall time -> UTC Date (two passes settle DST).
function chicago(y, m, d, hh, mm) {
  let t = Date.UTC(y, m - 1, d, hh, mm);
  for (let i = 0; i < 2; i++) {
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", {timeZone: TZ, hourCycle: "h23",
      year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric"})
      .formatToParts(new Date(t)).map(x => [x.type, Number(x.value)]));
    t += Date.UTC(y, m - 1, d, hh, mm) - Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute);
  }
  return new Date(t);
}
const local = Object.fromEntries(new Intl.DateTimeFormat("en-US", {timeZone: TZ, year: "numeric", month: "numeric"})
  .formatToParts(now).map(x => [x.type, Number(x.value)]));
const [y, m] = local.month === 1 ? [local.year - 1, 12] : [local.year, local.month - 1];
const period = `${y}-${String(m).padStart(2, "0")}`;
const firstSat = 1 + ((6 - new Date(Date.UTC(y, m - 1, 1)).getUTCDay() + 7) % 7);
const pad = n => String(n).padStart(2, "0");

// Two held classes: first Saturday (before the rate) and the one after it.
[firstSat, firstSat + 7].forEach(day => {
  const id = `${SESSION}:${y}-${pad(m)}-${pad(day)}:09:00`;
  db.session_occurrences.updateOne({academy_id: A, occurrence_id: id}, {
    $setOnInsert: {occurrence_id: id, academy_id: A, session_id: SESSION, template_session_id: SESSION,
      start_at: chicago(y, m, day, 9, 0), end_at: chicago(y, m, day, 10, 0), scheduled_coach_id: COACH,
      is_billable: true, is_payable: true, kit: "k01"},
    $set: {status: "completed"}}, {upsert: true});
});

// 50% of revenue from the Sunday after the first Saturday (a later rate still wins).
const rateId = `kit_k01_rate_${period.replace("-", "_")}`;
db.coach_rates.updateOne({rate_id: rateId}, {$set: {rate_id: rateId, academy_id: A, coach_id: COACH,
  billing_unit: "percent_of_revenue", amount_minor: 0, percent_bps: 5000, currency: "USD",
  effective_from: chicago(y, m, firstSat + 1, 0, 0), effective_until: null, status: "active"}}, {upsert: true});

// A percent rate needs invoiced tuition for the class-month; add one only if none is counted.
const invId = `kit_k01_invoice_${period.replace("-", "_")}`;
const counted = db.invoices.countDocuments({academy_id: A, session_id: SESSION, period,
  status: {$nin: ["draft", "void"]}, is_deleted: {$ne: true}, invoice_id: {$ne: invId}});
if (!counted) {
  const at = chicago(y, m, 1, 10, 0);
  db.invoices.updateOne({invoice_id: invId}, {$set: {academy_id: A, invoice_id: invId,
    invoice_number: `KIT-${period}-K01`, parent_id: "demo_user_parent", student_id: "demo_student_sam",
    enrollment_id: "demo_enrollment_sam_sat", session_id: SESSION, period, status: "paid",
    subtotal_cents: 8000, discount_cents: 0, total_cents: 8000, balance_due_cents: 0, refunded_cents: 0,
    currency: "usd", due_date: at, delivery_status: "not_sent", finalized_at: at, version: 0,
    created_at: at, updated_at: at}}, {upsert: true});
}

// Casey: keep the persona tester's existing account id; only force it active.
const casey = "demo_user_coach2";
db.users.updateOne({user_id: casey}, {
  $setOnInsert: {user_id: casey, academy_id: A, created_at: now, display_name: "Casey Newcoach",
    name: "Casey Newcoach", email: "demo.coach2@example.com", normalized_email: "demo.coach2@example.com",
    phone: "555-0109", role: "coach", roles: ["coach"], stripe_customer_id: null},
  $set: {status: "active", global_status: "active", is_active: true}}, {upsert: true});
db.academy_memberships.updateOne({user_id: casey, academy_id: A}, {
  $setOnInsert: {membership_id: "kit_k01_membership_casey", academy_id: A, user_id: casey, roles: ["coach"],
    invited_by: "demo_user_owner", invited_at: now, accepted_at: now, created_at: now},
  $set: {status: "active", updated_at: now}}, {upsert: true});
const caseyHeld = db.session_occurrences.countDocuments({academy_id: A, scheduled_coach_id: casey,
  start_at: {$gte: chicago(y, m, 1, 0, 0), $lt: m === 12 ? chicago(y + 1, 1, 1, 0, 0) : chicago(y, m + 1, 1, 0, 0)}});

print(`k01: ${period} Demo Coach classes on ${pad(firstSat)} (unpaid) and ${pad(firstSat + 7)} (50%); ` +
  `kit invoice ${counted ? "not needed" : "upserted"}; Casey held classes in ${period}: ${caseyHeld}`);
