## README.md (repo root)

- [contract] README.md:139-140 says security disclosures go by email with subject `SECURITY DISCLOSURE`; SECURITY.md:1-6 directs reporters to GitHub "Security -> Report a vulnerability" (private advisory) and has no email or subject-line convention. The two documents give different disclosure channels.
- [undocumented] README.md:89-102 lists the deploy pipeline as seven steps; `.github/workflows/production.yml:1053` defines a `sentry-release` job that is not mentioned. The pipeline also has `backend-advisory` (line 229), `scripts-validate` (line 673), `hook-tests` (line 718) and `ci-gate` (line 733) jobs; the README's "Validate" step does not cover them.
- [wording] README.md:164 says `backend/` is the "FastAPI service" and README.md:165 says `backend/v2/` is the "Production FastAPI app". `backend/` holds only packaging and config (`Dockerfile`, `fly.toml`, `pyproject.toml`, `v2/`, `scripts/`), so the app code lives entirely in `backend/v2/`.
