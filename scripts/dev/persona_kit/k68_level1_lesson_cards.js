// K68 (S68): the demo academy's first active program has two lesson cards on
// Level 1, so "What we teach" opens with real teaching content. Original kit
// wording only. Idempotent: fixed kit_* card ids, upserted.
const A = "acad_demo_academy", now = new Date();
const program = db.skill_programs.find({academy_id: A, is_active: {$ne: false}}).sort({created_at: 1}).limit(1).toArray()[0];
const level = program && db.skill_levels.findOne({academy_id: A, program_id: program.program_id, sequence: 1});
if (!level) {
  print("k68: skipped, the demo academy has no active program with a Level 1 (seed the badminton pathway first)");
  quit();
}
const skills = db.skills.find({academy_id: A, level_id: level.level_id}).sort({sequence: 1}).toArray();
const cards = [
  {card_id: "kit_k68_card_grips", lesson_number: 1, title: "Grips",
   goal_summary: "Every child holds the racket with a relaxed forehand and thumb grip.",
   teaching_points: ["Shake hands with the handle", "Loose fingers, firm only at contact"],
   equipment: ["rackets"], safety_notes: ["A racket length between children"],
   activity_summary: "Grip-change relay: switch grips on the coach's call."},
  {card_id: "kit_k68_card_ready", lesson_number: 2, title: "Ready position",
   goal_summary: "Balanced stance with the racket up, ready to move.",
   teaching_points: ["Feet shoulder width", "Racket in front, head height"],
   equipment: ["rackets", "shuttles"], safety_notes: ["Space between pairs"],
   activity_summary: "Mirror drill in pairs."},
];
cards.forEach((card, i) => db.lesson_cards.updateOne({academy_id: A, card_id: card.card_id}, {
  $set: {...card, program_id: program.program_id, level_id: level.level_id,
    skill_ids: skills.slice(0, 2).map((s) => s.skill_id), slug: card.card_id, source: "BWF_SHUTTLE_TIME",
    module_name: "", lesson_range: "", page_hint: null, resource_links: [], content_hash: "",
    display_order: i, is_active: true, updated_at: now, created_by: "kit"},
  $setOnInsert: {created_at: now},
}, {upsert: true}));
print(`k68: ${cards.length} Level 1 lesson cards on ${program.name}`);
