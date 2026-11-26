// K16 (part, S25): one cancelled Saturday class date with a reason. The other
// K16 states (time-locked past class, mixed levels, age range) belong to the
// steps that use them (S12, S15). Re-runs keep the same date once chosen.
const A = "acad_demo_academy", now = new Date();
const REASON = "Gym closed for a school event";

let occ = db.session_occurrences.findOne({academy_id: A, kit_cancelled: "k16"});
if (!occ) {
  occ = db.session_occurrences.find({academy_id: A, session_id: "demo_session_sat", status: "scheduled",
    start_at: {$gt: now}, kit: {$exists: false}}).sort({start_at: 1}).limit(1).toArray()[0];
}
if (occ) {
  db.session_occurrences.updateOne({academy_id: A, occurrence_id: occ.occurrence_id}, {
    $set: {status: "cancelled", cancellation_reason: REASON, kit_cancelled: "k16"},
    $min: {cancelled_at: now}});
}
print(`k16: ${occ ? `${occ.occurrence_id} cancelled ("${REASON}")` : "no future Saturday date to cancel"}`);
