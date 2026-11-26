// K15: payslips. Demo Coach has an approved payout period for last month and
// a draft one for this month, so Session economics shows a real margin for
// last month and "Needs payroll" for this one. Casey Newcoach is named as the
// Wed clinic's assistant (session only, so no held class owes Casey pay).
// Used by S35, S59, S60. Run after k01.
const A = "acad_demo_academy", COACH = "demo_user_coach", TZ = "America/Chicago", now = new Date();

function chicago(y, m, d) {
  let t = Date.UTC(y, m - 1, d);
  for (let i = 0; i < 2; i++) {
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", {timeZone: TZ, hourCycle: "h23",
      year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric"})
      .formatToParts(new Date(t)).map(x => [x.type, Number(x.value)]));
    t += Date.UTC(y, m - 1, d) - Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute);
  }
  return new Date(t);
}
const local = Object.fromEntries(new Intl.DateTimeFormat("en-US", {timeZone: TZ, year: "numeric", month: "numeric"})
  .formatToParts(now).map(x => [x.type, Number(x.value)]));
const next = (y, m) => (m === 12 ? [y + 1, 1] : [y, m + 1]);
const [ly, lm] = local.month === 1 ? [local.year - 1, 12] : [local.year, local.month - 1];
const months = [[ly, lm, "approved"], [local.year, local.month, "draft"]];

months.forEach(([y, m, status]) => {
  const start = chicago(y, m, 1), [ny, nm] = next(y, m), end = chicago(ny, nm, 1);
  const tag = `${y}_${String(m).padStart(2, "0")}`, token = `kit_k15_${tag}`;
  // Keyed on the coach's month window (the generator's unique key), so a
  // period the tester already generated is reused, not duplicated.
  const key = {academy_id: A, coach_id: COACH, period_start: start, period_end: end};
  const held = db.session_occurrences.find({academy_id: A, start_at: {$gte: start, $lt: end},
    status: {$ne: "cancelled"}, is_payable: {$ne: false}, end_at: {$lt: now},
    $or: [{actual_coach_id: COACH}, {actual_coach_id: null, scheduled_coach_id: COACH}]}).toArray();
  const fields = {period_id: `kit_k15_period_${tag}`, ...key, currency: "USD", revenue_basis: "invoiced",
    generated_at: now, version: 0};
  if (status === "approved") {
    // Last month is final: approved, no unresolved rows, one $30 line per held class.
    db.payout_periods.updateOne(key, {$setOnInsert: fields, $set: {status: "approved", approved_at: now,
      total_minor: 3000 * held.length, lines_version: token, unpaid_occurrence_ids: [],
      unpaid_occurrences: [], payout_warnings: []}}, {upsert: true});
  } else {
    db.payout_periods.updateOne(key, {$setOnInsert: {...fields, status: "draft", total_minor: 0,
      lines_version: token, unpaid_occurrence_ids: [], unpaid_occurrences: [], payout_warnings: []}},
      {upsert: true});
  }
  const period = db.payout_periods.findOne(key);
  if (period.lines_version === token) {
    held.forEach(o => db.payout_period_lines.updateOne(
      {academy_id: A, period_id: period.period_id, lines_version: token, occurrence_id: o.occurrence_id},
      {$set: {coach_id: COACH, basis: "per_session", minutes: "60", amount_minor: status === "approved" ? 3000 : 0,
        currency: "USD", rate_id: null, percent_bps: null, expected_revenue_minor: null,
        original_amount_minor: null, adjustment_reason: null}}, {upsert: true}));
  }
  print(`k15: ${y}-${String(m).padStart(2, "0")} Demo Coach period ${period.status}, ${held.length} held classes`);
});

db.sessions.updateOne({academy_id: A, session_id: "demo_session_wed"},
  {$addToSet: {assistant_coach_ids: "demo_user_coach2"}});
