## README.md

- [undocumented] README lines 89-102 (deployment pipeline) list 7 steps. `.github/workflows/production.yml:1057` defines a `sentry-release` job that the README does not mention. The README's "Validate" step (line 92) also omits the real-Mongo contract job (`production.yml:167`), the advisory lint/mypy job (`production.yml:229`), and the `scripts-validate` and `hook-tests` jobs (`production.yml:675`, `production.yml:720`).
