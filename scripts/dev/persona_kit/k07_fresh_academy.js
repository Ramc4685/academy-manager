// K07: a second, just-bootstrapped local academy whose only required live
// waiver is the untouched starter text (S09, S47, S56). Served at
// fresh.localhost; owner fresh.owner@example.com. The Firebase login is not
// made here (mongosh cannot reach the auth emulator): create that email in the
// emulator UI, then sign in; auth links the account by email.
const A = "acad_fresh_local", SLUG = "fresh", DOMAIN = "fresh.localhost";
const OWNER = "kit_k07_user_owner", EMAIL = "fresh.owner@example.com", now = new Date();
// Must stay byte-equal to DEFAULT_WAIVER_BODY in bootstrap_academy.py.
const STARTER = "Default academy participation waiver. Replace this template before " +
  "accepting student registrations.";

db.academies.updateOne({academy_id: A}, {
  $setOnInsert: {academy_id: A, created_at: now},
  $set: {name: "Fresh Local Academy", display_name: "Fresh Local Academy", slug: SLUG,
    primary_domain: DOMAIN, status: "active", owner_email: EMAIL, updated_at: now}}, {upsert: true});
db.academy_domains.updateOne({domain: DOMAIN}, {
  $setOnInsert: {created_at: now},
  $set: {academy_id: A, domain: DOMAIN, slug: SLUG, status: "verified", kind: "tenant_subdomain"}},
  {upsert: true});
db.users.updateOne({user_id: OWNER}, {
  $setOnInsert: {user_id: OWNER, created_at: now},
  $set: {email: EMAIL, normalized_email: EMAIL, display_name: "Fran Fresh", name: "Fran Fresh",
    phone: "555-0170", academy_id: A, role: "owner", roles: ["admin", "owner"],
    global_status: "active", status: "active", is_active: true, updated_at: now}}, {upsert: true});
db.academy_memberships.updateOne({academy_id: A, user_id: OWNER}, {
  $setOnInsert: {membership_id: "kit_k07_membership_owner", created_at: now, accepted_at: now},
  $set: {roles: ["admin", "owner"], status: "active", updated_at: now}}, {upsert: true});
// The starter waiver exactly as bootstrap writes it: required for all families.
db.waiver_templates.updateOne({waiver_template_id: "kit_k07_waiver_starter"}, {
  $setOnInsert: {created_at: now, effective_from: now, published_at: now, assigned_at: now},
  $set: {academy_id: A, name: "Default participation waiver", title: "Default participation waiver",
    version: "1", body: STARTER, status: "active", assigned_to_registration: true, updated_at: now}},
  {upsert: true});

const live = db.waiver_templates.countDocuments({academy_id: A, status: "active"});
print(`k07: ${A} at ${DOMAIN}, owner ${EMAIL}; live waivers: ${live} (starter only expected)`);
