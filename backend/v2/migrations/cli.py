"""Command-line entry point for the v2 migrations runner.

``python -m backend.v2.migrations [--dry-run] [--timeout-seconds N]``

Production runs this from the deploy pipeline (see
``docs/runbooks/migrations-rollout.md``): the ``migrate-production`` job in
``.github/workflows/production.yml`` runs ``--dry-run`` on the freshly built
image, and Fly's ``release_command`` (``backend/fly.toml``) runs the apply on
that same image before traffic moves to it. A non-zero exit aborts the deploy.

The apply path delegates to :func:`run_pending_migrations`, so it takes the
same distributed lease as the boot path did and applies the same idempotent
modules. This module only adds reporting, a ``--dry-run`` that touches
nothing, and an overall timeout around the lease wait.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.migrations import runner

log = logging.getLogger("backend.v2.migrations.cli")

#: Default overall budget for the apply path. Longer than the migrations
#: lease TTL (15 min) so a stale lease left by a crashed run can expire and
#: the apply can still proceed inside one invocation.
DEFAULT_TIMEOUT_SECONDS = 20 * 60

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_TIMEOUT = 2


def _emit(event: str, **fields: Any) -> None:
    """One structured ``key=value`` line per event, on stdout, flushed.

    Fly streams release-command stdout into the deploy log; keeping each
    event on one line makes the pending list greppable there.
    """
    rendered = " ".join(f"{key}={value!r}" for key, value in fields.items())
    print(f"migrations event={event} {rendered}".rstrip(), flush=True)


async def pending_versions(db: AsyncIOMotorDatabase[Any]) -> list[str]:
    """Versions discovered on disk but not recorded in the registry."""
    applied = {doc["version"] async for doc in db[runner.REGISTRY_COLLECTION].find({})}
    return [m.version for m in runner._discover_migrations() if m.version not in applied]


async def run(
    db: AsyncIOMotorDatabase[Any],
    *,
    dry_run: bool,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> int:
    """Report pending migrations and, unless ``dry_run``, apply them.

    Returns a process exit code. Never raises for a migration failure or a
    timeout; both are reported and mapped to a non-zero code so the deploy
    pipeline stops.
    """
    try:
        pending_before = await pending_versions(db)
    except Exception as exc:  # reported, then non-zero exit
        log.exception("Could not read the migrations registry")
        _emit("registry_read_failed", error=f"{type(exc).__name__}: {exc}")
        return EXIT_FAILED

    _emit("pending_before", count=len(pending_before), versions=pending_before)

    if dry_run:
        _emit("dry_run", applied=[], note="nothing written")
        return EXIT_OK

    try:
        applied = await asyncio.wait_for(runner.run_pending_migrations(db), timeout=timeout_seconds)
    except TimeoutError:
        log.error("Migrations did not finish within %.0fs", timeout_seconds)
        _emit("timeout", timeout_seconds=timeout_seconds, pending_before=pending_before)
        return EXIT_TIMEOUT
    except Exception as exc:  # reported, then non-zero exit
        log.exception("Migration run failed")
        _emit("failed", error=f"{type(exc).__name__}: {exc}")
        try:
            still_pending = await pending_versions(db)
        except Exception:  # best-effort diagnostics only
            still_pending = ["<registry unreadable>"]
        _emit("pending_after", count=len(still_pending), versions=still_pending)
        return EXIT_FAILED

    pending_after = await pending_versions(db)
    _emit("applied", count=len(applied), versions=applied)
    _emit("pending_after", count=len(pending_after), versions=pending_after)
    if pending_after:
        # Another holder applied nothing and the lease-loser path returned with
        # work still outstanding; treat as a failure rather than a clean deploy.
        _emit("failed", error="migrations still pending after run")
        return EXIT_FAILED
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.v2.migrations",
        description="Apply pending v2 migrations (or list them with --dry-run).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List pending migrations and exit without applying anything.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=(
            "Overall budget for the apply, including waiting for the migrations "
            f"lease (default {DEFAULT_TIMEOUT_SECONDS}s)."
        ),
    )
    return parser


async def _main_async(args: argparse.Namespace) -> int:
    # Imported here so tests of ``run`` never construct settings or a client.
    from motor.motor_asyncio import AsyncIOMotorClient

    from backend.v2.shared.config import get_settings

    settings = get_settings()
    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(
        settings.mongo_url, serverSelectionTimeoutMS=20_000
    )
    try:
        db = client[settings.mongo_db]
        _emit("start", db=settings.mongo_db, dry_run=args.dry_run)
        return await run(db, dry_run=args.dry_run, timeout_seconds=args.timeout_seconds)
    finally:
        client.close()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_main_async(args))
    except Exception as exc:  # settings/connection errors
        log.exception("Migrations CLI could not start")
        _emit("startup_failed", error=f"{type(exc).__name__}: {exc}")
        return EXIT_FAILED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
