## README.md (repo root)

- [stale-not-built] README.md:162 lists `edge/` ("Retired Cloudflare Worker router kept for historical reference"); no `edge/` directory exists in the repo (`ls edge` fails, `git ls-files edge` empty).
- [stale-not-built] README.md:96-98 step 6 "Release record — publish a non-moving, SHA-bearing `deploy-*` GitHub Release"; `.github/workflows/production.yml` has no release-publishing job (no `gh release`/`deploy-*` tag). After the smoke job (~line 1027-1047) the only follow-on job is `sentry-release` (~line 1049), which creates Sentry releases, not a GitHub Release.
- [contract] README.md:74 and :161 state Next.js 15; `frontend/package.json:37` pins `"next": "16.4.1"` (React 19.3.0 at line 38 is consistent). The README line 90 pipeline text is otherwise fine.
