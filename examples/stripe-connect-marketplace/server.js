require("dotenv").config();

const express = require("express");
const Stripe = require("stripe");

const {
  STRIPE_SECRET_KEY,
  STRIPE_PUBLISHABLE_KEY,
  STRIPE_API_VERSION = "2026-06-24.dahlia",
  ROOT_URL = "http://localhost:4242",
  APPLICATION_FEE_AMOUNT = "123",
  PORT = "4242",
} = process.env;

function requireEnv(name, value, hint) {
  if (!value || value.includes("REPLACE_ME")) {
    throw new Error(
      `${name} is required. ${hint} Copy .env.example to .env and fill this value with your Stripe test credential.`
    );
  }
}

requireEnv("STRIPE_SECRET_KEY", STRIPE_SECRET_KEY, "Use a sk_test_... key for local testing.");
requireEnv("STRIPE_PUBLISHABLE_KEY", STRIPE_PUBLISHABLE_KEY, "Use a pk_test_... key for local testing.");

const applicationFeeAmount = Number.parseInt(APPLICATION_FEE_AMOUNT, 10);
if (!Number.isInteger(applicationFeeAmount) || applicationFeeAmount < 0) {
  throw new Error("APPLICATION_FEE_AMOUNT must be a non-negative integer in the smallest currency unit.");
}

const stripe = new Stripe(STRIPE_SECRET_KEY, {
  // The user requested the 2026-06-24.dahlia API version for this sample.
  apiVersion: STRIPE_API_VERSION,
});

const app = express();
app.use(express.urlencoded({ extended: false }));

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function page(title, body) {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(title)}</title>
  <style>
    :root {
      color-scheme: light;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
      color: #111827;
      background: #f8fafc;
    }
    body {
      margin: 0;
      padding: 32px;
    }
    main {
      max-width: 920px;
      margin: 0 auto;
    }
    h1 {
      margin: 0 0 8px;
      font-size: 28px;
    }
    h2 {
      margin: 32px 0 12px;
      font-size: 18px;
    }
    p {
      color: #4b5563;
    }
    a {
      color: #1d4ed8;
    }
    .panel,
    .product {
      background: white;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      padding: 20px;
      margin: 16px 0;
    }
    label {
      display: block;
      margin: 14px 0 6px;
      font-weight: 600;
    }
    input,
    textarea,
    select {
      width: 100%;
      box-sizing: border-box;
      border: 1px solid #d1d5db;
      border-radius: 6px;
      padding: 10px 12px;
      font: inherit;
      background: white;
    }
    textarea {
      min-height: 84px;
      resize: vertical;
    }
    button {
      border: 0;
      border-radius: 6px;
      padding: 11px 16px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      color: white;
      background: #111827;
    }
    button.secondary {
      color: #111827;
      background: #e5e7eb;
    }
    .row {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
    }
    .muted {
      color: #6b7280;
      font-size: 14px;
    }
    .status {
      display: inline-block;
      border-radius: 999px;
      padding: 4px 10px;
      background: #eef2ff;
      color: #3730a3;
      font-size: 13px;
      font-weight: 700;
    }
    .error {
      border-color: #fecaca;
      background: #fef2f2;
      color: #991b1b;
    }
    code {
      background: #f3f4f6;
      border-radius: 4px;
      padding: 2px 5px;
    }
  </style>
</head>
<body>
  <main>${body}</main>
