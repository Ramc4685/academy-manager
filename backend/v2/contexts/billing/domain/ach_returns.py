"""Provider-neutral ACH/Nacha return-code helpers."""

from __future__ import annotations

import re

_R_CODE_RE = re.compile(r"\bR([0-9]{2})\b", re.IGNORECASE)


def normalize_nacha_return_code(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    direct = _R_CODE_RE.search(text.replace("_", " ").replace("-", " "))
    if direct is not None:
        return f"R{direct.group(1)}".upper()
    return None
