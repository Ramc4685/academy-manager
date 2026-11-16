## README.md (repo root)

- [undocumented] README.md:89-102 (Deployment pipeline) lists seven steps, but `.github/workflows/production.yml` also runs a `sentry-release` job (`production.yml:1049-1117`, `needs: [smoke]`, releases `courtmastr-fastapi@${{ github.sha }}` and `courtmastr-frontend@${{ github.sha }}`) in parallel with `publish-release`. The README does not mention it.
- [wording] README.md:92-93 says Validate covers "backend compile/tests, v2 DDD boundary checks, and Next.js typecheck/lint/build/E2E". The workflow also runs real-Mongo contract tests (`production.yml:167`), ruff/mypy/advisory scans (`production.yml:229`), an OpenAPI drift check, scripts validation (`production.yml:673`) and hook tests (`production.yml:718`). The summary is incomplete, not wrong.
