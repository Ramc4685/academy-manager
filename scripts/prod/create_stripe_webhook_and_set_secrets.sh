#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${FLY_APP_NAME:-courtmastr-academy-api}"
WEBHOOK_URL="${STRIPE_WEBHOOK_URL:-https://api.academy.courtmastr.com/api/v2/parent/webhooks/stripe}"
DESCRIPTION="${STRIPE_WEBHOOK_DESCRIPTION:-CourtMastr Academy Manager parent billing webhooks}"

if ! command -v stripe >/dev/null 2>&1; then
  echo "stripe CLI is required. Install it with: brew install stripe/stripe-cli/stripe" >&2
  exit 1
fi

if ! command -v flyctl >/dev/null 2>&1; then
  echo "flyctl is required. Install it and run: flyctl auth login" >&2
  exit 1
fi

echo "This will create a LIVE Stripe webhook endpoint and update Fly secrets."
echo "Fly app: ${APP_NAME}"
echo "Webhook URL: ${WEBHOOK_URL}"
echo
echo "Use your Stripe LIVE secret key. Do not enter pk_live_; publishable keys are not used here."
echo

read -r -s -p "Enter live Stripe secret key (sk_live_...): " STRIPE_API_KEY
echo

if [[ -z "${STRIPE_API_KEY}" ]]; then
  echo "STRIPE_API_KEY cannot be empty." >&2
  exit 1
fi

if [[ "${STRIPE_API_KEY}" == sk_test_* || "${STRIPE_API_KEY}" == rk_test_* ]]; then
  echo "Refusing to use a test-mode Stripe API key for production." >&2
  exit 1
fi

if [[ "${STRIPE_API_KEY}" == pk_* ]]; then
  echo "Publishable keys cannot create webhooks or authenticate backend billing calls." >&2
  exit 1
fi

if [[ "${STRIPE_API_KEY}" != sk_live_* && "${STRIPE_API_KEY}" != rk_live_* ]]; then
  echo "Stripe API key must start with sk_live_ or rk_live_." >&2
  exit 1
fi

TMP_JSON="$(mktemp)"
trap 'rm -f "${TMP_JSON}"' EXIT

echo "Creating live Stripe webhook endpoint..."
if ! stripe webhook_endpoints create --live --api-key "${STRIPE_API_KEY}" \
  --url "${WEBHOOK_URL}" \
  --description "${DESCRIPTION}" \
  --enabled-events checkout.session.completed \
  --enabled-events checkout.session.expired \
  --enabled-events checkout.session.async_payment_succeeded \
  --enabled-events checkout.session.async_payment_failed \
  --enabled-events payment_intent.succeeded \
  --enabled-events payment_intent.payment_failed \
  --enabled-events invoice.paid \
  --enabled-events invoice.payment_failed \
  --enabled-events charge.refunded \
  --enabled-events customer.subscription.updated \
  --enabled-events customer.subscription.deleted \
  >"${TMP_JSON}"; then
  echo "Stripe webhook creation failed." >&2
  exit 1
fi

WEBHOOK_INFO="$(
  python3 - "${TMP_JSON}" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1]))
if data.get("error"):
    error = data["error"]
    print(f"ERROR\t{error.get('type')}\t{error.get('message')}")
    raise SystemExit(0)

secret = str(data.get("secret") or "")
endpoint_id = str(data.get("id") or "")
url = str(data.get("url") or "")
status = str(data.get("status") or "")
if not secret.startswith("whsec_") or not endpoint_id:
    print("ERROR\tunexpected_response\tStripe did not return a webhook signing secret.")
    raise SystemExit(0)

print(f"OK\t{endpoint_id}\t{url}\t{status}\t{secret}")
PY
)"

IFS=$'\t' read -r RESULT ENDPOINT_ID ENDPOINT_URL ENDPOINT_STATUS STRIPE_WEBHOOK_SECRET <<<"${WEBHOOK_INFO}"

if [[ "${RESULT}" != "OK" ]]; then
  echo "Stripe webhook creation failed: ${ENDPOINT_ID:-unknown} ${ENDPOINT_URL:-}" >&2
  exit 1
fi

echo "Created Stripe webhook endpoint: ${ENDPOINT_ID} (${ENDPOINT_STATUS})"
echo "Importing Stripe secrets into Fly..."

printf 'STRIPE_API_KEY=%s\nSTRIPE_WEBHOOK_SECRET=%s\n' \
  "${STRIPE_API_KEY}" \
  "${STRIPE_WEBHOOK_SECRET}" \
  | flyctl secrets import -a "${APP_NAME}"

echo
echo "Stripe webhook endpoint created and Fly secrets submitted for ${APP_NAME}."
echo "Secrets were not printed. Next: rerun the production billing probe after Fly finishes deploying."
