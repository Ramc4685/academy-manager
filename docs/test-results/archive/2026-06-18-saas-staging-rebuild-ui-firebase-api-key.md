# saas staging rebuild ui firebase api key

## Current State

Status: active

## Problem

rebuild-ui rebuilt the frontend with missing Firebase web API key, causing auth/invalid-api-key client crash on post-login.

## Changed Files

- None recorded yet.

## Log

- 2026-06-18T09:53:42 main/NA: Task ledger created.

## Verification

- No verification recorded yet.
- 2026-06-18T09:56:29: Root cause: scripts/dev/saas_staging.sh rebuild-ui did not pass NEXT_PUBLIC_FIREBASE_API_KEY into the Docker build, unlike up/up-dev, so the rebuilt frontend crashed with Firebase auth/invalid-api-key. Fixed rebuild-ui to resolve and pass the key. Verified bash -n, rebuilt frontend container successfully, checked rebuilt chunks do not contain blank/dummy API key markers, and Playwright loaded /post-login -> /login with no console/page errors.
## Reusable Lessons

- None recorded yet.
