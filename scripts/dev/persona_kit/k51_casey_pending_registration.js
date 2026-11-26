// K51 (S51): a PENDING_APPROVAL registration for Mila Quinn into Casey's class
// (kit_session_casey, from k06), so approving it shows her on Casey's skill
// board under Level 1. The walk-in for S51 is added by hand from New family.
// Run k01 and k06 first. Re-running resets the application only, before approval.
const A = "acad_demo_academy", SID = "kit_session_casey", PID = "kit_user_parent_quinn";
const email = "quinn.family@example.com", now = new Date();
if (!db.sessions.findOne({academy_id: A, session_id: SID})) { print("k51: run k06 first"); quit(1); }
db.users.updateOne({user_id: PID}, {$setOnInsert: {user_id: PID, academy_id: A, created_at: now,
  display_name: "Jo Quinn", name: "Jo Quinn", email, normalized_email: email, phone: "555-0171",
  role: "parent", roles: ["parent"], status: "active", global_status: "active", is_active: true,
  stripe_customer_id: null}}, {upsert: true});
db.academy_memberships.updateOne({membership_id: "kit_k51_membership_quinn"}, {$setOnInsert: {
  membership_id: "kit_k51_membership_quinn", academy_id: A, user_id: PID, roles: ["parent"], status: "active",
  invited_by: "demo_user_owner", invited_at: now, accepted_at: now, created_at: now}}, {upsert: true});
db.email_suppressions.updateOne({email}, {$setOnInsert: {email, reason: "hard_bounce", created_at: now}}, {upsert: true});
const at = new Date(now - 36e5);
db.onboarding_applications.updateOne({application_id: "kit_app_mila_casey"}, {
  $setOnInsert: {created_at: at},
  $set: {application_id: "kit_app_mila_casey", academy_id: A, parent_user_id: PID, parent_email: email,
    status: "PENDING_APPROVAL",
    parent_profile: {first_name: "Jo", last_name: "Quinn", email, phone: "555-0171", heard_from: "", referral_code: ""},
    child_profile: {first_name: "Mila", last_name: "Quinn", date_of_birth: "2017-06-09", skill_level: "beginner",
      emergency_contact_name: "Jo Quinn", emergency_contact_phone: "555-0171", medical_notes: "__none_declared__"},
    selected_session_id: SID, waiver_acceptance: null, additional_waiver_acceptances: [],
    stripe_checkout_session_id: null, payment_id: null, superseded_payment_ids: [], student_id: null,
    enrollment_id: null, waitlist_id: null, decision_reason: null, decided_by: null, decided_at: null,
    review_claimed_at: null, review_claim_token: null, expires_at: new Date(+now + 7 * 864e5), updated_at: at}},
  {upsert: true});
print("k51: Mila Quinn pending for Casey's Junior Starters");
