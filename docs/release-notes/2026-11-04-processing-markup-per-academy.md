# processing-markup-per-academy

PR: #1131

## What changed

The CourtMastr processing markup (`application_fee_bps`, already charged on Stripe Connect payments) now carries its agreement: a platform admin can record the academy's acceptance (version, signatory, time) when setting the rate on the platform tenant page, every change is audited with the agreement fields, and new academies start at 100 bps (1%) with no acceptance recorded yet. Academy admins see the rate, the agreement text and the acceptance status read-only under Settings, Payments, and the Month close page shows a "CourtMastr processing fee taken" line. From this release the Stripe webhook records the fee Stripe actually took on each payment row (`application_fee_cents`, from the PaymentIntent or invoice, or from the checkout-session metadata the pay link now carries); the line sums those and estimates only payments recorded before this release from the current rate, which is why it still says "estimated". Parents are not charged a per-order fee.

## Deploy notes

- No migration: the three new `billing_settings` fields and the new `ledger_payments.application_fee_cents` are optional and absent on every existing document.
- No env or config changes.
- Owner step after deploy: set the live academy to 100 bps on `/platform/tenants/[academyId]` and tick "Record the academy's acceptance" with the signatory. Existing academies are untouched by the deploy itself (no setting still means 0 bps). Note that the house academy charges on the platform Stripe account, where no application fee applies, so its statement line reads 0 regardless of the rate.

## Risk / rollback

- A wrong rate charges parents nothing extra but moves money between the academy and the platform on every Connect charge: the rate is bounded at 10%, audited, and visible to the academy admin. If billing settings cannot be read at charge time the charge still goes through with no fee (existing behaviour).
- The month-close line is an estimate and is hidden (with a `platform_fee_unavailable` warning) rather than shown wrong when the rate cannot be read.
- Rollback: revert the PR. Stored agreement fields are ignored, new tenants go back to 0 bps, and the charge path is unchanged.
