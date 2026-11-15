# EGM drift backlog

Open divergences between folder READMEs and code, from `docs/egm/drift/*.md`. Fixing them is separate work.

## README.md (`docs/egm/drift/_root.md`)

- [undocumented] README.md:89-102 deploy steps omit the `sentry-release` job in `.github/workflows/production.yml`.
- [wording] README.md:92-93 Validate step undersells the job: it also runs real-Mongo contract tests, lint, the OpenAPI drift check, the Worker runtime smoke, real-auth E2E and scripts validation.
