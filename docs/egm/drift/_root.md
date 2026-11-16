## README.md (repo root)

- [undocumented] README.md:83-84 says `academy-next` owns `academy.courtmastr.com/*`. `frontend/wrangler.jsonc:18-25` also routes `*.courtmastr.com/*` (tenant subdomains).
- [undocumented] README.md:89-102 lists seven deploy steps. `.github/workflows/production.yml:1049` (`sentry-release`, runs after smoke alongside `publish-release` at `:1119`) creates the Sentry release and is not mentioned.
- [wording] README.md:98 shows `flyctl deploy --remote-only --app courtmastr-academy-api`. `production.yml:961-963` deploys the prebuilt image from the migrate job with `--image ... --ha=false` (release-command timeout also set).
- [wording] README.md:92-93 describes Validate as compile/tests, DDD boundary checks and Next.js typecheck/lint/build/E2E. `production.yml` also runs real-Mongo contract tests (`:167`), the OpenAPI drift check, Worker runtime smoke (`:352`), real-auth smoke E2E (`:639`) and scripts validation (`:673`).
- [wording] README.md:51 says "managed, multi-region cloud service". `backend/fly.toml:2` pins `primary_region = "ord"` and `production.yml:954-955` forces `--ha=false` (single machine, in-process scheduler).
