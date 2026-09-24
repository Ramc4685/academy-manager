"""Mongo backup, retention, scratch restore and verification (roadmap D6).

Automates the manual ``mongodump`` / ``mongorestore`` steps in DEPLOYMENT.md
("Database Backups") and the one-off drill recorded in
``docs/runbooks/blno-launch-ops-proof-2026-06-17.md``. The procedure and the
schedule live in ``docs/runbooks/backup-restore.md``.

Four subcommands::

    # 1. Dump one database to <out-dir>/<db>-<UTC stamp>.archive.gz plus a
    #    sidecar manifest (<archive>.manifest.json) of per-collection
    #    document counts and index names read from the source.
    python backend/scripts/backup_restore.py backup \\
        --uri-env MONGO_URL --db academy_manager --out-dir /backups

    # 2. List (default) or delete (--apply) archives older than --keep-days.
    python backend/scripts/backup_restore.py prune --out-dir /backups --keep-days 30

    # 3. Restore an archive into a DIFFERENT database on a scratch server.
    python backend/scripts/backup_restore.py restore \\
        --archive /backups/academy_manager-20260923T020000Z.archive.gz \\
        --target-uri-env SCRATCH_MONGO_URL \\
        --nsFrom academy_manager --nsTo academy_manager_restore_20260923

    # 4. Compare the restored database with the manifest (exit 1 on mismatch).
    python backend/scripts/backup_restore.py verify \\
        --manifest /backups/academy_manager-20260923T020000Z.archive.gz.manifest.json \\
        --target-uri-env SCRATCH_MONGO_URL --db academy_manager_restore_20260923

Connection strings are only ever read from environment variables named on the
command line (never a flag value), handed to the Mongo tools through a
temporary 0600 ``--config`` file (so they never appear in ``ps``), and every
line this script prints goes through :func:`redact` first.

``restore`` is fenced. It refuses, unless ``--i-know-this-is-prod`` is passed,
when the target env var is named ``PROD_MONGO_*``, when the target host is the
host of any ``PROD_MONGO_*`` env var or listed in ``BACKUP_RESTORE_DENY_HOSTS``,
and when the target database name equals the source. It also refuses any
non-localhost target unless ``--allow-remote-target`` (or the prod flag) is
passed, and it never restores into a database that already holds collections.

Exit codes: 0 ok, 1 verification mismatch or tool failure, 2 refused / bad input.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_REFUSED = 2

ARCHIVE_SUFFIX = ".archive.gz"
MANIFEST_SUFFIX = ".manifest.json"
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_ARCHIVE_RE = re.compile(r"^(?P<db>.+)-(?P<stamp>\d{8}T\d{6}Z)\.archive\.gz$")

#: Hosts that count as "this machine". Anything else is remote.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})
PROD_ENV_PREFIX = "PROD_MONGO_"
DENY_HOSTS_ENV = "BACKUP_RESTORE_DENY_HOSTS"

_USERINFO_RE = re.compile(r"(mongodb(?:\+srv)?://)[^@/\s]+@", re.IGNORECASE)
_SECRET_QUERY_RE = re.compile(
    r"((?:password|tlsCertificateKeyFilePassword|sslPEMKeyPassword|authMechanismProperties)=)[^&\s]+",
    re.IGNORECASE,
)


class Refused(Exception):
    """A guard said no. The message is safe to print (already redacted)."""


# ---------------------------------------------------------------------------
# Redaction and output
# ---------------------------------------------------------------------------


def redact(text: str, secrets: Sequence[str] = ()) -> str:
    """Strip credentials from anything that looks like a Mongo URI.

    ``secrets`` are exact strings (the raw URIs in play) removed wholesale
    first, so a URI in a shape the regexes miss still never reaches output.
    """
    for secret in secrets:
        if secret:
            text = text.replace(secret, redact_uri(secret))
    text = _USERINFO_RE.sub(r"\1***@", text)
    return _SECRET_QUERY_RE.sub(r"\1***", text)


def redact_uri(uri: str) -> str:
    """``mongodb://user:pw@h1,h2/db?x=1`` -> ``mongodb://***@h1,h2/db?x=1``."""
    scheme, sep, rest = uri.partition("://")
    if not sep:
        return "***"
    authority, slash, tail = rest.partition("/")
    if "@" in authority:
        authority = "***@" + authority.rsplit("@", 1)[1]
    return _SECRET_QUERY_RE.sub(r"\1***", f"{scheme}{sep}{authority}{slash}{tail}")


