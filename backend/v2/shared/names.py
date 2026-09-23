"""Name normalisation shared by every people search and sort.

``full_name_key`` started life in the admin student directory
(``contexts/enrollment/application/use_cases/admin_directory.py``), where it
keys the directory cursor. The People CRM family index (spec
``docs/design/people-crm/engineering-spec.md`` §3.2, "Name matching uses
``full_name_key``") must match names exactly the same way, and contexts may
not import each other, so the one definition lives here.
"""

from __future__ import annotations

import re
import unicodedata


def full_name_key(value: str) -> str:
    """Return the stable sort/search key shared by admin people views.

    Accents folded, case folded, runs of whitespace collapsed.
    """
    normalized = unicodedata.normalize("NFKD", value)
    ascii_folded = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", ascii_folded.lower()).strip()
