# platform-hardening-l13b

PR: TBD

## What changed
- #849 regression: evening-win and report-card sends (`parent_win_sends`, `parent_report_card_sends`) had a global unique index on `digest_id` again, so one academy's claim id could block another's. Migration 0244 swaps each for a unique `(academy_id, digest_id)` index. A new guard test replays every migration and fails on any unique index on a tenant collection that leaves out `academy_id`, unless it is on a short, reasoned allowlist.
- #983: the webhook handler's invoice and subscription hydration, admin "reconcile Stripe billing" and the billing reconciliation report now read Stripe objects on the academy's connected account. They used to read on the platform account, where direct charges don't exist (`resource_missing`).
- #982: in `multi_academy` mode a dispute on a platform-account charge is now attributed by its PaymentIntent. When exactly one academy holds a platform ledger payment for that PaymentIntent, the dispute goes to that academy. Anything else (no row, two academies, a connected-account row) is quarantined with a reason instead of guessed. Migration 0245 adds the lookup index.
- A newly bootstrapped academy's first user gets the `owner` role alongside `admin`. Re-running bootstrap never grants it to an existing membership.
- Scheduled per-academy jobs skip `suspended` and `cancelled` tenants. The Stripe webhook drain and PaymentIntent reconcile still run for them, so money already in flight settles.
- Tenant data export streams the zip instead of building it in memory. A `tenant.data_export_started` audit row is written before the first byte, and the export is refused if it can't be. `tenant.data_exported` is written after the last byte with the archive SHA-256, size and counts. **The `X-Export-Sha256` response header is gone**: read the SHA from the completion audit row. The frontend never read the header.
- Connect events for an unknown or mismatched account were already quarantined on main. This PR adds a pinning test and documents the event list in `docs/runbooks/stripe-direct-charges.md`.

## Deploy notes
- Migrations 0244 (`win_report_card_send_ids_per_academy`) and 0245 (`ledger_payment_intent_directory_index`) apply through `release_command`. 0244 checks for duplicate `(academy_id, digest_id)` pairs first and aborts the deploy without changing any index if it finds one. It never drops a row.
- Read-only pre-deploy check (`mongosh "$MONGO_URL" --quiet`). Every number should be 0, and `drift` should list only allowlisted indexes:
  ```js
  const out = {};
  for (const c of ["parent_win_sends", "parent_report_card_sends"]) {
    out[c] = {
      dupes: db[c].aggregate([
        { $match: { digest_id: { $gt: "" } } },
        { $group: { _id: { a: "$academy_id", d: "$digest_id" }, n: { $sum: 1 } } },
        { $match: { n: { $gt: 1 } } }, { $count: "n" },
      ]).toArray()[0]?.n ?? 0,
      noAcademy: db[c].countDocuments({ digest_id: { $gt: "" }, academy_id: { $in: [null, ""] } }),
    };
  }
  out.drift = db.getCollectionNames().flatMap((c) =>
    db[c].getIndexes()
      .filter((i) => i.unique && i.name !== "_id_" && !("academy_id" in i.key))
      .map((i) => `${c}.${i.name}`));
  out.academyStatus = db.academies.aggregate([{ $group: { _id: "$status", n: { $sum: 1 } } }]).toArray();
  printjson(out);
  ```
  `noAcademy` rows are not blocked by the new index, but they mean a send was written without a tenant; report them rather than fix them by hand. `academyStatus` shows how many tenants will stop getting scheduled jobs.
- Stripe: the Connect webhook endpoint must be subscribed to `invoice.*`, `customer.subscription.*`, `charge.dispute.*` and the payment events listed in the runbook. No new secret.

## Risk / rollback
- Risk: a dispute that used to be guessed onto an academy now waits in quarantine when attribution is ambiguous. That is intended; the runbook says how to re-drive it.
- Risk: an integration reading `X-Export-Sha256` would break. None is known.
- Rollback: revert the PR. 0244's per-academy indexes are stricter than nothing and safe to leave in place. If the old global index is truly needed, recreate it by hand after checking for cross-academy `digest_id` collisions. The 0245 index is harmless to keep.
