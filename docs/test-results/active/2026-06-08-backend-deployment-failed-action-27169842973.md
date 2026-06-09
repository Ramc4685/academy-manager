# backend deployment failed action 27169842973

## Current State

Status: active

## Problem

GitHub Actions backend deployment failed; identify root cause from run logs, fix locally, and verify focused checks.

## Changed Files

- None recorded yet.

## Log

- 2026-06-08T18:01:32 main/NA: Task ledger created.
- 2026-06-08T18:03:06 main/working: Inspected run 27169842973. Backend deploy built/pushed image but Fly reported no listener on 0.0.0.0:8001 and timed out health checks; production smoke then saw 502/503. A newer main production run 27172413218 for a85dde6 is in progress, so checking fresh result before editing.
- 2026-06-08T18:05:05 main/working: Root cause aligned with BLNO production login ledger: Fly machine 5683ed0df35448 had broken outbound network and was replaced by healthy 781960b93e5d18, but the stopped unhealthy machine remained in the app. Removing the stopped no-volume machine so future deploys/proxy routing do not target it.
- 2026-06-08T19:09:07 main/working: Manual production workflow 27174858865 validated successfully but skipped Production Approval/Deploy Backend because production gates still required path-filter changes. Patching production workflow so workflow_dispatch explicitly satisfies approval and deploy conditions while keeping production environment approval.
## Verification

- No verification recorded yet.
- 2026-06-08T18:05:38: Fixed Fly app state by destroying stopped unhealthy machine 5683ed0df35448 (no volume). Verification: flyctl machine list now shows one app machine, 781960b93e5d18, started with 1/1 checks; flyctl checks list shows servicecheck-00-http-8001 passing; production smoke script passed. GitHub run 27172413218 has backend validation/lint passing and is waiting on production approval, so the next deployment attempt has not run yet.
- 2026-06-08T19:09:30: ruby -e 'require "yaml"; YAML.load_file(".github/workflows/production.yml")' parsed the production workflow after the workflow_dispatch deploy-gate patch.
- 2026-06-08T19:31:08: Manual Production run 27175473230 completed successfully after PR #154 workflow_dispatch deploy-gate fix and production approval. Deploy Backend, Deploy Frontend, and Production Smoke passed; live Fly image label GH_SHA=a18a18c.
## Reusable Lessons

- None recorded yet.
