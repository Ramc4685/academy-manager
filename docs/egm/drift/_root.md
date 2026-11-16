## README.md

- [undocumented] README.md:92-102 (Deployment pipeline) lists seven stages, but `.github/workflows/production.yml:1057` also defines a `sentry-release` job (needs `smoke`), which runs before `publish-release` at `production.yml:1127`. The README does not mention it.
- [wording] README.md:92-93 describes Validate as "backend compile/tests, v2 DDD boundary checks, and Next.js typecheck/lint/build/E2E". The workflow also has a real-Mongo contract job (`production.yml:167`), an advisory job (`production.yml:229`), a scripts-validate job (`production.yml:675`), a hook-tests job (`production.yml:720`) and a `ci-gate` job (`production.yml:735`).
- [wording] README.md:83-84 says the `academy-next` Worker owns `academy.courtmastr.com/*` through a Worker Route. `frontend/wrangler.jsonc:18-24` also routes `*.courtmastr.com/*`, so the claim understates the route set.
