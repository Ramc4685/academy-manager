# Stripe Connect Marketplace Sample

This is a self-contained demo for Stripe Connect. It does not use the Academy Manager database and it does not store onboarding status. For this demo, account status is always fetched directly from Stripe with `stripe.accounts.retrieve(stripeAccountId)`.

## Run Locally

```bash
cd examples/stripe-connect-marketplace
npm install
cp .env.example .env
npm start
```

Fill `.env` with your Stripe test keys. Do not commit `.env`.

Open `http://localhost:4242`.

## What It Demonstrates

- Creating a connected account with only `controller` properties. The sample intentionally does not pass top-level `type`.
- Creating Account Links for hosted onboarding.
- Fetching connected account status directly from the Accounts API.
- Creating connected-account products using the `Stripe-Account` header via `stripeAccount`.
- Displaying a simple storefront for a connected account.
- Creating hosted Checkout Sessions as direct charges with an application fee.

## Production Notes

- The sample uses the connected account ID in URLs, such as `/store/acct_...`, to keep the demo small. In production, use an academy slug or another customer-facing identifier and resolve it to the account ID server-side.
- Add real authentication and authorization before letting users create accounts or products.
- Add CSRF protection for browser form posts.
- Add webhooks for durable payment fulfillment. Redirects do not prove payment success.
- Store connected account IDs in your database only after you have verified the user owns the academy or merchant profile.
