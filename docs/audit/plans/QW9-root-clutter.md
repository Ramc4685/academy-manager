# QW9 — Move tracked repo-root clutter
Status: TODO
Size: XS · Depends on: none · Tracker: ../TRACKER.md

## Problem
Screenshots, scratch HTML, session logs, and old test artifacts are tracked at the repo root, polluting checkouts and diffs.

## Current behavior (verified via `git ls-files`)
Tracked clutter:
- Root images: `production-admin-login-redirect.png`, `reports-dashboard-full.png`, `reports-deposit-slip.png`, `reports-refunds.png`, `reports-revenue-by-category.png`.
- `academy-financial-flows.html`, `Plans.md`, `test_result.md`.
- `output/` — 7 tracked playwright/screenshot PNGs (plus untracked `output/playwright/staging-child-added-*.png`).
- `.playwright-cli/` — 15 tracked console logs / page snapshots (June 17 session artifacts).
- `test_reports/` — 10 tracked iteration JSON/XML files + `.gitkeep`s.
- Related-but-keep-for-now: `tests/test_test_result_cli.py` (tests the `test_result.md` CLI — decide together with `test_result.md`), `memory/PRD.md`.
No Makefile/CI references to `test_reports`, `Plans.md`, or `academy-financial-flows.html` found (grep verified).

## Implementation steps
1. Delete from git (history keeps them; no doc value): root PNGs, `output/`, `.playwright-cli/`, `test_reports/` — `git rm -r --cached` is not enough; use `git rm` so working tree is clean too.
2. `Plans.md` → move to `docs/` (or `.planning/`) if still current, else delete; `academy-financial-flows.html` → `docs/` if referenced anywhere, else delete.
3. Decide `test_result.md` + `tests/test_test_result_cli.py` as a pair: if the CLI is dead, delete both; otherwise leave (out of scope — note decision in PR).
4. Append to `.gitignore`: `output/`, `.playwright-cli/`, `test_reports/`, `/*.png` (root-level only; leading slash keeps app assets unaffected).
5. `git status` after: previously-untracked `output/playwright/staging-child-added-*.png` should now be ignored.

## Verification
- `git ls-files | grep -E "^(output|\.playwright-cli|test_reports)/|^[^/]+\.png$"` → empty.
- `git status --porcelain` shows no newly-untracked noise (ignores working).
- CI fully green (nothing referenced the removed paths).

## Risks / rollback
- Low: artifacts only. If something did reference a removed file, CI catches it; `git revert` restores.

## PR checklist
- [ ] Release note if backend/ or frontend/ changed (per AGENTS.md)
- [ ] TRACKER.md updated
- [ ] Plan Status flipped to DONE
