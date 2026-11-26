// K02 (S02): the free Wednesday clinic, and for the new parent (Rosa Alvarez) a
// PENDING_APPROVAL application for Lucia in it plus a CHECKOUT_PENDING one for
// Mateo in the paid Saturday class. Re-running restores exactly this state.
const A = "acad_demo_academy", now = new Date();
db.sessions.updateOne({academy_id:A, session_id:"demo_session_wed"},
  {$set:{title:"Junior Skills Clinic (free)", amount_cents:0, monthly_price:0, capacity:12, status:"scheduled", is_deleted:false}});
const rosa = db.users.findOne({normalized_email:"rosa.alvarez@example.com"}) || db.users.findOne({email:"rosa.alvarez@example.com"});
if (!rosa) {
  print("k02: rosa.alvarez@example.com has not signed up yet; sign her up, then re-run k02");
} else {
  const parent = {first_name:"Rosa", last_name:"Alvarez", email:"rosa.alvarez@example.com", phone:"555-0142", heard_from:"", referral_code:""};
  const child = (first, dob) => ({first_name:first, last_name:"Alvarez", date_of_birth:dob, skill_level:"beginner",
    emergency_contact_name:"Rosa Alvarez", emergency_contact_phone:"555-0142", medical_notes:"__none_declared__"});
  const apps = [
    ["kit_app_lucia_pending", "PENDING_APPROVAL", child("Lucia","2018-04-12"), "demo_session_wed", 2],
    ["kit_app_mateo_checkout", "CHECKOUT_PENDING", child("Mateo","2016-09-03"), "demo_session_sat", 1],
  ];
  apps.forEach(([id, status, kid, sid, hoursAgo]) => {
    const at = new Date(now - hoursAgo * 36e5);
    db.onboarding_applications.updateOne({application_id:id}, {
      $setOnInsert:{created_at:at},
      $set:{application_id:id, academy_id:A, parent_user_id:rosa.user_id, parent_email:"rosa.alvarez@example.com", status,
        parent_profile:parent, child_profile:kid, selected_session_id:sid, waiver_acceptance:null, additional_waiver_acceptances:[],
        stripe_checkout_session_id:null, payment_id:null, superseded_payment_ids:[], student_id:null, enrollment_id:null,
        waitlist_id:null, decision_reason:null, decided_by:null, decided_at:null, review_claimed_at:null, review_claim_token:null,
        expires_at:new Date(+now + 7 * 864e5), updated_at:at}}, {upsert:true});
  });
  print(`k02: open registrations for ${rosa.user_id}: Lucia pending, Mateo checkout`);
}
