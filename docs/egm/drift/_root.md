## README.md (repo root)

- [undocumented] README.md:89-102 (Deployment pipeline) lists seven steps, but `.github/workflows/production.yml` also runs a `sentry-release` job (`production.yml:~1050-1117`, `release: courtmastr-frontend@${{ github.sha }}`) between smoke and the release record. The README does not mention it.
- [wording] README.md:92-93 says Validate covers "backend compile/tests, v2 DDD boundary checks, and Next.js typecheck/lint/build/E2E". The workflow also runs real-Mongo contract tests (`production.yml:167`), ruff/mypy lint (`production.yml:229`), dependency vulnerability scans, an OpenAPI drift check (`production.yml:312`), a Worker runtime smoke (`production.yml:352`), a real-auth E2E job and scripts/hook validation. The summary is incomplete, not wrong.
