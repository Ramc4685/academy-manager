"""Single source of truth for how outbound email looks.

Every renderer (identity invites, billing notices, digests, welcome mail)
imports its colours, font, shell and button from here so all mail reads as one
product and matches the app's Rally palette (frontend/tailwind.config.ts).

Email-client constraints: inline styles only, literal hex, no ``<style>``
block, no web fonts (Manrope is first in the stack and degrades to the system
sans everywhere it is not installed).

This module lives in ``shared`` so contexts can use it without importing the
composition root (ADR-0005).
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass
from typing import Literal

FONT_STACK = (
    "Manrope, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
)
INK = "#0f172a"
MUTED = "#64748b"
LINE = "#e2e8f0"
PAPER = "#f8fafc"
COBALT = "#2563eb"
COBALT_HOVER = "#1d4ed8"
COBALT_SOFT = "#eff6ff"
VOLT = "#facc15"
VOLT_SOFT = "#fef9c3"
NIGHT = "#0a0f1c"
GREEN_BG, GREEN_FG = "#ecfdf5", "#065f46"
AMBER_BG, AMBER_FG = "#fffbeb", "#92400e"
RED_BG, RED_FG, RED_BORDER = "#fef2f2", "#991b1b", "#fecaca"
WHATSAPP_GREEN = "#25d366"
MAX_WIDTH = 560

_HEX_COLOUR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


@dataclass(frozen=True, slots=True)
class EmailBrand:
    """What the shell needs to know about the sending academy."""

    academy_name: str
    brand_color: str | None = None
    logo_url: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None

    def accent(self) -> str:
        """The academy's colour if it is a valid hex, else cobalt. Free text
        from the settings form must never reach a style attribute."""
        candidate = (self.brand_color or "").strip()
        return candidate.lower() if _HEX_COLOUR.match(candidate) else COBALT


def shell(
    *,
    brand: EmailBrand,
    inner_html: str,
    date_label: str | None = None,
    footer_html: str = "",
) -> str:
    """Header (logo or name + optional date), a brand rule with a volt accent,
    the body, then a footer naming the academy with its contact details."""
    accent = brand.accent()
    safe_name = _html.escape(brand.academy_name)
    if brand.logo_url:
        identity = (
            f'<img src="{_html.escape(brand.logo_url, quote=True)}" alt="{safe_name}" '
            f'height="32" style="height:32px;max-width:200px;display:block;" />'
        )
    else:
        identity = (
            f'<span style="font-size:17px;font-weight:700;color:{INK};'
            f'letter-spacing:-0.01em;">{safe_name}</span>'
        )
    date_html = (
        f'<span style="font-size:12px;color:{MUTED};float:right;padding-top:6px;">'
        f"{_html.escape(date_label)}</span>"
        if date_label
        else ""
    )
    contact_bits = [b for b in (brand.contact_email, brand.contact_phone) if b]
    contact = " &middot; ".join(_html.escape(b) for b in contact_bits) if contact_bits else ""
    contact_html = f"<br />{contact}" if contact else ""
    return (
        f'<div style="font-family:{FONT_STACK};max-width:{MAX_WIDTH}px;margin:0 auto;'
        f'color:{INK};font-size:15px;line-height:1.5;">'
        f'<div style="padding:4px 0 12px;margin-bottom:0;overflow:hidden;">'
        f"{identity}{date_html}</div>"
        f'<div style="height:3px;background:{accent};margin-bottom:20px;">'
        f'<div style="height:3px;width:48px;background:{VOLT};"></div></div>'
        f"{inner_html}"
        f"{footer_html}"
        f'<p style="font-size:12px;color:{MUTED};margin:28px 0 0;border-top:1px solid {LINE};'
        f'padding-top:12px;">Sent by {safe_name}{contact_html}</p>'
        "</div>"
    )


def button(
    label: str,
    url: str,
    *,
    accent: str = COBALT,
    variant: Literal["primary", "secondary"] = "primary",
) -> str:
    safe_url = _html.escape(url, quote=True)
    safe_label = _html.escape(label)
    if variant == "primary":
        style = f"background:{accent};color:#ffffff;border:1px solid {accent};"
    else:
        style = f"background:#ffffff;color:{INK};border:1px solid #cbd5e1;"
    return (
        f'<a href="{safe_url}" style="{style}font-size:14px;font-weight:600;'
        f"padding:10px 18px;border-radius:8px;text-decoration:none;display:inline-block;"
        f'white-space:nowrap;">{safe_label}</a>'
    )


def chip(text: str, *, bg: str, fg: str) -> str:
    return (
        f'<span style="background:{bg};color:{fg};font-size:11px;font-weight:600;'
        f'padding:2px 8px;border-radius:10px;white-space:nowrap;">{_html.escape(text)}</span>'
    )


_SYMBOLS = {"USD": "$", "CAD": "$", "AUD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}


def format_money(cents: int, currency: str) -> str:
    """``6000, "usd"`` → ``$60.00``. Codes without a symbol map render as
    ``CHF 5.00`` so nothing is ever shown as a wrong currency."""
    code = (currency or "USD").upper()
    sign = "-" if cents < 0 else ""
    amount = f"{abs(cents) / 100:,.2f}"
    symbol = _SYMBOLS.get(code)
    return f"{sign}{symbol}{amount}" if symbol else f"{sign}{code} {amount}"


_BLOCK_TAGS = re.compile(r"</?(?:p|div|h[1-6]|tr|li|br)\b[^>]*>", re.I)
_CELL_END = re.compile(r"</t[dh]>", re.I)
_ANCHOR = re.compile(r'<a\b[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \r\f\v]+")
_BLANKS = re.compile(r"\n{3,}")


def html_to_text(html_body: str) -> str:
    """A readable plain-text twin: links become ``label (url)``, block tags
    become newlines, table cells become tabs, entities are decoded."""
    text = _ANCHOR.sub(lambda m: f"{m.group(2)} ({_html.unescape(m.group(1))})", html_body)
    text = _CELL_END.sub("\t", text)
    text = _BLOCK_TAGS.sub("\n", text)
    text = _TAG.sub("", text)
    text = _html.unescape(text).replace("\xa0", " ")
    lines = [_WS.sub(" ", line).strip(" ") for line in text.split("\n")]
    text = "\n".join(line.rstrip("\t") for line in lines)
    return _BLANKS.sub("\n\n", text).strip()