class Out:
    """Every line the script prints passes through here."""

    def __init__(self, secrets: Sequence[str] = ()) -> None:
        self.secrets = [s for s in secrets if s]

    def add_secret(self, secret: str) -> None:
        if secret:
            self.secrets.append(secret)

    def info(self, message: str) -> None:
        print(redact(message, self.secrets), flush=True)

    def error(self, message: str) -> None:
        print(redact(message, self.secrets), file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# URIs and the restore guard
# ---------------------------------------------------------------------------


def uri_hosts(uri: str) -> list[str]:
    """Lower-cased host names (no ports) of a ``mongodb://`` / ``+srv`` URI."""
    _, sep, rest = uri.partition("://")
    if not sep:
        raise ValueError("not a mongodb:// URI")
    authority = rest.split("/", 1)[0].split("?", 1)[0]
    if "@" in authority:
        authority = authority.rsplit("@", 1)[1]
    hosts = []
    for part in authority.split(","):
        part = unquote(part.strip())
        if not part:
            continue
        if part.startswith("["):  # IPv6 literal, optional :port
            host = part[: part.index("]") + 1]
        else:
            host = part.rsplit(":", 1)[0] if part.count(":") == 1 else part
        hosts.append(host.lower())
    if not hosts:
        raise ValueError("URI names no host")
    return hosts


def is_local_host(host: str) -> bool:
    return host in LOCAL_HOSTS or host.endswith(".localhost")


def denied_hosts(environ: Mapping[str, str]) -> set[str]:
    """Hosts of every ``PROD_MONGO_*`` env var plus ``BACKUP_RESTORE_DENY_HOSTS``."""
    denied: set[str] = set()
    for name, value in environ.items():
        if name.startswith(PROD_ENV_PREFIX) and "://" in value:
            with contextlib.suppress(ValueError):
                denied.update(uri_hosts(value))
    for raw in environ.get(DENY_HOSTS_ENV, "").split(","):
        if raw.strip():
            denied.add(raw.strip().lower())
    return denied


def check_restore_target(
    *,
    target_env: str,
    target_uri: str,
    source_db: str,
    target_db: str,
    environ: Mapping[str, str],
    i_know_this_is_prod: bool,
    allow_remote_target: bool,
) -> list[str]:
    """Raise :class:`Refused` unless the restore target is safe.

    Returns the target hosts on success. Pure: everything it reads is passed in.
    """
    hosts = uri_hosts(target_uri)
    if not i_know_this_is_prod:
        if target_env.startswith(PROD_ENV_PREFIX):
            raise Refused(
                f"target env var {target_env} is a {PROD_ENV_PREFIX}* variable; "
                "restoring there needs --i-know-this-is-prod (owner-only)"
            )
        hit = sorted(set(hosts) & denied_hosts(environ))
        if hit:
            raise Refused(
                f"target host {', '.join(hit)} is a production/denylisted host; "
                "restoring there needs --i-know-this-is-prod (owner-only)"
            )
        if target_db == source_db:
            raise Refused(
                f"--nsTo equals --nsFrom ({source_db}); restore into a different "
                "database name (a same-name restore is the owner-only prod procedure)"
            )
        remote = [h for h in hosts if not is_local_host(h)]
        if remote and not allow_remote_target:
            raise Refused(
                f"target host {', '.join(remote)} is not localhost; pass "
                "--allow-remote-target for a scratch cluster you own"
            )
    return hosts


# ---------------------------------------------------------------------------
# Archive names and retention
# ---------------------------------------------------------------------------


def archive_name(db: str, now: dt.datetime) -> str:
    return f"{db}-{now.astimezone(dt.UTC).strftime(STAMP_FORMAT)}{ARCHIVE_SUFFIX}"


def archive_timestamp(name: str) -> dt.datetime | None:
    """The UTC time encoded in an archive file name, or None if not ours."""
    match = _ARCHIVE_RE.match(name)
    if not match:
        return None
    try:
        return dt.datetime.strptime(match["stamp"], STAMP_FORMAT).replace(tzinfo=dt.UTC)
    except ValueError:
        return None


def expired_archives(names: Sequence[str], *, now: dt.datetime, keep_days: int) -> list[str]:
    """Archive names strictly older than ``keep_days`` days before ``now``.

    Uses the stamp in the name, not the file's mtime: copying an archive
    between hosts resets mtime and would reset its retention clock. Files that
    are not ours (no stamp) are never selected.
    """
    if keep_days < 1:
        raise ValueError("--keep-days must be at least 1")
    cutoff = now.astimezone(dt.UTC) - dt.timedelta(days=keep_days)
    selected = []
    for name in sorted(names):
        stamp = archive_timestamp(name)
        if stamp is not None and stamp < cutoff:
            selected.append(name)
    return selected


# ---------------------------------------------------------------------------
# Manifests
# ---------------------------------------------------------------------------

Snapshot = dict[str, dict[str, Any]]


def snapshot_database(db: Any) -> Snapshot:
    """``{collection: {"count": n, "indexes": [names...]}}`` for real collections."""
    result: Snapshot = {}
    for info in db.list_collections(filter={"type": "collection"}):
        name = info["name"]
        if name.startswith("system."):
            continue
        collection = db[name]
        result[name] = {
            "count": collection.count_documents({}),
            "indexes": sorted(index["name"] for index in collection.list_indexes()),
        }
    return dict(sorted(result.items()))


def diff_snapshots(expected: Snapshot, actual: Snapshot) -> list[str]:
    """Human-readable mismatches between a manifest and a restored database."""
    problems = []
    for name in sorted(set(expected) - set(actual)):
        problems.append(f"missing collection: {name}")
    for name in sorted(set(actual) - set(expected)):
        problems.append(f"unexpected collection: {name}")
    for name in sorted(set(expected) & set(actual)):
        want, got = expected[name], actual[name]
        if want.get("count") != got.get("count"):
            problems.append(
                f"count mismatch: {name} expected {want.get('count')} got {got.get('count')}"
            )
        want_idx, got_idx = set(want.get("indexes", [])), set(got.get("indexes", []))
        for index in sorted(want_idx - got_idx):
            problems.append(f"missing index: {name}.{index}")
        for index in sorted(got_idx - want_idx):
            problems.append(f"unexpected index: {name}.{index}")
    return problems


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Mongo tools
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def uri_config_file(uri: str) -> Iterator[Path]:
    """A 0600 YAML ``--config`` file carrying the URI, deleted afterwards."""
    fd, raw_path = tempfile.mkstemp(prefix="mongo-tools-", suffix=".yaml")
    path = Path(raw_path)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"uri: {json.dumps(uri)}\n")
        yield path
    finally:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def run_tool(argv: list[str], out: Out) -> int:
    """Run a Mongo tool, relaying its (redacted) output. Returns the exit code."""
    if shutil.which(argv[0]) is None:
        out.error(f"{argv[0]} not found on PATH (install MongoDB Database Tools)")
        return EXIT_MISMATCH
    completed = subprocess.run(argv, capture_output=True, text=True, check=False)
    for stream in (completed.stdout, completed.stderr):
        for line in stream.splitlines():
            out.info(f"  {argv[0]}: {line}")
    return completed.returncode


