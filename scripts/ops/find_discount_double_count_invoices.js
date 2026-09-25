// READ-ONLY. Finds ledger invoices whose tuition discount was taken off twice.
//
// Background: the monthly generator writes a discounted month as a gross
// tuition line, a negative `tuition_discount` line, AND the same amount in the
// header's `discount_cents`. Before the fix, `recompute_totals` summed the
// lines (already net of the discount line) and subtracted `discount_cents`
// again. Any recompute did it: an ACH autopay discount line (first attempt or
// retry), the hourly late-fee pass, an admin-added line, an enrollment-move
// line, or `create_invoice` back-filling a missing line.
//
// Run with a read-only user, e.g.
//   mongosh "$MONGO_URL" --quiet scripts/ops/find_discount_double_count_invoices.js
// Optional: set ACADEMY_ID below to one academy (default: every academy).
//
// Only aggregate/find are used. Nothing here writes.

const ACADEMY_ID = null; // e.g. "acad_blno_badminton"

const match = {
  status: { $ne: "void" },
  is_deleted: { $ne: true },
  discount_cents: { $gt: 0 },
};
if (ACADEMY_ID) match.academy_id = ACADEMY_ID;

const rows = db.invoices
  .aggregate([
    { $match: match },
    {
      $lookup: {
        from: "invoice_lines",
        let: { a: "$academy_id", i: "$invoice_id" },
        pipeline: [
          { $match: { $expr: { $and: [{ $eq: ["$academy_id", "$$a"] }, { $eq: ["$invoice_id", "$$i"] }] } } },
          { $project: { _id: 0, line_type: 1, source_type: 1, source_id: 1, amount_cents: 1, description: 1 } },
        ],
        as: "lines",
      },
    },
    {
      $addFields: {
        line_sum_cents: { $sum: "$lines.amount_cents" },
        discount_line_cents: {
          $sum: {
            $map: {
              input: "$lines",
              as: "l",
              in: {
                $cond: [
                  { $and: [{ $eq: ["$$l.source_type", "tuition_discount"] }, { $lt: ["$$l.amount_cents", 0] }] },
                  { $multiply: ["$$l.amount_cents", -1] },
                  0,
                ],
              },
            },
          },
        },
        // The legacy payment id the generator used as the credit key.
        tuition_source_id: {
          $first: {
            $map: {
              input: { $filter: { input: "$lines", as: "l", cond: { $eq: ["$$l.line_type", "tuition"] } } },
              as: "t",
              in: "$$t.source_id",
            },
          },
        },
      },
    },
    // Only the generator shape: a discount line AND the header discount.
    { $match: { discount_line_cents: { $gt: 0 } } },
    {
      $lookup: {
        from: "credit_applications",
        let: { a: "$academy_id", k: "$tuition_source_id" },
        pipeline: [
          { $match: { $expr: { $and: [{ $eq: ["$academy_id", "$$a"] }, { $eq: ["$invoice_id", "$$k"] }] } } },
          { $match: { reversed_at: null } },
          { $group: { _id: null, cents: { $sum: "$amount_cents" } } },
        ],
        as: "credit",
      },
    },
    {
      $lookup: {
        from: "payment_allocations",
        let: { a: "$academy_id", i: "$invoice_id" },
        pipeline: [
          { $match: { $expr: { $and: [{ $eq: ["$academy_id", "$$a"] }, { $eq: ["$invoice_id", "$$i"] }] } } },
          { $group: { _id: null, cents: { $sum: "$amount_cents" } } },
        ],
        as: "alloc",
      },
    },
    {
      $addFields: {
        // Since #971 applied credit is an `account_credit` line, already in
        // line_sum_cents; only an older header-only credit is subtracted here.
        credit_line_cents: {
          $sum: {
            $map: {
              input: "$lines",
              as: "l",
              in: { $cond: [{ $eq: ["$$l.source_type", "account_credit"] }, 1, 0] },
            },
          },
        },
        credit_applied_cents: { $ifNull: [{ $first: "$credit.cents" }, 0] },
        allocated_cents: { $ifNull: [{ $first: "$alloc.cents" }, 0] },
        // Discount counted once: every line, minus only the header discount no
        // line carries. That is what the fixed recompute_totals produces.
        correct_total_before_credit_cents: {
          $max: [0, { $subtract: ["$line_sum_cents", { $max: [0, { $subtract: ["$discount_cents", "$discount_line_cents"] }] }] }],
        },
        // The fingerprint the buggy recompute leaves: subtotal == sum of lines
        // (the generator writes it GROSS) and total == lines - discount again.
        double_count_fingerprint: {
          $and: [
            { $eq: ["$subtotal_cents", "$line_sum_cents"] },
            { $eq: ["$total_cents", { $max: [0, { $subtract: ["$line_sum_cents", "$discount_cents"] }] }] },
          ],
        },
        late_fee_lines: { $size: { $filter: { input: "$lines", as: "l", cond: { $or: [{ $eq: ["$$l.source_type", "late_fee_policy"] }, { $eq: ["$$l.line_type", "late_fee"] }] } } } },
        ach_lines: { $size: { $filter: { input: "$lines", as: "l", cond: { $eq: ["$$l.line_type", "ach_discount"] } } } },
        other_added_lines: {
          $size: {
            $filter: {
              input: "$lines",
              as: "l",
              cond: { $not: [{ $in: ["$$l.line_type", ["tuition", "discount", "ach_discount", "late_fee"]] }] },
            },
          },
        },
      },
    },
    {
      $addFields: {
        // What the family should owe in total, net of the account credit the
        // generator applied (credit is on no line; the buggy recompute dropped it too).
        correct_total_cents: {
          $max: [
            0,
            {
              $subtract: [
                "$correct_total_before_credit_cents",
                { $cond: [{ $gt: ["$credit_line_cents", 0] }, 0, "$credit_applied_cents"] },
              ],
            },
          ],
        },
      },
    },
    { $addFields: { under_charged_cents: { $subtract: ["$correct_total_cents", "$total_cents"] } } },
    { $match: { $or: [{ double_count_fingerprint: true }, { under_charged_cents: { $ne: 0 } }] } },
    {
      $project: {
        _id: 0,
        academy_id: 1,
        invoice_id: 1,
        invoice_number: 1,
        parent_id: 1,
        student_id: 1,
        period: 1,
        status: 1,
        subtotal_cents: 1,
        discount_cents: 1,
        discount_line_cents: 1,
        line_sum_cents: 1,
        credit_applied_cents: 1,
        total_cents: 1,
        correct_total_cents: 1,
        under_charged_cents: 1, // > 0: family was billed too little; < 0: too much
        balance_due_cents: 1,
        allocated_cents: 1,
        double_count_fingerprint: 1,
        late_fee_lines: 1,
        ach_lines: 1,
        other_added_lines: 1,
        updated_at: 1,
      },
    },
    { $sort: { academy_id: 1, period: 1, invoice_id: 1 } },
  ])
  .toArray();

printjson(rows);

const total = rows.reduce((s, r) => s + r.under_charged_cents, 0);
const paid = rows.filter((r) => r.status === "paid");
print(`\n${rows.length} affected invoice(s); net under-charge ${(total / 100).toFixed(2)} USD`);
print(`${paid.length} of them already paid (short-collected ${(paid.reduce((s, r) => s + r.under_charged_cents, 0) / 100).toFixed(2)} USD)`);
print(
  `${rows.length - paid.length} still open: after the fix deploys, their NEXT recompute ` +
    `(autopay retry, late fee, added line) raises the total to correct_total_before_credit_cents ` +
    `automatically. Where credit_applied_cents > 0 that over-shoots by the credit (a separate, ` +
    `pre-existing gap: applied credit is on no line), so settle those by hand first.`
);
