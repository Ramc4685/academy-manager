# sibling-discount-family-offers

PR: TBD

## What changed
Settings > Billing rules has a new Family offers card (owner only to save, audited). It ships switched off. The owner can turn on an automatic sibling discount and set its percentage (no default; 0.01% to 100%), which child pays full price (highest tuition, lowest tuition or first enrolled) and whether it covers every class of each other child or one class each. The monthly run and admin "Bill this month" then price each other child's monthly tuition with it, on the existing "Sibling discount" line; a larger manual tuition discount on the same class wins (ties go to the manual one) and the two never add up. Each enrollment-month's decision is recorded once and reused, so retries and orphan recovery charge the same amount, and an invoice already issued is never repriced. The card also stores the referral programme's values (credits, hold days, yearly cap, expiry, trigger) with its switch disabled and marked Coming soon; the referral logic is not built yet. New API: `GET`/`PUT /api/v2/admin/billing/family-offers` (PUT owner only).

## Deploy notes
Migration `0237_sibling_discount_decisions` creates the unique index `sibling_decision_enrollment_period_unique` on the new `sibling_discount_decisions` collection (academy, enrollment, period). It applies through the release_command; nothing to watch beyond it creating one index. No env vars.

Read-only pre-deploy check (do not add an index from it): confirm no enrollment has two active manual discounts, since the resolver weighs the sibling discount against the one active manual policy. Expect no rows:

```
db.enrollment_discounts.aggregate([
  { $match: { status: "active" } },
  { $group: { _id: { academy_id: "$academy_id", enrollment_id: "$enrollment_id" }, n: { $sum: 1 }, ids: { $push: "$discount_id" } } },
  { $match: { n: { $gt: 1 } } }
])
```

## Risk / rollback
Nothing changes for any academy until the owner switches the sibling discount on, and with it off the monthly run writes no decision rows. If prices look wrong, switching it off stops new decisions at once; months already decided keep their decision (by design, so a retry never changes a charge), so delete the affected `sibling_discount_decisions` rows only for months not yet invoiced if they must be re-priced. Roll back the code by reverting the merge commit; the collection and index can stay or be dropped. Known limit: siblings are found through `students.parent_id`, so a child linked to the parent only through `enrollment.parent_id` or `parent_user_id` is not counted.
