## README.md

- [undocumented] README.md:83-84 says the `academy-next` Worker owns `academy.courtmastr.com/*`. `frontend/wrangler.jsonc:18-25` also routes `*.courtmastr.com/*` (zone `courtmastr.com`) to the Worker. The wildcard tenant route is not mentioned.
- [undocumented] README.md:89-102 lists seven pipeline steps. `.github/workflows/production.yml:1049` has a `sentry-release` job (backend and frontend Sentry releases) that runs after smoke and is not listed.