def mongo_client(uri: str) -> Any:
    from pymongo import MongoClient

    return MongoClient(uri, serverSelectionTimeoutMS=10_000)


def read_uri(env_name: str, environ: Mapping[str, str]) -> str:
    value = environ.get(env_name, "").strip()
    if not value:
        raise Refused(f"environment variable {env_name} is empty or unset")
    if "://" not in value:
        raise Refused(f"environment variable {env_name} does not hold a mongodb:// URI")
    return value


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_backup(args: argparse.Namespace, environ: Mapping[str, str], out: Out) -> int:
    uri = read_uri(args.uri_env, environ)
    out.add_secret(uri)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.UTC)
    archive = out_dir / archive_name(args.db, now)
    manifest_path = archive.with_name(archive.name + MANIFEST_SUFFIX)

    client = mongo_client(uri)
    try:
        # Counts are taken before the dump. On a live database writes between
        # the two make a later verify differ by those writes; see the runbook.
        collections = snapshot_database(client[args.db])
    finally:
        client.close()
    if not collections:
        out.error(f"database {args.db} has no collections; refusing to write an empty backup")
        return EXIT_REFUSED

    out.info(f"backup: {args.db} ({len(collections)} collections) -> {archive}")
    with uri_config_file(uri) as config:
        code = run_tool(
            [
                "mongodump",
                f"--config={config}",
                f"--db={args.db}",
                f"--archive={archive}",
                "--gzip",
                "--quiet",
            ],
            out,
        )
    if code != 0:
        out.error(f"mongodump failed with exit code {code}")
        with contextlib.suppress(FileNotFoundError):
            archive.unlink()
        return EXIT_MISMATCH
    archive.chmod(0o600)

    manifest = {
        "format": 1,
        "db": args.db,
        "archive": archive.name,
        "created_at": now.isoformat(),
        "source": redact_uri(uri),
        "archive_sha256": sha256_file(archive),
        "archive_bytes": archive.stat().st_size,
        "collections": collections,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest_path.chmod(0o600)
    total = sum(c["count"] for c in collections.values())
    out.info(f"backup: ok, {total} documents; manifest {manifest_path}")
    return EXIT_OK


def cmd_prune(args: argparse.Namespace, environ: Mapping[str, str], out: Out) -> int:
    out_dir = Path(args.out_dir)
    if not out_dir.is_dir():
        out.error(f"{out_dir} is not a directory")
        return EXIT_REFUSED
    names = [p.name for p in out_dir.iterdir() if p.is_file()]
    expired = expired_archives(names, now=dt.datetime.now(dt.UTC), keep_days=args.keep_days)
    verb = "deleting" if args.apply else "would delete (dry run; pass --apply)"
    for name in expired:
        out.info(f"prune: {verb} {name}")
        if args.apply:
            (out_dir / name).unlink()
            with contextlib.suppress(FileNotFoundError):
                (out_dir / (name + MANIFEST_SUFFIX)).unlink()
    out.info(f"prune: {len(expired)} archive(s) older than {args.keep_days} days")
    return EXIT_OK


def cmd_restore(args: argparse.Namespace, environ: Mapping[str, str], out: Out) -> int:
    archive = Path(args.archive)
    if not archive.is_file():
        out.error(f"archive {archive} not found")
        return EXIT_REFUSED
    uri = read_uri(args.target_uri_env, environ)
    out.add_secret(uri)
    hosts = check_restore_target(
        target_env=args.target_uri_env,
        target_uri=uri,
        source_db=args.ns_from,
        target_db=args.ns_to,
        environ=environ,
        i_know_this_is_prod=args.i_know_this_is_prod,
        allow_remote_target=args.allow_remote_target,
    )

    manifest_path = archive.with_name(archive.name + MANIFEST_SUFFIX)
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_sha = manifest.get("archive_sha256")
        if expected_sha and sha256_file(archive) != expected_sha:
            out.error(f"archive checksum does not match {manifest_path.name}; refusing")
            return EXIT_REFUSED

    client = mongo_client(uri)
    try:
        existing = [
            n for n in client[args.ns_to].list_collection_names() if not n.startswith("system.")
        ]
    finally:
        client.close()
    if existing:
        out.error(
            f"target database {args.ns_to} already holds {len(existing)} collection(s); "
            "restore only into an empty database"
        )
        return EXIT_REFUSED

    out.info(f"restore: {archive.name} {args.ns_from}.* -> {args.ns_to}.* on {', '.join(hosts)}")
    with uri_config_file(uri) as config:
        code = run_tool(
            [
                "mongorestore",
                f"--config={config}",
                f"--archive={archive}",
                "--gzip",
                "--quiet",
                f"--nsInclude={args.ns_from}.*",
                f"--nsFrom={args.ns_from}.*",
                f"--nsTo={args.ns_to}.*",
                "--stopOnError",
            ],
            out,
        )
    if code != 0:
        out.error(f"mongorestore failed with exit code {code}")
        return EXIT_MISMATCH
    out.info("restore: ok; now run `verify` against the manifest")
    return EXIT_OK


def cmd_verify(args: argparse.Namespace, environ: Mapping[str, str], out: Out) -> int:
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    uri = read_uri(args.target_uri_env, environ)
    out.add_secret(uri)
    target_db = args.db or manifest["db"]
    client = mongo_client(uri)
    try:
        actual = snapshot_database(client[target_db])
    finally:
        client.close()
    expected: Snapshot = manifest["collections"]
    problems = diff_snapshots(expected, actual)
    total = sum(c["count"] for c in actual.values())
    out.info(
        f"verify: {target_db} vs {manifest.get('archive')}: "
        f"{len(actual)}/{len(expected)} collections, {total} documents"
    )
    for problem in problems:
        out.error(f"verify: {problem}")
    if problems:
        out.error(f"verify: FAILED with {len(problems)} mismatch(es)")
        return EXIT_MISMATCH
    out.info("verify: ok, counts and index names match")
    return EXIT_OK


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)

    backup = sub.add_parser("backup", help="mongodump one database plus a manifest")
    backup.add_argument("--uri-env", default="MONGO_URL", help="env var holding the source URI")
    backup.add_argument("--db", required=True)
    backup.add_argument("--out-dir", required=True)
    backup.set_defaults(func=cmd_backup)

    prune = sub.add_parser(
        "prune", help="delete archives older than --keep-days (dry run by default)"
    )
    prune.add_argument("--out-dir", required=True)
    prune.add_argument("--keep-days", type=int, default=30)
    prune.add_argument("--apply", action="store_true", help="actually delete")
    prune.set_defaults(func=cmd_prune)

    restore = sub.add_parser("restore", help="restore an archive into a different database")
    restore.add_argument("--archive", required=True)
    restore.add_argument("--target-uri-env", default="SCRATCH_MONGO_URL")
    restore.add_argument(
        "--nsFrom", "--ns-from", dest="ns_from", required=True, help="source db name"
    )
    restore.add_argument("--nsTo", "--ns-to", dest="ns_to", required=True, help="target db name")
    restore.add_argument("--allow-remote-target", action="store_true")
    restore.add_argument("--i-know-this-is-prod", action="store_true", help="owner-only")
    restore.set_defaults(func=cmd_restore)

    verify = sub.add_parser("verify", help="compare a database with a backup manifest")
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--target-uri-env", default="SCRATCH_MONGO_URL")
    verify.add_argument("--db", help="database to check (default: the manifest's db)")
    verify.set_defaults(func=cmd_verify)
    return parser


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    env = os.environ if environ is None else environ
    args = build_parser().parse_args(argv)
    out = Out()
    try:
        code: int = args.func(args, env, out)
    except Refused as exc:
        out.error(f"refused: {exc}")
        return EXIT_REFUSED
    except ValueError as exc:
        out.error(f"error: {exc}")
        return EXIT_REFUSED
    except Exception as exc:  # anything else: redacted, non-zero
        out.error(f"error: {type(exc).__name__}: {exc}")
        return EXIT_MISMATCH
    return code


if __name__ == "__main__":
    sys.exit(main())
