# QW3 — Scrub weak example credentials
Status: TODO
Size: XS · Depends on: none · Tracker: ../TRACKER.md

## Problem
Tracked example/seed files ship guessable passwords and the owner's real email, normalizing weak credentials and leaking PII into the public-ish repo.

## Current behavior (verified)
- `backend/.env.example:11-12` — `ADMIN_EMAIL=ramchand4685@gmail.com`, `ADMIN_PASSWORD=Admin@12345`.
- `backend/scripts/import_blno.py:31-32` — hardcoded `COACH_PASSWORD = "Coach@12345"`, `PARENT_PASSWORD = "Parent@12345"` (no env override).
- `backend/scripts/seed_firebase_users.py:21-29` — env-overridable but weak defaults (`Admin@12345` etc.) AND real emails: `ramchand4685@gmail.com`, `gowtham@blno.academy`, `kishore@blno.academy`, `manojedward.btech@gmail.com`.
- `backend/scripts/seed_local.py:67-69` — same weak defaults; prints seeded emails/uids (lines ~1445-1625) but does not print passwords (verified) — no change needed for printing beyond a spot-check.
- `backend/.env.bak` exists on disk (1,145 bytes) but is **untracked** (gitignore `.env.*` covers it) — local-only deletion.

## Implementation steps
1. `.env.example`: `ADMIN_EMAIL=admin@example.com`, `ADMIN_PASSWORD=CHANGE_ME`.
2. `import_blno.py`: read both passwords from env (`BLNO_COACH_PASSWORD` / `BLNO_PARENT_PASSWORD`) and fail fast if unset.
3. `seed_firebase_users.py`: replace real emails with `admin@example.test` / `coach1@example.test` etc. (emulator-only script — confirm via its header before renaming), and change defaults to `CHANGE_ME`-style or require env.
4. `seed_local.py`: change the three defaults to match; leave logging as-is.
5. `rm backend/.env.bak` (local file, not in git).
6. Grep tests/docs for `Admin@12345` and the real emails; update any that reference the old values (e2e seeds may depend on them — align, don't break).

## Verification
- `git grep -i "Admin@12345\|Coach@12345\|Parent@12345\|ramchand4685\|blno.academy"` → only intentional remnants (none in backend/).
- Seed flow still works: run `seed_local.py` with `SEED_ADMIN_PASSWORD` set against local emulator; login succeeds.
- Backend tests + e2e suite green.

## Risks / rollback
- e2e/staging scripts that assume the old seed emails/passwords will break — the grep in step 6 is the guard. Rollback: revert the commit.

## PR checklist
- [ ] Release note if backend/ or frontend/ changed (per AGENTS.md)
- [ ] TRACKER.md updated
- [ ] Plan Status flipped to DONE
