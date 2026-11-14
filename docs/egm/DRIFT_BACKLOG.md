# EGM drift backlog

Open README-vs-code divergences found by drift reports. Details in `docs/egm/drift/`.

## . (README.md) — drift/_root.md, 2026-11-14
- [stale-not-built] README lists `edge/`, which does not exist.
- [contract] README says Next.js 15; frontend pins 16.4.1.
- [undocumented] Layout omits `mobile/`, `memory/`, `tests/`, `firebase-emulator/`, PROJECT.md, GAPS.md, SECURITY.md.
- [wording] `production.yml` called the "single" control plane; five other workflows exist.
- [wording] Scheduler timezone "set on backend" is only `SCHEDULER_TZ` in fly.toml.
- [wording] Email gate description only partly verified (APP_ENV mapping).

## backend/v2 (backend/v2/README.md) — drift/backend__v2.md, 2026-11-14
- [stale-not-built] README links a plan file that does not exist.
- [missing] Layout omits `composition/`, owner/public/student interfaces and top-level route modules.
- [missing] Layout omits several `shared/` packages.
- [missing] Layout omits several test directories.
- [contract] Identity context lacks `domain/events.py`; use cases are flat files.
- [contract] `TenantScopedRepository` claim only partly verified.
- [contract] CI coverage is `--cov=v2 --cov-fail-under=86`, not 70% on `v2/shared`.
- [contract] Mypy is blocking against a frozen baseline, not advisory.
- [undocumented] CI runs `ruff format --check` and a separate contract-test job.
- [undocumented] Structural tests cover more than layering and event rules.
- [wording] Four interface personas listed; owner, student, public are also mounted.
- [wording] No `testcontainers` reference under tests/contract.
- [wording] "W1A-02" reference no longer appears in identity context.
