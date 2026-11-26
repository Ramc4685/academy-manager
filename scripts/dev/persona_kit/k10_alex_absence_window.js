// K10 (S17, S18): Alex Demo has an upcoming Saturday class with no absence
// reported yet (so "Report absence" is offered) and one late mark this month.
// Re-running clears only Alex's notice on that one upcoming class.
const A = "acad_demo_academy", now = new Date(), S = "demo_student_alex";
const next = db.session_occurrences.find({academy_id:A, session_id:"demo_session_sat", status:"scheduled", start_at:{$gt:new Date(+now + 48 * 36e5)}})
  .sort({start_at:1}).limit(1).toArray()[0];
if (next) db.absence_notices.deleteMany({academy_id:A, student_id:S, occurrence_id:next.occurrence_id});
const monthStart = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
const past = db.session_occurrences.find({academy_id:A, session_id:"demo_session_sat", start_at:{$gte:monthStart, $lt:now}})
  .sort({start_at:-1}).limit(1).toArray()[0];
if (past) db.attendance.updateOne({academy_id:A, occurrence_id:past.occurrence_id, student_id:S},
  {$setOnInsert:{attendance_id:"kit_att_alex_late"}, $set:{session_id:"demo_session_sat", status:"late", marked_by:"demo_user_coach",
    marked_at:now, client_app_version:"persona-kit", entry_source:"enrollment"}}, {upsert:true});
print(`k10: next class ${next ? next.occurrence_id : "none"}, late mark ${past ? past.occurrence_id : "none"}`);
