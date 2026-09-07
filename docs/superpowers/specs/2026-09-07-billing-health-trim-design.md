# Billing Health, trimmed — design

Date: 2026-09-07. Owner decisions from the brainstorming session are recorded inline.
Companion documents: the billing surface inventory and wireframes (artifact links in the
PR description), and specs 1–3 — `2026-09-05-payments-buckets-design.md`,
`2026-09-05-family-billing-design.md`, `2026-09-07-month-close-design.md`. This is the
fourth of five specs; it covers only the Billing Health page and the routes behind it.

## 1. Purpose

Billing Health is the page you open when **Stripe** is the problem: money is not arriving,
a webhook is stuck, the connected account is not ready, a charge exists in Stripe but not
in the app. It is a plumbing console, and it should contain nothing about a particular
family's payment behaviour.

Today it contains both. Half the page — open failed payments with a Retry button, and
the dunning ladder — is family work that specs 1 and 2 now own better: the Failed autopay
bucket carries attempt counts and next retry dates, and the Family billing page carries
the audited charge path with a reason (PR #666). Keeping the third copy of Retry here
means three places to check and two ways to charge a card.

The page also states two contradictory verdicts about itself. The header pill computes
"System healthy" from backlog counts alone, so an academy with **no connected Stripe
account and the platform fallback off** — where no parent can pay anything — renders a
green pill directly above a red card reading "Parents cannot pay right now". The pill
also counts quarantined webhooks from a list capped at 50 while the tile beside it shows
the true count.

This spec trims the page to plumbing, gives it one health verdict, moves the
reconciliation lookup here from Payments, and replaces the misleading legacy-match list.

Out of scope: Settings Billing rules (spec 5). Nothing about how money moves changes; no
migration, no data change.

## 2. Owner decisions

| Question | Decision |
|---|---|
| Legacy match queue | The list goes. It is not a queue: it recomputes "every open invoice with no allocation" on each load and fans out one Stripe `list_charges` call per row, so in production it presents ordinary unpaid invoices as migrated ones. The **confirm path stays** as a deliberate lookup: "link a Stripe charge to an invoice", by invoice id and charge id. |
| Who sees the page | **Owner only.** Stripe plumbing is governance, the same tier as Reports and Payouts. |
| Failed attempts and dunning | Removed from this page. The Payments Failed autopay bucket and the Family timeline own them. The one exception is the autopay switch-off failure (§4.4), which is plumbing and has no other home. |

## 3. What the page becomes

Per wireframe 4, four things and nothing else:

1. **Can parents pay?** — Connect readiness, and the single health verdict.
2. **Webhooks** — quarantined events with replay.
3. **Reconciliation** — runs, "Reconcile now", and the lookup by Stripe id.
4. **Link a Stripe charge** — the surviving half of legacy match.

Removed from the page: Open failed payments and its Retry / View dialog, the dunning
ladder table, and the page-side `healthy` computation.

## 4. One health verdict

### 4.1 Today

`billing-health/page.tsx` computes

```ts
const healthy = failedRows.length === 0 && activeDunningRows.length === 0 && quarantined.length === 0;
```

— backlog only, ignoring `payments_possible` entirely, and reading `quarantined` from the
50-capped list. `GET /admin/billing/connect-readiness` separately returns
`payments_possible = ready or fallback_allowed` and `funds_route_to_academy = ready`.

### 4.2 After

The verdict is computed **once, on the backend**, and returned by the readiness endpoint
as a new `health` object. The page renders it and computes nothing:

```
health: {
  state: "blocked" | "attention" | "ok",
  headline: str,          # one sentence, composed server side
  reasons: [ { code, detail } ]
}
```

| State | When | Headline |
|---|---|---|
| `blocked` | `payments_possible` is false | "Parents cannot pay right now" |
| `attention` | payments possible, but quarantined webhooks > 0, or the last reconciliation run failed, or there has been no run in 48 hours, or an autopay switch-off failed (§4.4) | "Payments work, {n} thing(s) need attention" |
| `ok` | none of the above | "Stripe is healthy" |

`blocked` outranks `attention`: an academy that cannot take money is never described as
merely needing attention. Counts come from the same aggregate the tiles show
(`count_stuck_by_status`), never from a capped list, so the pill and the number beside it
can no longer disagree.

Reason codes: `connect_not_ready`, `fallback_only` (informational, does not by itself
raise the state — funds route to the platform, which is a deliberate setting),
`webhooks_quarantined`, `reconciliation_failed`, `reconciliation_stale`,
`autopay_disable_failed`.

### 4.3 Tiles

Three tiles, all fed by the readiness response: Connect state with the funds-routing line,
quarantined webhook count (true count), last reconciliation with its outcome.

### 4.4 The one dunning fact that stays

`dunning_states` carries `autopay_disable_status`, `autopay_disable_error` and
`autopay_disabled_at`: when the ladder runs out, the worker switches autopay off, and
that Stripe call can itself fail. Nothing else in the product shows this. A failed
switch-off means the worker believes autopay is off while Stripe may still be attached,
so it is plumbing, not family work.

It appears as a single line under Reconciliation — "Autopay switch-off failed for {n}
invoices" with the invoice ids and their error, linking each to the family page — and as
the `autopay_disable_failed` reason code. It is a count and a list, with no action: the
fix is to retry the switch-off, which the worker already does on its next pass. No new
endpoint; the readiness composition reads the count from `dunning_states`.

## 5. Backend

### 5.1 Wiring moves out of `admin.py`

The billing-health closures sit inside `composition/admin.py`, which is at 4751 lines
against a 4800 budget. This spec moves the surviving ones into a new
`composition/billing_health.py` exposing a frozen `AdminBillingHealth` dataclass, wired
onto `app.state.admin_billing_health` in `main.py`, exactly as `composition/collections.py`
and `composition/families.py` do. Routes resolve it through a `Protocol` + `Depends` in a
new `interfaces/admin/billing_health_routes.py`, moved out of the 1541-line
`billing_routes.py`.

Moved: `get_connect_readiness` (extended with `health`), `list_reconciliation_runs`,
`run_reconciliation`, `replay_webhook_event`, `list_billing_webhook_events`,
`get_billing_reconciliation_report`, `confirm_legacy_match`.

Deleted: `list_legacy_match_queue` and its closure, the `LegacyMatchRowDto` /
`LegacyMatchCandidateDto` / `LegacyMatchQueueResponse` DTOs, and
`ListLegacyMatchQueue` with `list_unmatched_invoices` on the ledger repository if no
other caller remains.

**Kept but no longer called from this page:** `GET /admin/billing/failed-payment-attempts`,
`GET /admin/billing/dunning` and `GET /admin/billing/invoices/{id}/attempts`. Spec 3
removes the Reports page's copy of the first; after both PRs merge these routes have no
caller, and deleting them is a follow-up (§9). They are left alive here so this PR and
spec 3's PR can merge against `main` in either order.

### 5.2 Routes after the trim

All under `require_owner()`, all added to `OWNER_ONLY_ROUTE_PATHS`, which the structural
owner-gate test verifies in both directions:

| Route | Purpose |
|---|---|
| `GET /admin/billing/connect-readiness` | readiness + `health` (§4.2) |
| `GET /admin/billing/webhooks?status=&limit=` | quarantined list |
| `POST /admin/billing/webhook-events/{id}/replay` | replay |
| `GET /admin/billing/reconciliation-runs` | run history |
| `POST /admin/billing/reconcile-now` | trigger |
| `GET /admin/billing/reconciliation` | lookup by `pi_` / `in_` (moved here from Payments) |
| `POST /admin/billing/legacy-match/confirm` | link a charge to an invoice |

Moving these from admin to owner is a **visible access change**: an admin who could open
Billing Health yesterday gets a 404 today. The release note says so explicitly.

## 6. Page

Route stays `/admin/billing-health`. Owner-only, so the nav item is filtered by
`navForRoles` and the route joins `OWNER_ONLY_ROUTE_PREFIXES`.

- Header: title, health pill from `health.state` with `health.headline`, "Reconcile now".
- Three tiles (§4.3).
- **Can parents pay?** — the existing readiness card, unchanged apart from taking its
  tone from `health.state` rather than recomputing one.
- **Webhooks** — the quarantined table with Replay, plus the true count and a line when
  the list is truncated.
- **Reconciliation** — the runs table, then the lookup panel moved wholesale from
  `payments/ReconciliationReportPanel.tsx` into
  `billing-health/ReconciliationLookupPanel.tsx` (same component, new home), then the
  autopay switch-off line (§4.4).
- **Link a Stripe charge** — invoice id, charge id, amount, optional payment intent id
  and paid-at, with a confirmation naming the invoice and amount before posting. The
  endpoint is idempotent on the charge and invoice pair, so a double submit is safe, and
  it refuses an invoice that is not payable or an amount above the balance; both errors
  render inline.

The page uses `formatCents` and `billing-status.ts`, and drops its local formatters.

On Payments, `AllInvoicesTab` loses the reconciliation panel and gains a one-line pointer
to Billing Health, shown only to owners.

## 7. Error handling

- `connect-readiness` failing is the one fatal error: without it there is no verdict, and
  the page shows a single retry panel rather than a misleading green pill.
- Every other section degrades independently: a failed webhook list, run list or
  switch-off count renders that section's error inline and contributes no reason code, and
  the headline says which check could not run rather than claiming health.
- `reconcile-now` returns 503 when Stripe is unconfigured; the button surfaces that
  message rather than a generic failure.

## 8. Testing

Backend:

- Unit tests for the health verdict: `blocked` when payments are impossible even with an
  empty backlog (the contradiction this spec removes), `attention` for each reason code,
  `fallback_only` alone staying `ok`, `blocked` outranking `attention`, and counts taken
  from the aggregate rather than the capped list.
- Contract test (mongomock) for the switch-off failure count and its invoice list.
- Interface tests: every route 200 for owner and **404 for admin**, coach and parent;
  the legacy-match-queue route gone; confirm still 200 / 400; the structural owner-gate
  test updated in both directions.
- A test asserting `composition/admin.py` shrank and the new module is wired, alongside
  the existing composition line-budget test.

Frontend:

- Node test for the health pill mapping (state → tone and headline) and the truncation
  line.
- `billing-health.spec.ts` rewritten: the three tiles, replay, reconcile now, the moved
  lookup panel, the link-a-charge form posting the right body, the switch-off line, and
  **no failed-payments or dunning tables**; plus a stub where payments are impossible and
  the backlog is empty, asserting the pill reads blocked.
- `billing-trust-recovery.spec.ts` updated for the lookup's new home;
  `admin-shell.spec.ts` and `screen-meta.test.ts` for the owner-only nav item;
  `saas-launch-route-matrix.spec.ts` for the removed stubs.
- Inventory manifest: the `/admin/billing-health` entry loses the Retry, View and legacy
  Match workflows, buttons, modals and risk edges, and gains the lookup and link-a-charge
  ones; acceptance strings stay at or above the workflow and risk-edge counts. Route
  count is unchanged.

## 9. Rollout

One PR. Backend first (health verdict, composition move, route trim, owner gate), then
the page, then the manifest. No migration, no data change, no env.

Release note calls out the access change (admins lose the page), the removed sections and
where they went, and the moved reconciliation lookup.

## 10. Follow-ups this spec deliberately leaves

- Delete `GET /admin/billing/failed-payment-attempts`, `GET /admin/billing/dunning` and
  `GET /admin/billing/invoices/{id}/attempts` once spec 3 has merged and no caller
  remains.
- Retry the autopay switch-off from the page, if leaving it to the worker's next pass
  proves too slow in practice.
- A webhook event search by Stripe event id, if replay-by-list proves too coarse.
- Retire `list_unmatched_invoices` on the ledger repository if the link-a-charge form
  makes it permanently unused.
