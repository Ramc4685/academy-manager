# Academy Manager Plans.md

作成日: 2026-05-17

> **Context:** All Wave 0–4 ticket code is landed. This plan organises the
> in-progress working-tree changes (24 modified + 10 untracked files) into
> clean commits and verifies CI gates. All changes are tested and working;
> the work here is commit-organisation and CI confirmation, not new
> implementation.
>
> Execution note: tasks within each Phase are sequential (shared working tree).
> Use `/harness-work all --sequential` or run phase-by-phase.

---

## Phase 1: Commit backend changes

| Task | 内容 | DoD | Depends | Status |
|------|------|-----|---------|--------|
| 1.1 | Commit /me BFF endpoint + auth infrastructure [tdd:skip:already-implemented-and-passing] | `git log --oneline -1` shows commit; `backend/.venv/bin/python -m pytest backend/v2/tests/interface/ -q` exits 0 | - | cc:TODO |
| 1.2 | Commit migration index fixes (0010–0060) [tdd:skip:migration-scripts-no-new-logic] | `git log --oneline -1` shows commit; no pytest regression (`pytest backend/v2/tests -q` green) | 1.1 | cc:TODO |
| 1.3 | Commit backend contract + interface test files [tdd:skip:tests-are-the-artifact] | `git log --oneline -1` shows commit; `pytest backend/v2/tests/contract/ backend/v2/tests/interface/ -q` exits 0 with all new tests collected | 1.2 | cc:TODO |

---

## Phase 2: Commit frontend changes

| Task | 内容 | DoD | Depends | Status |
|------|------|-----|---------|--------|
| 2.1 | Commit frontend auth plumbing: firebase emulator support, /me API client, usePersonaAuth hook, post-login role routing, persona layout auth guards, suppressHydrationWarning [tdd:skip:already-implemented-and-passing] | `git log --oneline -1` shows commit; `pnpm --dir frontend typecheck` exits 0 | Phase 1 | cc:TODO |
| 2.2 | Commit coach persona tab pages: sessions list + profile page + today error-state hardening [tdd:skip:already-implemented-and-passing] | `git log --oneline -1` shows commit; `pnpm --dir frontend build` exits 0 | 2.1 | cc:TODO |
| 2.3 | Commit login visual polish + PWA icons + next.config BFF proxy + tailwind + globals.css + README + test_result.md + LICENSE [tdd:skip:assets-and-config] | `git log --oneline -1` shows commit; `pnpm --dir frontend build` exits 0; `git status` is clean | 2.2 | cc:TODO |

---

## Phase 3: Full verification

| Task | 内容 | DoD | Depends | Status |
|------|------|-----|---------|--------|
| 3.1 | Run full test suite: backend pytest + frontend typecheck + build + E2E [tdd:skip:verification-not-implementation] | `pytest backend/v2/tests -q` ≥ 121 passed; `pnpm --dir frontend typecheck` exits 0; `pnpm --dir frontend build` exits 0; `pnpm --dir frontend e2e` ≥ 6 passed | Phase 2 | cc:TODO |
