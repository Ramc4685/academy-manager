// K19 (S23, partial): the new parent (Rosa Alvarez) has no phone on her
// account, so Profile shows "Missing: your phone number". The broadcast
// audience half of K19 belongs to S69. Re-running clears the phone again.
const rosa = db.users.findOne({normalized_email:"rosa.alvarez@example.com"}) || db.users.findOne({email:"rosa.alvarez@example.com"});
if (!rosa) {
  print("k19: rosa.alvarez@example.com has not signed up yet; sign her up, then re-run k19");
} else {
  db.users.updateOne({user_id:rosa.user_id}, {$set:{phone:null, updated_at:new Date()}});
  print(`k19: ${rosa.user_id} has no phone`);
}
