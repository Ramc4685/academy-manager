"""``PLATFORM_SITE_URL`` (email footer "Powered by CourtMastr") is hand-mirrored
from ``frontend/lib/brand.ts`` ``publicSiteUrl`` (public page footer credit).
If the marketing domain moves in one place only, emails and the public page
point at different sites; this is the test that notices."""

from __future__ import annotations

import pathlib
import re

from backend.v2.shared.comms.email_theme import PLATFORM_SITE_URL

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
BRAND_TS = REPO_ROOT / "frontend" / "lib" / "brand.ts"


def test_email_platform_site_url_matches_frontend_brand() -> None:
    match = re.search(r'publicSiteUrl:\s*"([^"]+)"', BRAND_TS.read_text(encoding="utf-8"))
    assert match, f"publicSiteUrl not found in {BRAND_TS}"
    assert match.group(1) == PLATFORM_SITE_URL
