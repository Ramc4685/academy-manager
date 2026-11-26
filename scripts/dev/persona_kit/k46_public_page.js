// K46 (S46): publish the demo academy's public page with an address and a refund
// link, and list both demo classes on it with their level and ages. Kept here,
// not in seed_demo_academy.py, because that seed may run against a real demo tenant.
const A = "acad_demo_academy", now = new Date();
const a = db.academies.updateOne({academy_id: A}, {$set: {
  address: "100 Example Gym Rd, Normal IL",
  refund_policy_url: "https://example.com/demo-academy/refunds",
  "public_page.published": true,
  updated_at: now,
}}).matchedCount;
let n = 0;
["demo_session_sat", "demo_session_wed"].forEach((sid) => {
  n += db.sessions.updateOne({academy_id: A, session_id: sid}, {$set: {
    published: true, level: "Beginner", age_band: {min_age: 8, max_age: 12}, updated_at: now,
  }}).matchedCount;
});
print(`k46: public page published on ${a} academy; ${n} classes listed`);