</body>
</html>`;
}

function errorPage(message, status = 500) {
  return page(
    "Stripe Connect sample error",
    `<div class="panel error">
      <h1>Something needs attention</h1>
      <p>${escapeHtml(message)}</p>
      <p><a href="/">Back to demo</a></p>
    </div>`
  );
}

function moneyFromPrice(price) {
  if (!price || typeof price === "string") {
    return "Price unavailable";
  }
  const amount = price.unit_amount ?? 0;
  const currency = (price.currency || "usd").toUpperCase();
  return `${currency} ${(amount / 100).toFixed(2)}`;
}

function accountStatus(account) {
  const due = account.requirements?.currently_due || [];
  if (account.charges_enabled) {
    return "Ready to collect payments";
  }
  if (due.length > 0) {
    return `More onboarding required: ${due.join(", ")}`;
  }
  if (account.details_submitted) {
    return "Submitted, waiting for Stripe review";
  }
  return "Onboarding not started";
}

app.get("/", async (req, res) => {
  const accountId = typeof req.query.account === "string" ? req.query.account : "";
  let accountPanel = "";

  if (accountId) {
    try {
      // Demo requirement: fetch status directly from Stripe every time.
      // The sample deliberately does not store status in a database.
      const account = await stripe.accounts.retrieve(accountId);
      accountPanel = `<div class="panel">
        <h2>Connected Account</h2>
        <p><code>${escapeHtml(account.id)}</code></p>
        <p><span class="status">${escapeHtml(accountStatus(account))}</span></p>
        <p class="muted">charges_enabled=${account.charges_enabled}, payouts_enabled=${account.payouts_enabled}</p>
        <div class="row">
          <form method="post" action="/accounts/${encodeURIComponent(account.id)}/onboarding-link">
            <button type="submit">Onboard to collect payments</button>
          </form>
          <a href="/store/${encodeURIComponent(account.id)}">Open storefront</a>
        </div>
      </div>

      <div class="panel">
        <h2>Create Product on Connected Account</h2>
        <form method="post" action="/accounts/${encodeURIComponent(account.id)}/products">
          <label for="name">Name</label>
          <input id="name" name="name" value="Beginner group class" required>

          <label for="description">Description</label>
          <textarea id="description" name="description" required>One drop-in beginner group class.</textarea>

          <label for="priceInCents">Price in cents</label>
          <input id="priceInCents" name="priceInCents" type="number" min="50" step="1" value="2500" required>

          <label for="currency">Currency</label>
          <select id="currency" name="currency">
            <option value="usd">USD</option>
            <option value="cad">CAD</option>
          </select>

          <p><button type="submit">Create product</button></p>
        </form>
      </div>`;
    } catch (err) {
      accountPanel = `<div class="panel error">
        <h2>Could not retrieve account</h2>
        <p>${escapeHtml(err.message)}</p>
      </div>`;
    }
  }

  res.send(
    page(
      "Stripe Connect marketplace sample",
      `<h1>Stripe Connect Marketplace Sample</h1>
      <p>This demo creates connected accounts, sends users through Account Link onboarding, creates products on connected accounts, and sells them through hosted Checkout as direct charges with an application fee.</p>

      <div class="panel">
        <h2>Create Connected Account</h2>
        <p class="muted">This sample creates a connected account with only <code>controller</code> properties and no top-level <code>type</code>.</p>
        <form method="post" action="/accounts">
          <button type="submit">Create connected account</button>
        </form>
      </div>

      <div class="panel">
        <h2>Open Existing Account</h2>
        <form method="get" action="/">
          <label for="account">Connected account ID</label>
          <input id="account" name="account" placeholder="acct_..." value="${escapeHtml(accountId)}">
          <p><button class="secondary" type="submit">Check status</button></p>
        </form>
      </div>

      ${accountPanel}`
    )
  );
});

app.post("/accounts", async (req, res) => {
  try {
    const account = await stripe.accounts.create({
      // Requested Connect account shape:
      // - Do not pass top-level type.
      // - Platform controls fee collection.
      // - Stripe handles payment disputes and losses.
      // - Connected account gets full Stripe Dashboard access.
      controller: {
        fees: {
          payer: "account",
        },
        losses: {
          payments: "stripe",
        },
        stripe_dashboard: {
          type: "full",
        },
      },
    });

    res.redirect(`/?account=${encodeURIComponent(account.id)}`);
  } catch (err) {
    res.status(500).send(errorPage(err.message));
  }
});

app.get("/accounts/:accountId/status", async (req, res) => {
  try {
    // Always retrieve live status from Stripe for this demo.
    // A production app can cache selected fields, but it should still reconcile
    // against Stripe and listen to account.updated webhooks.
    const account = await stripe.accounts.retrieve(req.params.accountId);
    res.json({
      id: account.id,
      status: accountStatus(account),
      charges_enabled: account.charges_enabled,
      payouts_enabled: account.payouts_enabled,
      details_submitted: account.details_submitted,
      currently_due: account.requirements?.currently_due || [],
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.post("/accounts/:accountId/onboarding-link", async (req, res) => {
  const accountId = req.params.accountId;

  try {
    const link = await stripe.accountLinks.create({
      // Account Links are short-lived URLs hosted by Stripe.
      // The user completes onboarding on Stripe, then returns to return_url.
      account: accountId,
      type: "account_onboarding",
      refresh_url: `${ROOT_URL}/?account=${encodeURIComponent(accountId)}&refresh=1`,
      return_url: `${ROOT_URL}/?account=${encodeURIComponent(accountId)}&returned=1`,
    });

    res.redirect(link.url);
  } catch (err) {
    res.status(500).send(errorPage(err.message));
  }
});

app.post("/accounts/:accountId/products", async (req, res) => {
  const accountId = req.params.accountId;
  const name = String(req.body.name || "").trim();
  const description = String(req.body.description || "").trim();
  const currency = String(req.body.currency || "usd").trim().toLowerCase();
  const priceInCents = Number.parseInt(req.body.priceInCents, 10);

  if (!name || !description || !Number.isInteger(priceInCents) || priceInCents <= 0) {
    res.status(400).send(errorPage("Product name, description, and a positive price are required.", 400));
    return;
  }

  try {
    await stripe.products.create(
      {
        name,
        description,
        default_price_data: {
          unit_amount: priceInCents,
          currency,
        },
      },
      {
        // This option sends the Stripe-Account header so the product is created
        // on the connected account, not on the platform account.
        stripeAccount: accountId,
      }
    );

    res.redirect(`/store/${encodeURIComponent(accountId)}`);
  } catch (err) {
    res.status(500).send(errorPage(err.message));
  }
});

app.get("/store/:accountId", async (req, res) => {
  const accountId = req.params.accountId;

  try {
    const account = await stripe.accounts.retrieve(accountId);
    const products = await stripe.products.list(
      {
        active: true,
        limit: 20,
        expand: ["data.default_price"],
      },
      {
        // This sends the Stripe-Account header for reads from the connected account.
        stripeAccount: accountId,
      }
    );

    const productCards = products.data
      .map((product) => {
        const price = product.default_price;
        const priceId = typeof price === "string" ? price : price?.id;
        const disabled = priceId && account.charges_enabled ? "" : "disabled";
        const buyHint = account.charges_enabled
          ? ""
          : `<p class="muted">Checkout is disabled until this connected account completes Stripe onboarding.</p>`;

        return `<div class="product">
          <h2>${escapeHtml(product.name)}</h2>
          <p>${escapeHtml(product.description || "No description")}</p>
          <p><strong>${escapeHtml(moneyFromPrice(price))}</strong></p>
          ${buyHint}
          <form method="post" action="/store/${encodeURIComponent(accountId)}/checkout">
            <input type="hidden" name="priceId" value="${escapeHtml(priceId || "")}">
            <button type="submit" ${disabled}>Buy with Stripe Checkout</button>
          </form>
        </div>`;
      })
      .join("");

    res.send(
      page(
        "Connected account storefront",
        `<!-- Demo shortcut: this URL contains the raw connected account ID. In production, use an academy slug or another public identifier and resolve it server-side. -->
        <h1>Storefront</h1>
        <p class="muted">Connected account: <code>${escapeHtml(accountId)}</code></p>
        <p><span class="status">${escapeHtml(accountStatus(account))}</span></p>
        <p><a href="/?account=${encodeURIComponent(accountId)}">Back to account dashboard</a></p>
        ${productCards || `<div class="panel"><p>No products yet.</p></div>`}`
      )
    );
  } catch (err) {
    res.status(500).send(errorPage(err.message));
  }
});

app.post("/store/:accountId/checkout", async (req, res) => {
  const accountId = req.params.accountId;
  const priceId = String(req.body.priceId || "").trim();

  if (!priceId) {
    res.status(400).send(errorPage("A price ID is required to start Checkout.", 400));
    return;
  }

  try {
    const session = await stripe.checkout.sessions.create(
      {
        // Direct charge: this Checkout Session is created on the connected
        // account by passing stripeAccount in the request options below.
        line_items: [
          {
            price: priceId,
            quantity: 1,
          },
        ],
        payment_intent_data: {
          // Sample application fee. The platform receives this amount and the
          // connected account receives the remainder, subject to Stripe fees.
          application_fee_amount: applicationFeeAmount,
        },
        mode: "payment",
        success_url: `${ROOT_URL}/success?session_id={CHECKOUT_SESSION_ID}`,
        cancel_url: `${ROOT_URL}/store/${encodeURIComponent(accountId)}`,
      },
      {
        // This sends the Stripe-Account header and makes the payment a direct
        // charge on the connected account.
        stripeAccount: accountId,
      }
    );

    res.redirect(303, session.url);
  } catch (err) {
    res.status(500).send(errorPage(err.message));
  }
});

app.get("/success", async (req, res) => {
  res.send(
    page(
      "Payment success",
      `<div class="panel">
        <h1>Payment started successfully</h1>
        <p class="muted">Checkout session: <code>${escapeHtml(req.query.session_id || "")}</code></p>
        <p>In production, fulfill orders from Stripe webhooks instead of trusting this redirect.</p>
        <p><a href="/">Back to demo</a></p>
      </div>`
    )
  );
});

app.listen(Number.parseInt(PORT, 10), () => {
  console.log(`Stripe Connect sample running at ${ROOT_URL}`);
  console.log(`Using Stripe API version ${STRIPE_API_VERSION}`);
  console.log("Open the URL above and create a connected account to begin.");
});
