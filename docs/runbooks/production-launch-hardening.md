# Production Launch Hardening Runbook

Date: 2026-06-16

Use this runbook after the `feat/launch-hardening-billing-integration` branch is
deployed to a staging or production-like environment. It collects the remaining
evidence required by `docs/qa/2026-06-16-launch-readiness-addendum.md`.

Do not run destructive database operations from this runbook. The ledger payment
migration below is copy-only and never deletes legacy `payments` rows.

## Required Inputs

- Backend app: `courtmastr-academy-api`
- Primary academy: `acad_blno_badminton`
- Target Mongo URL and DB name
- Stripe test or live-like webhook secret for the target environment
- Resend sender domain verified for the target environment
- Operator approval before any command that writes to the target database

## 1. Environment Gate

Capture deployed environment values:

```bash
flyctl secrets list -a courtmastr-academy-api
flyctl ssh console -a courtmastr-academy-api -C 'printenv | sort'
```

Run the read-only environment audit:

```bash
cd backend
APP_TENANCY_MODE=single_academy \
PRIMARY_ACADEMY_ID=acad_blno_badminton \
ENABLE_PLATFORM_ROUTES=false \
ENABLE_OWNER_ROLE=false \
ENABLE_STUDENT_LOGIN=false \
CORS_ORIGINS=https://academy.courtmastr.com \
python scripts/launch_readiness_audit.py --env-only
```

Pass criteria:

- `APP_TENANCY_MODE=single_academy`
- `PRIMARY_ACADEMY_ID=acad_blno_badminton`
- `ENABLE_PLATFORM_ROUTES=false`
- `ENABLE_OWNER_ROLE=false`
- `ENABLE_STUDENT_LOGIN=false`
- `CORS_ORIGINS` has explicit origins and no `*`

## 2. Database Audit And Ledger Copy

Dry-run first:

```bash
cd backend
python scripts/ledger_payments_storage_audit.py \
  --mongo-url "$MONGO_URL" \
  --db-name "$DB_NAME"
```

Then run the broader read-only launch audit:

```bash
python scripts/launch_readiness_audit.py \
  --mongo-url "$MONGO_URL" \
  --db-name "$DB_NAME" \
  --primary-academy-id acad_blno_badminton
```

If `missing_from_ledger_payments` is non-zero, get operator approval and apply
the copy-only migration:

```bash
python scripts/ledger_payments_storage_audit.py \
  --mongo-url "$MONGO_URL" \
  --db-name "$DB_NAME" \
  --apply
```

Pass criteria:

- `missing_from_ledger_payments=0` after apply
- Required indexes report `status=pass`
- Active parent memberships without inviter are reviewed and accepted or fixed
- Audit output is saved with the release evidence

## 3. Billing Reconciliation

Run these flows in staging or a production-like tenant:

- Create invoice
- Add charge
- Remove draft line
- Send invoice with email delivery disabled
- Send invoice with Resend enabled
- Charge autopay
- Record manual payment
- Verify payment allocation
- Issue refund or credit path currently supported by the app
- Generate coach payout

Pass criteria:

- Checkout generation alone does not mark `delivery_status=sent`
- Successful Resend delivery marks `delivery_status=sent`
- Failed or disabled email leaves `not_sent` or `delivery_failed`
- Ledger payments are written to `ledger_payments`
- Invoice balance, payment allocation, credit, refund, and payout totals reconcile

## 4. Stripe Webhook Replay

Replay representative events against the target webhook endpoint:

- `checkout.session.completed` for invoice pay link
- Duplicate `checkout.session.completed`
- `payment_intent.succeeded`
- `invoice.paid` for subscription-backed billing
- Failed payment event

Pass criteria:

- Duplicate event is deduped by `stripe_webhook_events`
- Events without persisted tenant-owned mapping do not mutate tenant data
- Invoice pay link creates a ledger payment and allocation for the correct academy
- Failed payment does not mark invoice paid

## 5. Manual QA

Admin desktop:

- Public registration review and approval
- Enrollment creation
- Session occurrence creation
- Student Billing tab actions
- Reports CSV export
- Pause request approval

Parent and coach mobile:

- Parent onboarding
- Parent payment or checkout return
- Parent pause request
- Coach today view
- Attendance submission
- Skill progress update

Pass criteria:

- Parent cannot view another parent's student or invoice
- Coach cannot view unassigned students
- Coach cannot mutate roster or billing moves
- Admin views remain scoped to `acad_blno_badminton`
- CSV exports contain only tenant data

## 6. Operations Proof

Collect evidence for:

- Mongo backup exists
- Restore drill completed against a non-production target
- Error logging and alert destination configured
- Health monitor configured for `/api/v2/healthz`
- Rollback command rehearsed or documented for the deployed release
- Firebase authorized domains include the production frontend host
- Cookie and CORS behavior verified in a browser

## Ship Decision

Ship only when every item is green:

- No tenant leaks
- No RBAC gaps
- Money flows reconcile
- Parent/coach flows pass mobile
- Admin flows pass desktop
- Stripe webhooks are idempotent
- Backups and rollback exist

If any item is red or unverified, the verdict remains `do not ship`.
