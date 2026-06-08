# Marvy Labs IP protection and production branding plan

## Current State

Status: active

## Problem

Plan ownership/copyright/IP claim updates, remove customer-facing V2 language, and add production-grade legal surfaces without changing API compatibility paths.

## Changed Files

- `frontend/lib/brand.ts`
- `frontend/lib/brand.node-test.mjs`
- `frontend/app/page.tsx`
- `frontend/app/landing.module.css`
- `frontend/app/(marketing)/legal.module.css`
- `frontend/app/(marketing)/terms/page.tsx`
- `frontend/app/(marketing)/privacy/page.tsx`
- `frontend/app/(marketing)/security/page.tsx`
- `frontend/app/layout.tsx`
- `frontend/app/(marketing)/layout.tsx`
- `frontend/app/(marketing)/login/page.tsx`
- `frontend/app/(marketing)/register/page.tsx`
- `frontend/public/manifest.webmanifest`
- `frontend/e2e/fixtures/saas-stubs.ts`
- `README.md`
- `LICENSE`
- `frontend/README.md`
- `backend/v2/main.py`
- `backend/pyproject.toml`
- `backend/v2/tests/unit/test_healthz.py`
- `docs/superpowers/plans/2026-06-08-marvy-labs-ip-production-branding.md`

## Log

- 2026-06-08T14:43:03 main/NA: Task ledger created.
- 2026-06-08T14:46:56 main/working: Created implementation plan at docs/superpowers/plans/2026-06-08-marvy-labs-ip-production-branding.md. No code changes made.
- 2026-06-08T15:07:36 main/working: Implemented Marvy Labs legal owner constants, public legal pages, visible V2 copy removal, repo legal notice updates, public API metadata cleanup, and browser-smoked public pages on localhost:3002.
## Verification

- No verification recorded yet.
- 2026-06-08T14:46:56: Planning-only verification: read repo kickoff docs, reviewed public brand/legal hotspots, checked official Copyright Office/USPTO source guidance, and self-reviewed plan for placeholder language.
- 2026-06-08T15:07:36: Text sweeps passed: no public matches for v2 frontend, v2.0, Next v2, Academy Manager v2, RamC Venkatasamy, or Copyright (c).*CourtMastr; internal /api/v2 compatibility references remain.
- 2026-06-08T15:07:36: Frontend passed: node --no-warnings --test lib/brand.node-test.mjs; pnpm typecheck; pnpm lint; pnpm build.
- 2026-06-08T15:07:36: Backend passed: .venv/bin/pytest v2/tests/unit/test_healthz.py -q; .venv/bin/ruff check v2; .venv/bin/ruff format --check v2.
- 2026-06-08T15:07:36: Browser smoke passed on http://localhost:3002 for /, /terms, /privacy, /security, /login, /register, including no console/page errors and no 390px landing horizontal overflow.
## Reusable Lessons

- None recorded yet.
