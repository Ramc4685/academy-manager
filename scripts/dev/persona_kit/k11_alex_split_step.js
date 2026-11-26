// K11 (S18, partial): Alex Demo is working on "Split step" (PRACTICING), with
// one coach note ticked shared before parents could see skill notes (no
// shared_at, so it stays off the parent feed until re-shared; S53) and one
// private note. The pass itself is recorded in
// the coach app during the re-test (Today -> class -> mark the pass), so it
// goes through the real pass pipeline instead of hand-made attempt rows.
const A = "acad_demo_academy", now = new Date(), S = "demo_student_alex";
const skill = db.skills.findOne({academy_id:A, name:/^split step$/i}) || db.skills.findOne({name:/^split step$/i});
if (!skill) {
  print("k11: no 'Split step' skill in the demo curriculum; nothing seeded");
} else {
  const level = db.skill_levels.findOne({level_id:skill.level_id}) || {};
  db.student_skill_progress.updateOne({skill_progress_id:"kit_sp_alex_split_step"}, {
    $setOnInsert:{introduced_at:new Date(+now - 14 * 864e5)},
    $set:{skill_progress_id:"kit_sp_alex_split_step", academy_id:A, student_id:S, skill_id:skill.skill_id,
      level_id:skill.level_id, program_id:level.program_id || skill.program_id || null, status:"PRACTICING",
      coach_note:null, silent:false, tries:0, last_updated_at:now, last_updated_by:"demo_user_coach"}}, {upsert:true});
  [["kit_note_alex_shared", "shared", "Split step is getting quicker; keep the small hop before each shot.", 4],
   ["kit_note_alex_private", "private", "Start the split step earlier on returns; check again next week.", 2]].forEach(([id, vis, body, daysAgo]) =>
    db.coach_skill_notes.updateOne({note_id:id}, {$set:{note_id:id, academy_id:A, student_id:S, skill_id:skill.skill_id,
      coach_id:"demo_user_coach", session_id:"demo_session_sat", body, visibility:vis, created_at:new Date(+now - daysAgo * 864e5)}, $unset:{shared_at:""}}, {upsert:true}));
  print(`k11: Alex working on ${skill.name} (${skill.skill_id})`);
}
