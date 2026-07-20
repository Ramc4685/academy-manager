# QW4 — Delete orphaned legacy bytecode dirs
Status: TODO
Size: XS · Depends on: none · Tracker: ../TRACKER.md

## Problem
Audit flagged orphaned `backend/routers/` + `backend/services/` (`__pycache__`-only), an empty `backend/tests/`, and stray `backend/uv.lock`.

## Current behavior (verified 2026-07-20)
- `backend/routers/`, `backend/services/`, `backend/tests/` **no longer exist on disk** — already cleaned up since the audit snapshot. Nothing tracked in git for any of them (`git ls-files` empty).
- `backend/uv.lock` exists locally: 8 lines, contains only the virtual root package (near-empty, useless). It is **gitignored** (`.gitignore:` `backend/uv.lock`) and untracked — local-only artifact.
- Stray `backend/__pycache__/` exists at the backend root (untracked; `.gitignore` lines 19-20 cover `__pycache__/` and `*.pyc`).
- `backend/.env.bak` deletion is handled in QW3.

## Implementation steps
Mostly already done; remaining is local hygiene plus a guard:
1. `rm -rf backend/__pycache__ backend/uv.lock` (local, untracked).
2. `find backend -name "__pycache__" -not -path "*/.venv/*" | head` — confirm no other stray bytecode dirs outside virtualenvs.
3. Confirm `.gitignore` already covers `__pycache__/`, `*.pyc`, `backend/uv.lock` (it does — no edit needed).
4. Update TRACKER.md: mark QW4 DONE with note "dirs already absent; local artifacts removed".

## Verification
- `git status --porcelain backend/` → clean.
- `ls backend/` → no `routers`, `services`, `tests`, `uv.lock`, `__pycache__`.
- `cd backend && pytest v2/tests -q` still green (nothing imported from removed paths).

## Risks / rollback
- None meaningful — only untracked local files are removed; `uv.lock` regenerates if anyone runs `uv` (and stays gitignored).

## PR checklist
- [ ] Release note if backend/ or frontend/ changed (per AGENTS.md)
- [ ] TRACKER.md updated
- [ ] Plan Status flipped to DONE
