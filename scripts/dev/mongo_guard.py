"""Shared local-only Mongo URL guard for destructive scripts/dev utilities.

Every destructive or data-mutating dev script must call
``assert_local_mongo_url`` before connecting. The guard rejects:

- any scheme other than plain ``mongodb`` (``mongodb+srv`` resolves remote
  DNS seed lists and is never local);
- multi-host seed lists (``mongodb://127.0.0.1,prod-host/...``) where any
  host is non-local — pymongo connects to *all* hosts, not just the first;
- any host outside the local allowlist (loopback or the docker-compose
  ``mongo`` service).
"""

from __future__ import annotations

import urllib.parse

LOCAL_MONGO_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "mongo"})


def _host_from_netloc_part(part: str) -> str:
    """Extract the bare host from one ``host[:port]`` netloc entry."""

    part = part.strip()
    if part.startswith("["):
        # IPv6 literal, e.g. [::1]:27017
        end = part.find("]")
        return part[1:end].lower() if end != -1 else ""
    return part.split(":", 1)[0].lower()


def split_seed_list_hosts(mongo_url: str) -> list[str]:
    """Return every host in the URL's (possibly comma-separated) seed list."""

    parsed = urllib.parse.urlparse(mongo_url)
    netloc = parsed.netloc
    if "@" in netloc:
        netloc = netloc.rsplit("@", 1)[1]
    return [_host_from_netloc_part(part) for part in netloc.split(",")]


def assert_local_mongo_url(mongo_url: str) -> None:
    """Exit unless every host in the Mongo URL targets local staging."""

    parsed = urllib.parse.urlparse(mongo_url)
    if parsed.scheme != "mongodb":
        raise SystemExit(
            "REFUSING: Mongo URL must use the plain 'mongodb' scheme for "
            f"local staging; got scheme={parsed.scheme!r}"
        )
    hosts = split_seed_list_hosts(mongo_url)
    if not hosts or any(not host for host in hosts):
        raise SystemExit(
            f"REFUSING: Mongo URL has an empty or malformed host list: {parsed.netloc!r}"
        )
    non_local = [host for host in hosts if host not in LOCAL_MONGO_HOSTS]
    if non_local:
        raise SystemExit(
            "REFUSING: Mongo URL must target local staging only; got "
            f"host={non_local[0]!r}"
        )
