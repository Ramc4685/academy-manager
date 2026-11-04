"""Every (method, path) pair on the real app must be registered exactly once.

FastAPI does not complain when two routers expose the same method and path:
the first one included wins and the second is silently unreachable. That is
how the public page's ``GET/POST /admin/programs`` (#934) shadowed the skill
pathway's program list/create. Tests that mount a single router in isolation
cannot see this, so this check builds the full app via ``create_app()``.
"""

from __future__ import annotations

from collections import Counter

from backend.v2.tests._route_paths import iter_route_methods


def test_no_method_and_path_is_registered_twice() -> None:
    from backend.v2.main import create_app

    app = create_app()
    counts = Counter(iter_route_methods(app.routes))
    duplicates = sorted(pair for pair, n in counts.items() if n > 1)

    assert counts, "route walk found no routes; the helper is broken"
    assert duplicates == [], f"routes registered more than once: {duplicates}"


def test_skill_programs_and_public_page_programs_have_distinct_paths() -> None:
    from backend.v2.main import create_app

    pairs = set(iter_route_methods(create_app().routes))

    # Public page programs keep the bare path; skill programs live under curriculum.
    assert ("GET", "/api/v2/admin/programs") in pairs
    assert ("POST", "/api/v2/admin/programs") in pairs
    assert ("GET", "/api/v2/admin/curriculum/programs") in pairs
    assert ("POST", "/api/v2/admin/curriculum/programs") in pairs
