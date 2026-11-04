"""WCAG 2.x colour math shared by every surface that paints on a tenant's
``brand_color``: the email button today, the public academy page next.

Pure functions, no I/O. Callers must hand in a validated ``#rgb`` /
``#rrggbb`` string; :func:`readable_button_colors` raises ``ValueError`` on
anything else rather than silently substituting a default, because the
fallback-to-cobalt decision belongs to whoever owns the setting
(:meth:`backend.v2.shared.comms.email_theme.EmailBrand.accent`).

Mirrors ``frontend/lib/design/contrast.mjs`` so a future TypeScript twin
derives the same pair from the same hex.

This function *is* the ``brand-fill`` / ``brand-on`` rule for every surface.
The public academy page brief (docs/design/public-tenant-page/brief.md,
"Contrast guardrails") words rule 3 as "darken toward ink until white passes";
the implemented rule nudges toward whichever text colour is nearer to passing,
which moves the fill less and is what the email ticket specified. Reuse this
function rather than re-deriving from the brief, and align the brief's rule 3
wording to it when that page is built, so both surfaces cannot drift apart.
"""

from __future__ import annotations

import re

WHITE = "#ffffff"
INK = "#0f172a"  # Court Ink; kept literal so this module has no email_theme import.
AA_TEXT = 4.5
_STEP = 0.02
_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def parse_hex(value: str) -> tuple[int, int, int]:
    """``#rgb`` / ``#rrggbb`` → ``(r, g, b)`` in 0..255; ``ValueError`` otherwise."""
    if not isinstance(value, str) or not _HEX.match(value.strip()):
        raise ValueError(f"not a hex colour: {value!r}")
    raw = value.strip()[1:]
    if len(raw) == 3:
        raw = "".join(c * 2 for c in raw)
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def relative_luminance(value: str) -> float:
    """WCAG 2.x relative luminance of an sRGB hex colour."""

    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in parse_hex(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    """Contrast ratio between two hex colours, 1..21, order-independent."""
    la, lb = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _blend(start: str, toward: str, amount: float) -> str:
    (sr, sg, sb), (tr, tg, tb) = parse_hex(start), parse_hex(toward)
    return to_hex(
        (
            round(sr + (tr - sr) * amount),
            round(sg + (tg - sg) * amount),
            round(sb + (tb - sb) * amount),
        )
    )


def readable_button_colors(
    fill: str,
    *,
    dark_ink: str = INK,
    threshold: float = AA_TEXT,
) -> tuple[str, str]:
    """``(background, text)`` for a filled button on ``fill``, meeting WCAG AA.

    1. White text if it reaches ``threshold`` on ``fill``.
    2. Else ``dark_ink`` text if that does.
    3. Else (a narrow band of mid-tones where neither passes) nudge ``fill``
       in 2% steps toward whichever extreme is nearer to passing: toward
       ``dark_ink`` when white was the closer text colour, toward white when
       ``dark_ink`` was, until that text colour clears ``threshold``.

    Raises ``ValueError`` for a non-hex ``fill``; validate first.
    """
    fill = to_hex(parse_hex(fill))
    white_ratio = contrast_ratio(WHITE, fill)
    if white_ratio >= threshold:
        return fill, WHITE
    ink_ratio = contrast_ratio(dark_ink, fill)
    if ink_ratio >= threshold:
        return fill, dark_ink

    text, toward = (WHITE, dark_ink) if white_ratio >= ink_ratio else (dark_ink, WHITE)
    amount = _STEP
    while amount < 1.0:
        adjusted = _blend(fill, toward, amount)
        if contrast_ratio(text, adjusted) >= threshold:
            return adjusted, text
        amount += _STEP
    return toward, text
