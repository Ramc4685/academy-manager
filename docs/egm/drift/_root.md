## README.md (repo root)

- [wording] README:98 says backend deploy is `flyctl deploy --remote-only --app courtmastr-academy-api`; actual command is `flyctl deploy --image <migrate-production image> --release-command-timeout 25m --ha=false --app courtmastr-academy-api` (nothing rebuilt) at `.github/workflows/production.yml:961-963`.
- [wording] README:51 calls the service "managed, multi-region"; the API is a single Fly machine in one region (`backend/fly.toml:2` `primary_region = "ord"`, `--ha=false` at `.github/workflows/production.yml:963`).
