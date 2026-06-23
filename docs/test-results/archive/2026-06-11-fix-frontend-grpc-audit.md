# fix frontend grpc audit

## Current State

Status: active

## Problem

CI pnpm audit --audit-level=high fails because firebase 11.0.2 pulls @grpc/grpc-js 1.9.15 via Firestore

## Changed Files

- None recorded yet.

## Log

- 2026-06-11T09:41:36 main/NA: Task ledger created.
- 2026-06-11T09:42:32 main/working: Added frontend pnpm override for @grpc/grpc-js 1.9.16 and regenerated pnpm-lock.yaml to remove vulnerable 1.9.15 pulled through firebase/firestore.
## Verification

- No verification recorded yet.
- 2026-06-11T09:44:04: Reproduced failure: cd frontend && pnpm audit --audit-level=high exited 1 with high @grpc/grpc-js <1.9.16 advisories via firebase/firestore.
- 2026-06-11T09:44:08: pnpm install --lockfile-only regenerated frontend/pnpm-lock.yaml with @grpc/grpc-js 1.9.16; pnpm install --frozen-lockfile passed and installed the patched graph.
- 2026-06-11T09:44:11: pnpm why @grpc/grpc-js now reports @grpc/grpc-js@1.9.16 as the only installed version under @firebase/firestore/firebase.
- 2026-06-11T09:44:14: pnpm audit --audit-level=high passed after the override; remaining audit output is 1 low and 2 moderate vulnerabilities, below the high gate.
- 2026-06-11T09:44:19: pnpm typecheck passed; pnpm lint passed with only the existing Next.js lint deprecation notice; node --no-warnings --test lib/api/*.node-test.mjs lib/auth/*.node-test.mjs passed 19 tests; pnpm build passed.
## Reusable Lessons

- None recorded yet.
