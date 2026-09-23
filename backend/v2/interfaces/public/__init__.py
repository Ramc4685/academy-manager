"""Anonymous public persona: the academy's own marketing page (public tenant page).

Unauthenticated by design, so every route here is (1) tenant-resolved from
the request host by ``TenancyMiddleware`` before anything else, never from
caller input; (2) rate limited in ``shared/http/rate_limit.py``; and (3)
serialised only through the allow-listed DTOs in ``dtos.py``, which
``tests/structural/test_public_page_dto_no_leak.py`` inspects.
"""
