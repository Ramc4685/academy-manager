# security-dependency-bumps

PR: #1082

## What changed
Clears the critical and high dependency advisories that have failed the nightly strict audit since 2026-10-20 and that would block the next production deploy (including #1071).

Frontend: `next` and `eslint-config-next` 16.3.8 -> 16.4.1 (critical unauthenticated RCE and App Router DoS). Transitive `undici` 7.30.1, `body-parser` 1.20.9 / 2.4.x and `re2js` 2.8.7 via lockfile update. `zod@4` is overridden to ^4.6.7 because @serwist pins 4.4.3. GHSA-mrhx-c7xc-m3w5 is ignored for the dev-only zod 3.x copy under puppeteer-core, which has no patched release.

Backend: `pillow` 12.3.0 -> 13.0.0, `certifi` -> 2026.10.19, `aiohttp` 3.14.4 (with `yarl` 1.25.1, which it now requires), `dnspython` 2.9.0, `filelock` 4.2.1, `pymongo` 4.18.3. Dev: `black` 26.10.1.

CI: the Backend job and the weekly restore drill pin their Mongo service container to `mongo:8.0.34`. Older 8.0 builds refuse to start on the new ubuntu-26.04 runner kernel (SERVER-121912), which has failed the restore drill since 2026-10-19. The floating `mongo:8` tag had also drifted to 8.3, away from production's 8.0.

No app code changes. Supersedes Dependabot PRs #1069, #1074, #1075, #1077, #1078, #1079, #1080, #1081.

## Deploy notes
None. No migrations. The production build still uses `next build --webpack`, so the service worker is still emitted.

## Risk / rollback
The largest jumps are Pillow (a major version, used only to resize academy logos and photos) and Next 16.4 (a minor version). Both are covered by the unit and e2e suites. If uploads or rendering misbehave, revert the PR.
