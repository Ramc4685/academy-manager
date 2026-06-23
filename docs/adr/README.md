# Architecture Decision Records

This directory holds the load-bearing decisions for the academy-manager v2 architecture.

ADRs are short, dated, owned. Status moves: **Proposed → Accepted → (Superseded by ADR-NNNN | Deprecated)**. Accepted ADRs cannot be ignored — deviation requires a superseding ADR.

| # | Title | Status | Date |
|---|---|---|---|
| [0001](0001-fastapi-mongodb-stays.md) | FastAPI + MongoDB stay | Accepted | 2026-05-16 |
| [0002](0002-nextjs-app-router.md) | Next.js 15 App Router replaces CRA | Accepted | 2026-05-16 |
| [0003](0003-bff-inside-backend.md) | BFF lives inside the backend (one process) | Accepted | 2026-05-16 |
| [0004](0004-pwa-over-native.md) | PWA over native, Capacitor deferred | Accepted | 2026-05-16 |
| [0005](0005-clean-architecture-lite-monolith.md) | Clean-architecture-lite monolith, not microservices | Accepted | 2026-05-16 |
| [0006](0006-tenant-ready-single-tenant-shipped.md) | Tenant-ready, single-tenant shipped | Accepted | 2026-05-16 |
| [0011](0011-billing-ledger-payment-storage.md) | LedgerPayment uses its own ledger_payments collection | Accepted | 2026-06-14 |
| [0012](0012-ledger-invoice-as-source-of-truth.md) | Ledger invoice is the source of truth for billing | Accepted | 2026-06-14 |
| [0013](0013-card-processing-fee-as-method-conditional-invoice-line.md) | Card processing fee as a method-conditional invoice line | Proposed | 2026-06-22 |

## When to write an ADR

- A choice that future-you (or a new contributor) will second-guess without context.
- A choice that constrains downstream work (e.g., "we will not use X").
- A choice with a *reversal cost* — if changing it later would be expensive or scary, write the ADR.

Don't write ADRs for choices that are obvious, documented elsewhere, or trivially reversible (file naming, lint config, formatting).

## Template

```markdown
# ADR-NNNN: Title

**Status:** Proposed | Accepted | Deprecated | Superseded by ADR-XXXX
**Date:** YYYY-MM-DD
**Deciders:** Names
**Ticket:** Reference

## Context
[Forces at play]

## Decision
[What we're doing]

## Options Considered
[A, B, C — with assessment table]

## Trade-off Analysis
[The deciding factor]

## Consequences
[Easier / Harder / To revisit]

## Action Items
[Concrete follow-ups]
```
