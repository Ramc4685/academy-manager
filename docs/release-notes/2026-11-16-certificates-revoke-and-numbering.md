# certificates-revoke-and-numbering

PR: TBD

## What changed
The owner can revoke a certificate issued in error: the certificate page has a Revoke button that asks for a reason and confirms first. A revoked certificate stays on file and the admin pages show it with a Revoked label and banner, but the family no longer sees it in the journey, the parent views or the evening wins email, and any share link stops working. The student stays on their level; if they earn the level again, a fresh certificate is issued. Each revoke writes a `certificate.revoked` audit row.

New certificates are numbered per academy from a counter: `BLNO-C-0001` with the invoice prefix, or `C-0001` without one. Existing certificates keep their numbers. A certificate now records its skills, level number and level colour when it is issued, so renaming a skill or recolouring a level later no longer changes certificates already issued (older certificates still read the live curriculum).

In Settings > Curriculum, each level and skill has up and down buttons and a Retire button. A level with players on it cannot be retired, and the editor says why. Waiting level-ups block a level reorder or retire with the server's message. Retiring a skill says how many students were queued for a level-up because of it.

Fixes: a first status write on a skill can no longer overwrite a pass recorded at the same moment; retiring a skill queues only students that skill was holding back (not students already rejected, and nobody when the skill was optional); placing an unknown student, or one from another academy, is refused (404 on the single route, reported as refused in bulk placement). Account deletion now removes the child's name and any share link from their certificates.

## Deploy notes
Migration `0234_certificate_status_share_indexes` runs through the release_command. It sets `status: "issued"` on every existing certificate, then adds two partial unique indexes on `skill_certificates`: `certs_one_issued_per_level_uq` (one issued certificate per student and level) and `certs_share_token_per_academy_uq`.

The migration aborts the deploy, before creating any index, if production already holds two issued certificates for the same student and level; the error names them. Check first with this read-only query in mongosh:

```js
db.skill_certificates.aggregate([
  { $match: { $or: [{ status: "issued" }, { status: { $exists: false } }] } },
  { $group: {
      _id: { academy_id: "$academy_id", student_id: "$student_id", program_id: "$program_id", level_id: "$level_id" },
      count: { $sum: 1 },
      cert_numbers: { $push: "$cert_number" } } },
  { $match: { count: { $gt: 1 } } },
])
```

An empty result means the deploy is safe. For each row returned, set `status: "revoked"` on the extra certificate before deploying.

## Risk / rollback
Revoke only hides a certificate; the row is never deleted, so a mistaken revoke can be undone in the database by setting `status` back to `"issued"` (as long as no newer issued certificate exists for that level). Roll back the code by reverting the merge commit; the old code reads the new fields harmlessly. The indexes can stay, or drop them with `dropIndex` on `certs_one_issued_per_level_uq` and `certs_share_token_per_academy_uq`. Certificate numbers already minted in the new format stay as they are.
