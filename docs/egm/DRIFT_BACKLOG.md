# EGM drift backlog

Open divergences between folder READMEs and code, from `docs/egm/drift/*.md`. Fixing them is separate work.

## README.md (repo root)

- [stale-not-built] README layout lists `edge/`, which does not exist.
- [undocumented] Layout omits `mobile/`, `tests/`, `firebase-emulator/`, `memory/` and `.claude/`.
- [undocumented] Native Capacitor apps and `mobile-build-check.yml` are not mentioned.
- [undocumented] Pipeline section omits the `migrate-production` dry-run job in `production.yml`.
- [wording] README says Next 15 in two places; `frontend/package.json` pins Next 16.
- [wording] `production.yml` is called the single control plane, but other workflows exist.
- [wording] Timezone is described as a global backend setting; it is only `SCHEDULER_TZ` in `backend/fly.toml`.
