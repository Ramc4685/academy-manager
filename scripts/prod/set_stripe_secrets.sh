#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${FLY_APP_NAME:-courtmastr-academy-api}"

if ! command -v flyctl >/dev/null 2>&1; then
  echo "flyctl is required. Install it and run: flyctl auth login" >&2
  exit 1
fi

echo "This will update Stripe secrets for Fly app: ${APP_NAME}"
echo "Use Stripe LIVE mode values. The API key should start with sk_live_ or rk_live_."
echo

read -r -s -p "Enter live Stripe API key: " STRIPE_API_KEY
echo
read -r -s -p "Enter live Stripe webhook secret (whsec_...): " STRIPE_WEBHOOK_SECRET
echo
echo

if [[ -z "${STRIPE_API_KEY}" ]]; then
  echo "STRIPE_API_KEY cannot be empty." >&2
  exit 1
fi

if [[ "${STRIPE_API_KEY}" == sk_test_* || "${STRIPE_API_KEY}" == rk_test_* ]]; then
  echo "Refusing to set a test-mode Stripe API key in production." >&2
  exit 1
fi

if [[ "${STRIPE_API_KEY}" != sk_live_* && "${STRIPE_API_KEY}" != rk_live_* ]]; then
  echo "Stripe API key must start with sk_live_ or rk_live_." >&2
  exit 1
fi

if [[ -z "${STRIPE_WEBHOOK_SECRET}" ]]; then
  echo "STRIPE_WEBHOOK_SECRET cannot be empty." >&2
  exit 1
fi

if [[ "${STRIPE_WEBHOOK_SECRET}" != whsec_* ]]; then
  echo "Stripe webhook secret must start with whsec_." >&2
  exit 1
fi

printf 'STRIPE_API_KEY=%s\nSTRIPE_WEBHOOK_SECRET=%s\n' \
  "${STRIPE_API_KEY}" \
  "${STRIPE_WEBHOOK_SECRET}" \
  | flyctl secrets import -a "${APP_NAME}"

echo
echo "Stripe secrets submitted to Fly for ${APP_NAME}."
echo "Next: rerun the production billing probe after Fly finishes deploying."
