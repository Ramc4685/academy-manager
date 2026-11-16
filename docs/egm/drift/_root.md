## README.md

- [undocumented] README lines 89-102 (deployment pipeline, 7 steps): `.github/workflows/production.yml:1057` defines a `sentry-release` job (needs `smoke`, runs on main) that is not in the list. `.github/workflows/production.yml:1127` `publish-release` runs in parallel with it, not after it.
- [wording] README lines 121-123 (production email requires `APP_ENV=production`): `backend/v2/contexts/communications/infrastructure/resend_send_port.py:14` also enables the Resend sender when `APP_ENV=staging`. The enable flag is `EMAIL_DELIVERY_ENABLED=true` (`stub_send_port.py:6`), which the README does not name.
- [wording] README lines 92-93 (validate: "v2 DDD boundary checks"): `.github/workflows/production.yml:157` is an import-linter step. The `backend-contract-real-mongo` (line 167), `backend-advisory` (line 229), `scripts-validate` (line 675) and `hook-tests` (line 720) jobs are not mentioned.
