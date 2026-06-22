# open github issue code validity audit

## Current State

Status: active

## Problem

Verify whether GitHub issues #169, #148, and #104 are still valid against the current codebase.

## Changed Files

- None recorded yet.

## Log

- 2026-06-19T23:44:33 main/NA: Task ledger created.

## Verification

- No verification recorded yet.
- 2026-06-19T23:45:44: Read-only code audit completed for GitHub issues #169, #148, and #104. #169 is valid: skill-board reads program_id but unplaced action link drops program_id and return_to query. #148 is valid for create-session dialog: academy timezone query can reset form while open; edit dialog is not affected by academy timezone. #104 is partially valid: students list already has All/Active/Paused/Inactive filters and active_session_count, but it still does not expose assigned session names/session filter in list API/UI. No code changes or tests run.
## Reusable Lessons

- None recorded yet.
