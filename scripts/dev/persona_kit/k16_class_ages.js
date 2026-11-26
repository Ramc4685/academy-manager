// K16 (S15): an age range and a level on both demo classes, so the coach class
// header and Sessions rows show "Ages 7–13 · Mixed levels". Children's ages come from the dates of birth
// k00 and the base seed already hold (born 2013 to 2019: U9, U11 and U13), and
// the base seed's future dates are classes whose attendance has not opened.
const A = "acad_demo_academy", now = new Date();
const bands = {demo_session_sat: {min_age: 7, max_age: 13}, demo_session_wed: {min_age: 8, max_age: 12}};
const levels = {demo_session_sat: "Mixed levels", demo_session_wed: "Beginner"};
let n = 0;
Object.entries(bands).forEach(([sid, band]) => {
  n += db.sessions.updateOne({academy_id: A, session_id: sid}, {$set: {age_band: band, level: levels[sid], updated_at: now}}).matchedCount;
});
const kids = db.students.countDocuments({academy_id: A, date_of_birth: {$gt: ""}, is_deleted: {$ne: true}});
print(`k16: age range and level on ${n} classes; ${kids} children with a date of birth`);
