## README.md (repo root)

- [undocumented] README.md:83-84 says `academy-next` owns `academy.courtmastr.com/*`. `frontend/wrangler.jsonc:18-25` also routes `*.courtmastr.com/*` (tenant subdomains).
- [undocumented] README.md:89-102 lists seven deploy steps. `.github/workflows/production.yml:1049` (`sentry-release`, after smoke, alongside `publish-release` at `:1119`) creates Sentry releases and is not mentioned.
- [wording] README.md:98 shows `flyctl deploy --remote-only --app courtmastr-academy-api`. `production.yml:961-963` deploys the prebuilt migrate-job image with `--image ... --release-command-timeout 25m --ha=false --app courtmastr-academy-api`; nothing is rebuilt with `--remote-only`.
- [wording] README.md:92-93 describes Validate as compile/tests, DDD boundary checks and Next.js typecheck/lint/build/E2E. `production.yml` also runs real-Mongo contract tests, the OpenAPI snapshot check, Worker runtime smoke (`:352`), real-auth E2E (`:644`) and scripts validation (`:670`).
- [wording] README.md:51 says "managed, multi-region cloud service". `backend/fly.toml:2` pins `primary_region = "ord"` and `production.yml:954-955` forces `--ha=false` (one machine, in-process scheduler).
- [wording] README.md:116-117 says password-provider tokens must be email-verified. `backend/v2/contexts/identity/application/token_claims.py:26-50` requires `email_verified` for every provider and exempts only server-minted `custom` (magic-link) tokens (`:23`, `:46-47`).
- [wording] README.md:121-123 says production email requires `APP_ENV=production`. `backend/v2/composition/digests.py:1049,1079` allows real Resend in `staging` as well as `prod`, and the gate is the resolved settings env, not `APP_ENV` directly.
- [undocumented] README.md:31 and :142 list Google and email/password sign-in only. Server-minted magic-link login exists (`token_claims.py:15-23`).
