## README.md

- [wording] README.md:51 says the service "runs as a managed, multi-region cloud service". `backend/fly.toml:2` sets a single `primary_region = "ord"`, and README.md:63 and :76 also say region `ord`. The Fly app is single-region.
- [undocumented] README.md:161-174 (Layout) omits `docs/egm/` and other top-level files that exist, such as `GAPS.md`, `PROJECT.md`, `SECURITY.md`, `Makefile` and the `docker-compose*.yml` files. `docs/egm/drift/` is new and the docs/ line (README.md:172) does not mention it. Minor.
