// READ-ONLY. Lists users who ever signed in through a parent magic link.
//
// Background: magic links minted Firebase custom tokens (sign-in provider
// "custom"). The backend now refuses those sessions, but each one's Firebase
// refresh token stays valid until revoked, and the holder (possibly whoever a
// link was forwarded to) can still call Firebase client APIs directly, e.g.
// link a Google or password credential onto the parent's uid. These are the
// uids the owner revokes (`revoke_refresh_tokens`) and whose `provider_data`
// they check for providers the parent did not add.
//
// Run with a read-only user, e.g.
//   mongosh "$MONGO_URL" --quiet scripts/ops/list_magic_link_sessions.js
//
// Only aggregate is used. Nothing here writes.

const rows = db.audit_logs
  .aggregate([
    { $match: { action: "user_logged_in", "metadata.provider": "custom" } },
    {
      $group: {
        _id: "$entity_id",
        academies: { $addToSet: "$academy_id" },
        sessions: { $sum: 1 },
        first_at: { $min: "$created_at" },
        last_at: { $max: "$created_at" },
      },
    },
    {
      $lookup: {
        from: "users",
        let: { u: "$_id" },
        pipeline: [
          { $match: { $expr: { $or: [{ $eq: ["$user_id", "$$u"] }, { $eq: ["$auth_uid", "$$u"] }] } } },
          { $project: { _id: 0, firebase_uid: 1, auth_uid: 1, email: 1 } },
          { $limit: 1 },
        ],
        as: "user",
      },
    },
    { $sort: { last_at: -1 } },
  ])
  .toArray();

for (const r of rows) {
  const u = r.user[0] || {};
  print(
    [
      r._id,
      u.firebase_uid || u.auth_uid || "(no firebase uid)",
      u.email || "",
      r.academies.join("|"),
      r.sessions,
      r.first_at && r.first_at.toISOString(),
      r.last_at && r.last_at.toISOString(),
    ].join("\t")
  );
}
print(`${rows.length} user(s) with a magic-link session`);
