## README.md

- [undocumented] README lines 87-102 (Deployment pipeline, 7 steps) omit the `sentry-release` job, which runs after smoke on main pushes (`.github/workflows/production.yml:1057`, `needs: [smoke]`). The README lists only the `publish-release` step (`production.yml:1127`).
