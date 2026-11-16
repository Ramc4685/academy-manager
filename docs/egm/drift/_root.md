## README.md

- [wording] README:121-123 says production email requires `APP_ENV=production`; code also allows `staging` (`backend/v2/contexts/communications/infrastructure/resend_send_port.py:14`).
- [wording] README:173 says `scripts/` holds "importers"; no importer scripts exist under `scripts/` (`scripts/dev`, `scripts/ops`, `scripts/prod` hold audit, backfill, repair, seed and release tools).
- [undocumented] README:89-102 lists the pipeline stages without the `sentry-release` job, which runs between smoke and release record (`.github/workflows/production.yml:1057`).
