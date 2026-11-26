// K44 (S44, S54): Casey Newcoach is on no part of "Tuesday Intermediate" (k03)
// so the admin can assign her, and the class has a future date left to cancel.
// Her email notifications stay switched on so S54's assignment email is sent
// to the local mail stub. Run after k01 and k03.
const A = "acad_demo_academy", SID = "kit_k03_session_tue", CASEY = "demo_user_coach2", now = new Date();
if (!db.sessions.findOne({academy_id: A, session_id: SID})) throw new Error("k44: run k03 first");
if (!db.users.findOne({user_id: CASEY})) throw new Error("k44: run k01 first (Casey missing)");

db.sessions.updateOne({academy_id: A, session_id: SID}, {$pull: {assistant_coach_ids: CASEY}});
db.session_occurrences.updateMany({academy_id: A, session_id: SID, start_at: {$gt: now}},
  {$pull: {assistant_coach_ids: CASEY}});
const lead = db.sessions.findOne({academy_id: A, session_id: SID}).coach_id;
if (lead === CASEY) {
  db.sessions.updateOne({academy_id: A, session_id: SID}, {$set: {coach_id: "demo_user_coach", updated_at: now}});
}
db.email_preferences.updateOne({academy_id: A, user_id: CASEY},
  {$set: {notifications_opted_out: false}});
const spare = db.session_occurrences.countDocuments({academy_id: A, session_id: SID, status: "scheduled",
  start_at: {$gt: now}});
print(`k44: Casey off ${SID}; ${spare} future dates left to cancel`);
