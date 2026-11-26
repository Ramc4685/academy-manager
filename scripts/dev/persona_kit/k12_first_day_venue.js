// K12 (S16, S45): venue facts and what to bring on both demo classes (address, parking, arrive-early
// minutes) so the coach class page shows where to go, and an academy phone and
// email so a coach's empty first day says who to call. Casey Newcoach has no
// class unless k06 ran: leave k06 out to see her first-day empty state.
const A = "acad_demo_academy", now = new Date();
const venue = {
  demo_session_sat: {venue_address: "100 Example Gym Rd, Normal IL", parking_notes: "Park in the north lot; the side door opens at 8:45", arrival_minutes_before: 15, what_to_bring: "Water bottle, sneakers with non-marking soles, comfortable sports clothes"},
  demo_session_wed: {venue_address: "200 Sample School Ave, Normal IL", parking_notes: "Visitor spaces by the gym entrance", arrival_minutes_before: 10, what_to_bring: "Water bottle and indoor shoes; rackets are provided"},
};
let n = 0;
Object.entries(venue).forEach(([sid, v]) => {
  n += db.sessions.updateOne({academy_id: A, session_id: sid}, {$set: {...v, updated_at: now}}).matchedCount;
});
const a = db.academies.updateOne({academy_id: A}, {$set: {contact_phone: "555-0142", contact_email: "office@example.com", updated_at: now}}).matchedCount;
print(`k12: venue on ${n} classes; academy contact set on ${a} academy`);
