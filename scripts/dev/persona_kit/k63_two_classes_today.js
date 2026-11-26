// K63 (S63-S65): two class dates TODAY for the admin Today block. Junior
// Beginners (Sam, Alex and k04's Mia; run k04 first for the health answers)
// started at the top of this hour, so it reads NOW; the Junior Skills Clinic
// (Sam) starts an hour later, so it reads NEXT. Re-running moves both to the
// current hour again, keyed on fixed kit_* occurrence ids.
const A = "acad_demo_academy", now = new Date();
const hour = new Date(now); hour.setUTCMinutes(0, 0, 0);
const HOUR = 60 * 60 * 1000;

[["demo_session_sat", "kit_k63_occ_now", 0], ["demo_session_wed", "kit_k63_occ_next", 1]].forEach(([sid, oid, offset]) => {
  const base = db.session_occurrences.findOne({academy_id: A, session_id: sid, kit: {$exists: false}});
  if (!base) { print(`k63: no ${sid} class date; run the base demo seed`); quit(1); }
  const row = Object.fromEntries(Object.entries(base).filter(([k]) => !["_id", "start_at", "end_at", "status",
    "cancellation_reason", "cancelled_at", "cancelled_by", "substitute_coach_id", "actual_coach_id"].includes(k)));
  const start = new Date(hour.getTime() + offset * HOUR);
  db.session_occurrences.updateOne({academy_id: A, occurrence_id: oid}, {
    $setOnInsert: {...row, occurrence_id: oid, kit: "k63"},
    $set: {start_at: start, end_at: new Date(start.getTime() + HOUR), status: "scheduled"},
    $unset: {cancellation_reason: "", cancelled_at: "", substitute_coach_id: ""}}, {upsert: true});
});
print(`k63: Junior Beginners now (${hour.toISOString()}) and the Junior Skills Clinic an hour later, both today`);
