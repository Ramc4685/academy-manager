# Axe accessibility gate in nightly e2e, plus three parent home fixes it found (D11)

PR: #TBD

## What changed

- **Axe gate.** New Playwright spec `frontend/e2e/specs/a11y-axe.spec.ts` runs axe-core (`@axe-core/playwright` 4.13.0, dev dependency) with the `wcag2a` and `wcag2aa` tags, colour contrast included, over the public academy page (served by the existing `public-academy-stub.mjs`), parent home with a balance due, the admin dashboard and coach Today, all under browser-side stubs (persona inbox polls stubbed). Any `serious` or `critical` violation fails the run.
- **Allowlist that ratchets.** Known violations go in the spec's `ALLOWLIST`, one entry per surface + rule id + CSS selector, each with a linked issue. An entry whose violation no longer occurs also fails the run, so fixes must delete their entry. The list lands empty.
- **Self-check.** One test injects a 2.3:1 text element and asserts the gate reports it, so a broken axe setup cannot pass silently.
- **Own Playwright project and CI job.** The spec runs only in a new `a11y-chromium` project (Pixel 7); `chromium-mobile` and `webkit-mobile` ignore it, so the production PR matrix is unchanged. `.github/workflows/nightly-e2e.yml` gains a `Frontend E2E Accessibility (axe)` job (daily, on demand, and on PRs that touch `frontend/components/**` or `frontend/e2e/**`). A new `changes` job keeps WebKit on its old PR trigger, so a components-only PR does not start a WebKit run. The local pre-push gate treats `a11y-chromium` as nightly-only, like WebKit (`--full` or `PRE_PUSH_E2E_ALL=1` includes it).
- **Parent home fixes (found by the gate).** The balance banner's detail line (4.41:1) and the primary action card's body line (4.27:1 on the register card) dropped their 80% opacity and now pass 4.5:1. Child card rows now nest correctly inside their `<dl>`: the icon sits inside the `<dt>` and the meta line is a second `<dd>`, which fixes axe `definition-list` and `dlitem`. The layout looks the same.

## Deploy notes

- No backend change, no migration, no new route. Frontend-only.
- The new CI job is advisory (not a required check), like the WebKit job.

## Risk / rollback

- Low. Parent home changes are markup and opacity only. The gate is outside the required checks.
- Rollback: revert the PR.
