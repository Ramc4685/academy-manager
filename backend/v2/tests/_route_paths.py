"""Flatten a FastAPI app's route tree to full path strings.

FastAPI 0.139 changed ``include_router`` to keep an ``_IncludedRouter`` wrapper
in ``app.routes`` instead of eagerly copying the mounted routes (with their
prefix baked in) into the parent router. As a result, iterating ``app.routes``
and reading ``route.path`` no longer surfaces the nested business routes — the
wrappers expose the child routes via ``original_router.routes`` and the mount
prefix via ``include_context.prefix``.

``iter_route_paths`` walks that tree recursively and yields the fully-qualified
path for every concrete route. It also works on FastAPI < 0.139, where every
route already carries a ``.path`` and no ``_IncludedRouter`` wrappers exist.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any


def iter_route_paths(routes: Iterable[Any], prefix: str = "") -> Iterator[str]:
    """Yield the full path of every concrete route under ``routes``."""
    for route in routes:
        if type(route).__name__ == "_IncludedRouter":
            include_context = getattr(route, "include_context", None)
            sub_prefix = prefix + (getattr(include_context, "prefix", "") or "")
            original = getattr(route, "original_router", None)
            if original is not None:
                yield from iter_route_paths(original.routes, sub_prefix)
            continue
        path = getattr(route, "path", None)
        if path is not None:
            yield prefix + path


def route_paths(app: Any) -> set[str]:
    """Return the set of full paths registered on ``app``."""
    return set(iter_route_paths(app.routes))
