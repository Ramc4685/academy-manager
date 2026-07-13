# Fix flaky admin reports route matrix

PR: #301

## What changed

Corrected the network-stubbed admin reports E2E coverage so asynchronous report feeds use their real response shapes and cannot crash after the initial mount assertion passes.

## Deploy notes

none

## Risk / rollback

Test-only change. If CI behavior regresses, revert PR #301 to restore the previous route-matrix fixture and assertions.
