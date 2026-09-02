# WhatsApp Groups in Digests + Unified Email Theme (Slice 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every parent and coach daily digest lists the WhatsApp groups the recipient belongs in (from `Session.whatsapp_group_link`), and every outbound email renders through one Rally-themed shell with a plain-text twin.

**Architecture:** A new `shared/comms/email_theme.py` owns palette, fonts, shell, button, money formatting and HTML→text. A pure `render_whatsapp_groups_block` in the communications context renders the group strip. Composition-root providers gather `(label, url)` pairs from enrollment data and hand them to the digest use cases through two small Protocols. Identity/billing/composition email bodies switch to the shared shell and delete their inline style copies.

**Tech Stack:** Python 3.12, pydantic v2, FastAPI, Motor, pytest (`backend/.venv`), Playwright (`frontend/node_modules/@playwright/test`) for mockup screenshots.

**Spec:** `docs/superpowers/specs/2026-09-02-whatsapp-groups-and-email-theme-design.md`

## Global Constraints

- Contexts may not import each other (ADR-0005, `tests/structural/test_layering.py`). Contexts MAY import `backend.v2.shared.*`. Composition may import anything.
- Every user-supplied string interpolated into HTML goes through `html.escape` (`quote=True` for attributes).
- Email HTML is inline styles only, literal hex colours, no `<style>` block, no CSS variables.
- Theme tokens (verbatim from spec): font `Manrope, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif`; ink `#0f172a`; muted `#64748b`; line `#e2e8f0`; paper `#f8fafc`; cobalt `#2563eb`; cobalt-hover `#1d4ed8`; cobalt-soft `#eff6ff`; volt `#facc15`; volt-soft `#fef9c3`; night `#0a0f1c`; green `#ecfdf5`/`#065f46`; amber `#fffbeb`/`#92400e`; red `#fef2f2`/`#991b1b`; max width 560px; WhatsApp green `#25d366`.
- Parent block copy (verbatim): "Please join the group for each class above if you haven't already. If you're in a group for a class your child no longer attends, please leave it so you only get messages for your class."
- Coach block copy (verbatim): "Join the group for each class you teach if you haven't already. Leave groups for classes you no longer coach."
- Block heading: "Your class WhatsApp groups". Empty link list ⇒ block renders as `""`.
- The WhatsApp block must never fail a digest: provider errors are logged at warning and yield an empty list.
- Run backend tests from repo root as `backend/.venv/bin/python -m pytest backend/v2/tests/... -q`. Run lint as `backend/.venv/bin/ruff check backend/v2 && backend/.venv/bin/ruff format --check backend/v2`. Run type check as `backend/.venv/bin/mypy backend/v2` (CI-only, but run before the PR).
- Commit after every task. Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Never `--amend`, never `rebase` (pre-push hook blocks both).
- **Mockup gate:** Task 8 renders screenshots and STOPS for owner review before Tasks 9–13 proceed.

---

## File map

| File | Responsibility |
|---|---|
| `backend/v2/shared/comms/email_theme.py` (new) | Tokens, `EmailBrand`, `shell`, `button`, `chip`, `format_money`, `html_to_text` |
| `backend/v2/contexts/communications/application/whatsapp_groups_block.py` (new) | `WhatsAppGroupLink`, `dedupe_group_links`, `render_whatsapp_groups_block` |
| `backend/v2/contexts/communications/application/ports.py` | + `AcademyBrandLookup`, `CoachGroupLinkProvider` Protocols |
| `backend/v2/contexts/communications/application/parent_digest_view.py` | + `whatsapp_groups`, `DuesView.is_overdue` |
| `backend/v2/contexts/communications/application/parent_digest_renderer.py` | Shell, block, copy fixes |
| `backend/v2/contexts/communications/application/digest_renderer.py` | Shell with date header, block, empty-rule fix |
| `backend/v2/contexts/communications/application/unsubscribe_footer.py` | Theme colours |
| `backend/v2/contexts/communications/application/use_cases/send_parent_daily_digest.py` | + `brands` |
| `backend/v2/contexts/communications/application/use_cases/send_coach_daily_digest.py` | + `brands`, `group_links` |
| `backend/v2/contexts/communications/application/use_cases/send_coach_digest_test.py` | same as above |
| `backend/v2/contexts/communications/infrastructure/resend_send_port.py` | + `text` part |
| `backend/v2/composition/email_adapters.py` | `_branded_shell`/`_branded_button` delegate to theme; invoice heading; money format |
| `backend/v2/composition/enrollment_welcome_email.py` | Group chat block position + shared block; no reminder footer |
| `backend/v2/composition/digests.py` | `_AcademyBrandLookup`, `_CoachGroupLinkProvider`, parent provider gathers groups + `is_overdue` |
| `backend/v2/contexts/identity/application/use_cases/send_login_invite.py` | body via theme |
| `backend/v2/contexts/identity/application/use_cases/send_registration_verification_email.py` | body via theme |
| `backend/v2/contexts/billing/application/use_cases/send_add_card_reminder.py` | body via theme |
| `backend/v2/shared/security/external_url.py` | + `validate_whatsapp_group_link` |
| `backend/v2/contexts/enrollment/domain/models.py`, `.../admin_writes.py`, `backend/v2/interfaces/admin/views.py` | use the WhatsApp-specific validator |
| `frontend/app/(admin)/admin/sessions/[id]/SessionEditing.tsx` | helper text + host check |
| `backend/v2/tests/fixtures/email_previews/render_previews.py` (new), `frontend/scripts/email-previews.mjs` (new) | mockup pipeline |

---

### Task 1: Theme module

**Files:**
- Create: `backend/v2/shared/comms/email_theme.py`
- Test: `backend/v2/tests/unit/test_email_theme.py`

**Interfaces:**
- Produces:
  - constants `FONT_STACK, INK, MUTED, LINE, PAPER, COBALT, COBALT_HOVER, COBALT_SOFT, VOLT, VOLT_SOFT, NIGHT, GREEN_BG, GREEN_FG, AMBER_BG, AMBER_FG, RED_BG, RED_FG, RED_BORDER, WHATSAPP_GREEN, MAX_WIDTH`
  - `EmailBrand(academy_name: str, brand_color: str | None = None, logo_url: str | None = None, contact_email: str | None = None, contact_phone: str | None = None)` with `.accent() -> str`
  - `shell(*, brand: EmailBrand, inner_html: str, date_label: str | None = None, footer_html: str = "") -> str`
  - `button(label: str, url: str, *, accent: str = COBALT, variant: Literal["primary","secondary"] = "primary") -> str`
  - `chip(text: str, *, bg: str, fg: str) -> str`
  - `format_money(cents: int, currency: str) -> str` (`$60.00`, `€5.00`, `CHF 5.00`)
  - `html_to_text(html_body: str) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# backend/v2/tests/unit/test_email_theme.py
"""Shared email theme: shell, button, money, text twin."""

from __future__ import annotations

from backend.v2.shared.comms import email_theme as t


def test_brand_accent_falls_back_to_cobalt_for_junk() -> None:
    assert t.EmailBrand(academy_name="A").accent() == t.COBALT
    assert t.EmailBrand(academy_name="A", brand_color="red").accent() == t.COBALT
    assert t.EmailBrand(academy_name="A", brand_color="#ABCDEF").accent() == "#abcdef"
    assert t.EmailBrand(academy_name="A", brand_color=" #123 ").accent() == "#123"


def test_shell_escapes_and_wraps() -> None:
    brand = t.EmailBrand(academy_name="<Acme> & Co", contact_email="hi@acme.test")
    out = t.shell(brand=brand, inner_html="<p>body</p>", date_label="Thu, Sep 3")
    assert "&lt;Acme&gt; &amp; Co" in out
    assert "<Acme>" not in out
    assert "<p>body</p>" in out
    assert "Thu, Sep 3" in out
    assert "hi@acme.test" in out
    assert f"max-width:{t.MAX_WIDTH}px" in out
    assert t.FONT_STACK in out


def test_shell_uses_logo_when_present() -> None:
    brand = t.EmailBrand(academy_name="Acme", logo_url="https://cdn.test/logo.png\" onerror=x")
    out = t.shell(brand=brand, inner_html="")
    assert 'src="https://cdn.test/logo.png&quot; onerror=x"' in out
    assert 'alt="Acme"' in out


def test_button_variants() -> None:
    primary = t.button("Pay <now>", "https://x.test/?a=1&b=2")
    assert "Pay &lt;now&gt;" in primary
    assert 'href="https://x.test/?a=1&amp;b=2"' in primary
    assert f"background:{t.COBALT}" in primary
    secondary = t.button("Join", "https://x.test", variant="secondary")
    assert "background:#ffffff" in secondary
    custom = t.button("Go", "https://x.test", accent="#abcdef")
    assert "background:#abcdef" in custom


def test_format_money() -> None:
    assert t.format_money(6000, "usd") == "$60.00"
    assert t.format_money(123456, "USD") == "$1,234.56"
    assert t.format_money(500, "eur") == "€5.00"
    assert t.format_money(500, "chf") == "CHF 5.00"
    assert t.format_money(-250, "usd") == "-$2.50"


def test_html_to_text_keeps_links_and_structure() -> None:
    html_body = (
        "<div><h2>Title</h2><p>Hello&nbsp;<strong>you</strong>.</p>"
        '<p><a href="https://x.test/pay">Pay now</a></p><br/>'
        "<table><tr><td>A</td><td>B</td></tr></table></div>"
    )
    text = t.html_to_text(html_body)
    assert "Title" in text
    assert "Hello you." in text
    assert "Pay now (https://x.test/pay)" in text
    assert "<" not in text
    assert "A\tB" in text
```

- [ ] **Step 2: Run to verify failure**

Run: `backend/.venv/bin/python -m pytest backend/v2/tests/unit/test_email_theme.py -q`
Expected: `ModuleNotFoundError: No module named 'backend.v2.shared.comms.email_theme'`

- [ ] **Step 3: Implement**

```python
# backend/v2/shared/comms/email_theme.py
"""Single source of truth for how outbound email looks.

Every renderer (identity invites, billing notices, digests, welcome mail)
imports its colours, font, shell and button from here so all mail reads as one
product and matches the app's Rally palette (frontend/tailwind.config.ts).

Email-client constraints: inline styles only, literal hex, table-free where a
flex-free layout suffices, no web fonts (Manrope is first in the stack and
degrades to the system sans everywhere it is not installed).

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
    """Header (logo or name + optional date), a brand rule, the body, and a
    footer naming the academy with its contact details when known."""
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
    contact = (
        " &middot; ".join(_html.escape(b) for b in contact_bits) if contact_bits else ""
    )
    contact_html = f"<br />{contact}" if contact else ""
    return (
        f'<div style="font-family:{FONT_STACK};max-width:{MAX_WIDTH}px;margin:0 auto;'
        f'color:{INK};font-size:15px;line-height:1.5;">'
        f'<div style="padding:4px 0 12px;border-bottom:3px solid {accent};'
        f'margin-bottom:20px;overflow:hidden;">{identity}{date_html}'
        f'<div style="height:3px;width:48px;background:{VOLT};margin-top:-3px;'
        f'position:relative;top:15px;"></div></div>'
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
_WS = re.compile(r"[ \t\r\f\v]+")
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
```

- [ ] **Step 4: Run tests**

Run: `backend/.venv/bin/python -m pytest backend/v2/tests/unit/test_email_theme.py -q`
Expected: 6 passed. (If `A\tB` fails, check `_CELL_END` runs before `_TAG`.)

- [ ] **Step 5: Lint + commit**

```bash
backend/.venv/bin/ruff check backend/v2/shared/comms/email_theme.py backend/v2/tests/unit/test_email_theme.py && backend/.venv/bin/ruff format backend/v2/shared/comms/email_theme.py backend/v2/tests/unit/test_email_theme.py
git add backend/v2/shared/comms/email_theme.py backend/v2/tests/unit/test_email_theme.py
git commit -m "feat(comms): shared Rally email theme module (shell, button, money, text twin)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: WhatsApp groups block renderer

**Files:**
- Create: `backend/v2/contexts/communications/application/whatsapp_groups_block.py`
- Test: `backend/v2/tests/unit/test_whatsapp_groups_block.py`

**Interfaces:**
- Consumes: `email_theme.button, PAPER, INK, MUTED, LINE, WHATSAPP_GREEN`
- Produces:
  - `WhatsAppGroupLink(label: str, url: str, child_names: tuple[str, ...] = ())`
  - `dedupe_group_links(links: Iterable[WhatsAppGroupLink]) -> tuple[WhatsAppGroupLink, ...]` (merge by URL, union child names, keep first label/order)
  - `render_whatsapp_groups_block(links: Sequence[WhatsAppGroupLink], *, persona: Literal["parent","coach"], accent: str = COBALT) -> str`
  - `PARENT_GROUP_NOTE`, `COACH_GROUP_NOTE`, `GROUP_BLOCK_HEADING` string constants

- [ ] **Step 1: Write the failing tests**

```python
# backend/v2/tests/unit/test_whatsapp_groups_block.py
from __future__ import annotations

from backend.v2.contexts.communications.application.whatsapp_groups_block import (
    COACH_GROUP_NOTE,
    GROUP_BLOCK_HEADING,
    PARENT_GROUP_NOTE,
    WhatsAppGroupLink,
    dedupe_group_links,
    render_whatsapp_groups_block,
)

L1 = WhatsAppGroupLink(label="Beginner @ YWCA", url="https://chat.whatsapp.com/AAA", child_names=("Maithri",))
L2 = WhatsAppGroupLink(label="Intermediate @ YWCA", url="https://chat.whatsapp.com/BBB", child_names=("Arjun",))


def test_empty_links_render_nothing() -> None:
    assert render_whatsapp_groups_block([], persona="parent") == ""


def test_parent_block_lists_each_group_with_join_and_note() -> None:
    out = render_whatsapp_groups_block([L1, L2], persona="parent")
    assert GROUP_BLOCK_HEADING in out
    assert out.count('href="https://chat.whatsapp.com/') == 2
    assert "Beginner @ YWCA" in out and "Intermediate @ YWCA" in out
    assert "Maithri" in out and "Arjun" in out
    assert out.count(">Join<") == 2
    assert PARENT_GROUP_NOTE in out
    assert COACH_GROUP_NOTE not in out


def test_coach_block_uses_coach_note_and_no_child_names() -> None:
    out = render_whatsapp_groups_block([L1], persona="coach")
    assert COACH_GROUP_NOTE in out
    assert "Maithri" not in out


def test_labels_are_escaped() -> None:
    bad = WhatsAppGroupLink(label="<b>x</b>", url="https://chat.whatsapp.com/C?a=1&b=2")
    out = render_whatsapp_groups_block([bad], persona="coach")
    assert "&lt;b&gt;x&lt;/b&gt;" in out
    assert 'href="https://chat.whatsapp.com/C?a=1&amp;b=2"' in out


def test_dedupe_merges_same_url_and_keeps_order() -> None:
    dup = WhatsAppGroupLink(label="Beginner @ YWCA", url=L1.url, child_names=("Arjun",))
    merged = dedupe_group_links([L1, L2, dup])
    assert [m.url for m in merged] == [L1.url, L2.url]
    assert merged[0].child_names == ("Maithri", "Arjun")


def test_two_children_same_group_show_both_names_once() -> None:
    dup = WhatsAppGroupLink(label="Beginner @ YWCA", url=L1.url, child_names=("Arjun",))
    out = render_whatsapp_groups_block(dedupe_group_links([L1, dup]), persona="parent")
    assert out.count("Beginner @ YWCA") == 1
    assert "Maithri &amp; Arjun" in out
```

- [ ] **Step 2: Run to verify failure**

Run: `backend/.venv/bin/python -m pytest backend/v2/tests/unit/test_whatsapp_groups_block.py -q`
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# backend/v2/contexts/communications/application/whatsapp_groups_block.py
"""The "Your class WhatsApp groups" strip shared by every recurring email.

Pure: the composition root gathers the links (enrollment context knows which
session a family or coach belongs to); this module only renders. An empty
list renders nothing so an academy that has not configured any group link
sees no change to its digests.
"""

from __future__ import annotations

import html
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from backend.v2.shared.comms.email_theme import (
    COBALT,
    INK,
    LINE,
    MUTED,
    PAPER,
    WHATSAPP_GREEN,
    button,
)

GROUP_BLOCK_HEADING = "Your class WhatsApp groups"
PARENT_GROUP_NOTE = (
    "Please join the group for each class above if you haven't already. "
    "If you're in a group for a class your child no longer attends, please leave it "
    "so you only get messages for your class."
)
COACH_GROUP_NOTE = (
    "Join the group for each class you teach if you haven't already. "
    "Leave groups for classes you no longer coach."
)


@dataclass(frozen=True, slots=True)
class WhatsAppGroupLink:
    label: str
    url: str
    child_names: tuple[str, ...] = ()


def dedupe_group_links(links: Iterable[WhatsAppGroupLink]) -> tuple[WhatsAppGroupLink, ...]:
    """One row per group: two children in the same class share a row."""
    by_url: dict[str, WhatsAppGroupLink] = {}
    for link in links:
        existing = by_url.get(link.url)
        if existing is None:
            by_url[link.url] = link
            continue
        names = existing.child_names + tuple(
            n for n in link.child_names if n not in existing.child_names
        )
        by_url[link.url] = WhatsAppGroupLink(
            label=existing.label, url=existing.url, child_names=names
        )
    return tuple(by_url.values())


def _names(names: Sequence[str]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} & {names[-1]}"


def render_whatsapp_groups_block(
    links: Sequence[WhatsAppGroupLink],
    *,
    persona: Literal["parent", "coach"],
    accent: str = COBALT,
) -> str:
    if not links:
        return ""
    rows = []
    for link in links:
        who = _names(link.child_names) if persona == "parent" else ""
        who_html = (
            f'<span style="font-size:12px;color:{MUTED};display:block;">{html.escape(who)}</span>'
            if who
            else ""
        )
        rows.append(
            '<tr><td style="padding:8px 0;vertical-align:middle;">'
            f'<span style="font-size:14px;font-weight:600;color:{INK};">'
            f"{html.escape(link.label)}</span>{who_html}</td>"
            '<td style="padding:8px 0 8px 12px;text-align:right;vertical-align:middle;">'
            f'{button("Join", link.url, accent=accent, variant="secondary")}</td></tr>'
        )
    note = PARENT_GROUP_NOTE if persona == "parent" else COACH_GROUP_NOTE
    return (
        f'<div style="background:{PAPER};border:1px solid {LINE};'
        f"border-left:4px solid {WHATSAPP_GREEN};border-radius:10px;"
        f'padding:14px 16px;margin:16px 0;">'
        f'<p style="font-size:13px;font-weight:700;color:{INK};margin:0 0 4px;'
        f'text-transform:uppercase;letter-spacing:0.06em;">{GROUP_BLOCK_HEADING}</p>'
        f'<table role="presentation" style="width:100%;border-collapse:collapse;">'
        f'{"".join(rows)}</table>'
        f'<p style="font-size:12px;color:{MUTED};margin:8px 0 0;">{note}</p>'
        "</div>"
    )
```

- [ ] **Step 4: Run tests**

Run: `backend/.venv/bin/python -m pytest backend/v2/tests/unit/test_whatsapp_groups_block.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/v2/contexts/communications/application/whatsapp_groups_block.py backend/v2/tests/unit/test_whatsapp_groups_block.py
git commit -m "feat(comms): pure renderer for the class WhatsApp groups block

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Parent digest renderer on the shell + block + copy fixes

**Files:**
- Modify: `backend/v2/contexts/communications/application/parent_digest_view.py`
- Modify: `backend/v2/contexts/communications/application/parent_digest_renderer.py`
- Modify: `backend/v2/contexts/communications/application/unsubscribe_footer.py:14-15`
- Test: `backend/v2/tests/application/test_parent_digest_renderer.py`

**Interfaces:**
- Consumes: `email_theme.*`, `whatsapp_groups_block.*`
- Produces: `ParentDigestView.whatsapp_groups: tuple[WhatsAppGroupLink, ...] = ()`; `DuesView.is_overdue: bool = False`; `render_parent_digest(view, *, brand: EmailBrand | None = None, unsubscribe_url: str | None = None) -> tuple[str, str]`. When `brand` is None the shell uses `EmailBrand(academy_name=view.program_name or "Your academy")`.

- [ ] **Step 1: Add failing tests** (append to the existing test file; keep the existing tests)

```python
from backend.v2.contexts.communications.application.whatsapp_groups_block import (
    GROUP_BLOCK_HEADING,
    PARENT_GROUP_NOTE,
    WhatsAppGroupLink,
)
from backend.v2.shared.comms.email_theme import RED_BG, COBALT_SOFT, EmailBrand


def _view(**overrides) -> ParentDigestView:
    base = dict(
        parent_name="Priya",
        date_label="Thursday, September 3",
        program_name="Badminton",
        children=(_child(),),
        on_portal=True,
        portal_url="https://portal.test/parent/dashboard",
    )
    base.update(overrides)
    return ParentDigestView(**base)


def test_multi_child_greeting_is_capitalised() -> None:
    _, body = render_parent_digest(_view(children=(_child("A"), _child("B"))))
    assert "Good morning! Your kids have practice today" in body


def test_upcoming_dues_are_not_red_and_overdue_are() -> None:
    upcoming = DuesView(amount="$60.00", due_date="September 10", pay_url="https://p/pay")
    _, body = render_parent_digest(_view(dues=upcoming))
    assert COBALT_SOFT in body and RED_BG not in body
    assert "due September 10" in body
    overdue = DuesView(amount="$60.00", due_date="August 10", pay_url="https://p/pay", is_overdue=True)
    _, body = render_parent_digest(_view(dues=overdue))
    assert RED_BG in body
    assert "overdue since August 10" in body


def test_variant_b_dues_wording_follows_overdue_flag() -> None:
    upcoming = DuesView(amount="$60.00", due_date="September 10", pay_url="https://p/pay")
    _, body = render_parent_digest(
        _view(on_portal=False, dues=upcoming, activate_url="https://p/activate")
    )
    assert "is due September 10" in body
    overdue = DuesView(amount="$60.00", due_date="August 10", pay_url="https://p/pay", is_overdue=True)
    _, body = render_parent_digest(
        _view(on_portal=False, dues=overdue, activate_url="https://p/activate")
    )
    assert "was due August 10" in body


def test_whatsapp_block_rendered_between_cards_and_billing() -> None:
    link = WhatsAppGroupLink(label="Beginner @ YWCA", url="https://chat.whatsapp.com/AAA", child_names=("Maithri",))
    dues = DuesView(amount="$60.00", due_date="September 10", pay_url="https://p/pay")
    _, body = render_parent_digest(_view(whatsapp_groups=(link,), dues=dues))
    assert GROUP_BLOCK_HEADING in body and PARENT_GROUP_NOTE in body
    assert body.index("Thumb grip") < body.index(GROUP_BLOCK_HEADING) < body.index("Pay now")


def test_no_links_means_no_block() -> None:
    _, body = render_parent_digest(_view())
    assert GROUP_BLOCK_HEADING not in body


def test_shell_shows_academy_and_date() -> None:
    brand = EmailBrand(academy_name="BLNO Badminton", brand_color="#112233")
    _, body = render_parent_digest(_view(), brand=brand)
    assert "BLNO Badminton" in body
    assert "Thursday, September 3" in body
    assert "#112233" in body
```

- [ ] **Step 2: Run to verify failure**

Run: `backend/.venv/bin/python -m pytest backend/v2/tests/application/test_parent_digest_renderer.py -q`
Expected: failures on `is_overdue`/`whatsapp_groups`/`brand` unexpected keyword.

- [ ] **Step 3: Update the view**

In `parent_digest_view.py`, add the import and fields:

```python
from backend.v2.contexts.communications.application.whatsapp_groups_block import (
    WhatsAppGroupLink,
)

# in DuesView, after pay_url:
    # True when the earliest open invoice's due date is before today. Drives
    # colour and wording: red + "overdue since" vs neutral + "due".
    is_overdue: bool = False

# in ParentDigestView, after reply_to:
    # Groups for every ACTIVE enrollment in the family (not only today's
    # sessions), deduplicated by URL. Empty when no session has a link.
    whatsapp_groups: tuple[WhatsAppGroupLink, ...] = ()
```

- [ ] **Step 4: Rewrite the renderer's constants, entry point, greeting, billing and activation blocks**

Replace the module-level colour constants with theme imports and re-map the names used below:

```python
from backend.v2.contexts.communications.application.whatsapp_groups_block import (
    render_whatsapp_groups_block,
)
from backend.v2.shared.comms.email_theme import (
    AMBER_BG,
    AMBER_FG,
    COBALT,
    COBALT_SOFT,
    EmailBrand,
    GREEN_BG,
    GREEN_FG,
    INK,
    LINE,
    MUTED,
    PAPER,
    RED_BG,
    RED_BORDER,
    RED_FG,
    button,
    chip,
    shell,
)

_TEXT_PRIMARY = INK
_TEXT_SECONDARY = MUTED
_TEXT_MUTED = MUTED
_BORDER = LINE
_SURFACE = PAPER
_LINK = COBALT

_STATUS_CHIPS = {
    "not started": ("#f1f5f9", MUTED),
    "introduced": (AMBER_BG, AMBER_FG),
    "learning": (COBALT_SOFT, "#1e40af"),
    "practicing": (GREEN_BG, GREEN_FG),
}
_DEFAULT_CHIP = ("#f1f5f9", "#334155")

_ACCENT_BG = COBALT_SOFT
_ACCENT_FG = "#1e40af"
_ACCENT_FILL = COBALT
_DANGER_BG = RED_BG
_DANGER_FG = RED_FG
_DANGER_BORDER = RED_BORDER
_DANGER_FILL = "#dc2626"
```

Delete `_FONT_STACK` and the old hex constants. Replace `render_parent_digest`:

```python
def render_parent_digest(
    view: ParentDigestView,
    *,
    brand: EmailBrand | None = None,
    unsubscribe_url: str | None = None,
) -> tuple[str, str]:
    """Return ``(subject, body)`` for one family's morning digest. ``body`` is HTML.

    The digest is a recurring non-transactional message, so it always ends
    with an opt-out notice (#555). ``unsubscribe_url`` is ``None`` when no
    signing secret is configured; the footer then points at the portal
    instead of rendering a link that would go nowhere.
    """
    subject = _subject(view)
    resolved_brand = brand or EmailBrand(academy_name=view.program_name or "Your academy")
    accent = resolved_brand.accent()

    greeting = _greeting(view)
    cards = "".join(_child_card(c, on_portal=view.on_portal) for c in view.children)
    groups = render_whatsapp_groups_block(view.whatsapp_groups, persona="parent", accent=accent)
    billing = _billing_block(view) if view.on_portal else _activation_block(view)
    footer = _footer(view) + render_unsubscribe_footer(unsubscribe_url)

    body = shell(
        brand=resolved_brand,
        inner_html=f"{greeting}{cards}{groups}{billing}",
        date_label=view.date_label or None,
        footer_html=footer,
    )
    return subject, body
```

Fix the greeting: change `who = "your kids have"` to `who = "Your kids have"` and `who = "you have"` to `who = "You have"`, and the single-child branch stays as-is because it starts with the name. Also change the f-string so the sentence is `f"Good morning! {who} practice today — here's the plan."` (unchanged text, just the capital now comes from `who`).

Replace the dues banner in `_billing_block` with an overdue-aware one:

```python
    if view.dues is not None:
        d = view.dues
        bg, fg, border = (
            (_DANGER_BG, _DANGER_FG, _DANGER_BORDER)
            if d.is_overdue
            else (_ACCENT_BG, _ACCENT_FG, "#bfdbfe")
        )
        when = f"overdue since {html.escape(d.due_date)}" if d.is_overdue else f"due {html.escape(d.due_date)}"
        out.append(
            f'<div style="display:flex;align-items:center;justify-content:space-between;'
            f"gap:12px;background:{bg};border-radius:8px;padding:10px 14px;"
            f'margin-bottom:10px;">'
            f'<p style="font-size:13px;color:{fg};margin:0;">'
            f'Balance of <span style="font-weight:600;">{html.escape(d.amount)}</span> {when}.</p>'
            f'<a href="{html.escape(d.pay_url, quote=True)}" '
            f'style="background:#ffffff;border:1px solid {border};'
            f"color:{fg};font-size:12px;font-weight:600;padding:6px 14px;"
            f'border-radius:8px;text-decoration:none;white-space:nowrap;">Pay now</a>'
            "</div>"
        )
```

In `_activation_block`, replace the dues branch's first two style values and the heading sentence:

```python
    if view.dues is not None:
        d = view.dues
        bg, fg, fill = (
            (_DANGER_BG, _DANGER_FG, _DANGER_FILL) if d.is_overdue else (_ACCENT_BG, _ACCENT_FG, _ACCENT_FILL)
        )
        verb = "was due" if d.is_overdue else "is due"
        return (
            f'<div style="background:{bg};border-radius:10px;padding:16px;">'
            f'<p style="font-size:14px;font-weight:600;color:{fg};margin:0 0 4px;">'
            f"Your balance of {html.escape(d.amount)} {verb} {html.escape(d.due_date)}</p>"
            f'<p style="font-size:13px;color:{fg};margin:0 0 12px;">'
            f"Set up your parent account to pay in two minutes — you'll also be able to "
            f"report absences and follow your child's progress.</p>"
            f'<a href="{url}" style="background:{fill};color:#ffffff;font-size:13px;'
            f"font-weight:600;padding:9px 18px;border-radius:8px;text-decoration:none;"
            f'display:inline-block;">Set up account &amp; pay</a>'
            "</div>"
        )
```

Replace `_status_chip` body with `return " " + chip(status, bg=bg, fg=fg)` after the lookup. Leave `_child_card`, `_progress_block`, `_footer` unchanged apart from now-remapped constants.

In `unsubscribe_footer.py` replace the two constants:

```python
from backend.v2.shared.comms.email_theme import COBALT, LINE, MUTED

_MUTED = MUTED
_LINK = COBALT
```
and change `border-top:1px solid #e5e7eb` to `border-top:1px solid {LINE}` (make that string an f-string).

- [ ] **Step 5: Run tests**

Run: `backend/.venv/bin/python -m pytest backend/v2/tests/application/test_parent_digest_renderer.py backend/v2/tests/unit/test_digest_unsubscribe_footer.py -q`
Expected: all pass. If an existing test asserts the exact old greeting `"Good morning! Maithri has practice today"`, it still passes (single-child path unchanged).

- [ ] **Step 6: Commit**

```bash
git add backend/v2/contexts/communications/application/parent_digest_view.py backend/v2/contexts/communications/application/parent_digest_renderer.py backend/v2/contexts/communications/application/unsubscribe_footer.py backend/v2/tests/application/test_parent_digest_renderer.py
git commit -m "feat(comms): parent digest on the shared shell with WhatsApp groups and overdue-aware dues

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Coach digest renderer on the shell + block

**Files:**
- Modify: `backend/v2/contexts/communications/application/digest_renderer.py`
- Test: `backend/v2/tests/application/test_send_coach_daily_digest.py` (renderer tests live here, around line 210)

**Interfaces:**
- Produces: `render_coach_digest(plan, *, brand: EmailBrand | None = None, whatsapp_groups: Sequence[WhatsAppGroupLink] = (), playlist_url: str | None = None, unsubscribe_url: str | None = None) -> tuple[str, str]`

- [ ] **Step 1: Add failing tests** (append near the existing `render_coach_digest` test)

```python
from backend.v2.contexts.communications.application.whatsapp_groups_block import (
    COACH_GROUP_NOTE,
    GROUP_BLOCK_HEADING,
    WhatsAppGroupLink,
)
from backend.v2.shared.comms.email_theme import EmailBrand


def test_coach_digest_has_greeting_date_and_academy() -> None:
    plan = _populated_plan()
    _, body = render_coach_digest(plan, brand=EmailBrand(academy_name="BLNO Badminton"))
    assert "BLNO Badminton" in body
    assert "Good morning" in body
    assert str(plan.date) in body


def test_coach_digest_renders_groups_after_sessions() -> None:
    link = WhatsAppGroupLink(label="Tuesday Juniors", url="https://chat.whatsapp.com/AAA")
    _, body = render_coach_digest(_populated_plan(), whatsapp_groups=[link], playlist_url="https://yt/pl")
    assert GROUP_BLOCK_HEADING in body and COACH_GROUP_NOTE in body
    assert body.index("Not yet placed") < body.index(GROUP_BLOCK_HEADING) < body.index("Full video playlist")


def test_coach_digest_without_playlist_has_no_empty_rule() -> None:
    _, body = render_coach_digest(_populated_plan())
    assert "Full video playlist" not in body
    # exactly one top-level rule above the unsubscribe footer: the shell's
    assert body.count("border-top:1px solid") == 2  # shell footer + unsubscribe footer
```

- [ ] **Step 2: Run to verify failure**

Run: `backend/.venv/bin/python -m pytest backend/v2/tests/application/test_send_coach_daily_digest.py -q -k "coach_digest"`
Expected: `TypeError: unexpected keyword argument 'brand'`

- [ ] **Step 3: Implement**

Replace the constants block at the top of `digest_renderer.py` with:

```python
from collections.abc import Sequence

from backend.v2.contexts.communications.application.whatsapp_groups_block import (
    WhatsAppGroupLink,
    render_whatsapp_groups_block,
)
from backend.v2.shared.comms.email_theme import (
    AMBER_BG,
    AMBER_FG,
    COBALT,
    COBALT_SOFT,
    EmailBrand,
    GREEN_BG,
    GREEN_FG,
    INK,
    LINE,
    MUTED,
    shell,
)

_TEXT_PRIMARY = INK
_TEXT_SECONDARY = MUTED
_TEXT_MUTED = MUTED
_BORDER = LINE
_LINK = COBALT

_STATUS_CHIPS = {
    "not started": ("#f1f5f9", MUTED),
    "introduced": (AMBER_BG, AMBER_FG),
    "learning": (COBALT_SOFT, "#1e40af"),
    "practicing": (GREEN_BG, GREEN_FG),
}
_DEFAULT_CHIP = ("#f1f5f9", "#334155")
```

Replace `render_coach_digest`:

```python
def render_coach_digest(
    plan: Any,
    *,
    brand: EmailBrand | None = None,
    whatsapp_groups: Sequence[WhatsAppGroupLink] = (),
    playlist_url: str | None = None,
    unsubscribe_url: str | None = None,
) -> tuple[str, str]:
    """Return ``(subject, body)`` for one coach's daily plan. ``body`` is HTML.

    Ends with the same opt-out notice as the parent digest (#555): a daily
    recurring email is not transactional, whoever receives it.
    """
    date_str = str(getattr(plan, "date", "") or "")
    program_name = str(getattr(plan, "program_name", "") or "")

    subject = f"Your teaching plan for {date_str}" if date_str else "Your teaching plan"
    if program_name:
        subject = f"{subject} — {program_name}"

    resolved_brand = brand or EmailBrand(academy_name=program_name or "Your academy")
    greeting = (
        f'<p style="font-size:15px;margin:0 0 16px;">Good morning! Here is your teaching plan'
        f"{' for ' + html.escape(program_name) if program_name else ''}.</p>"
    )
    sessions_html = "".join(_render_session(s) for s in (getattr(plan, "sessions", None) or []))
    groups_html = render_whatsapp_groups_block(
        whatsapp_groups, persona="coach", accent=resolved_brand.accent()
    )

    footer_html = ""
    if playlist_url:
        footer_html = (
            f'<p style="font-size:12px;color:{_TEXT_MUTED};margin:16px 0 0;">'
            f'<a href="{html.escape(playlist_url, quote=True)}" style="color:{_LINK};text-decoration:none;">Full video playlist</a>'
            "</p>"
        )

    body = shell(
        brand=resolved_brand,
        inner_html=f"{greeting}{sessions_html}{groups_html}",
        date_label=date_str or None,
        footer_html=footer_html + render_unsubscribe_footer(unsubscribe_url),
    )
    return subject, body
```

In `_render_session`, change the wrapper's `border-bottom:1px solid {_BORDER}` to `border:1px solid {_BORDER};border-radius:10px;padding:14px 16px;` so sessions become cards like the parent digest (keep `margin-bottom:12px`). Remove `padding-bottom:16px`.

- [ ] **Step 4: Run tests**

Run: `backend/.venv/bin/python -m pytest backend/v2/tests/application/test_send_coach_daily_digest.py backend/v2/tests/unit/test_digest_unsubscribe_footer.py -q`
Expected: all pass. If the empty-rule count assertion is off by one, count the `border-top:1px solid` occurrences in the rendered body and fix the expected number to match the shell footer + unsubscribe footer only.

- [ ] **Step 5: Commit**

```bash
git add backend/v2/contexts/communications/application/digest_renderer.py backend/v2/tests/application/test_send_coach_daily_digest.py
git commit -m "feat(comms): coach digest on the shared shell with WhatsApp groups

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Composition adapters use the theme (billing, welcome, roster, announcements)

**Files:**
- Modify: `backend/v2/composition/email_adapters.py:45-80, 185-238, 298-345`
- Modify: `backend/v2/composition/enrollment_welcome_email.py:196-232`
- Test: `backend/v2/tests/unit/test_enrollment_welcome_email.py`, `backend/v2/tests/composition/` (existing adapter tests), new `backend/v2/tests/unit/test_email_adapters_theme.py`

**Interfaces:**
- `_branded_shell(*, academy_name, inner_html, footer_note: str | None = None)` keeps its signature (roster/announcement callers unchanged) and delegates to `email_theme.shell`. `_branded_button(*, label, url)` delegates to `email_theme.button`. `_BRAND_HEADING = INK`, `_BRAND_ACCENT = COBALT`, `_BRAND_MUTED = MUTED`, `_BRAND_FONT = FONT_STACK` remain exported names.

- [ ] **Step 1: Write failing tests**

```python
# backend/v2/tests/unit/test_email_adapters_theme.py
from __future__ import annotations

from backend.v2.composition.email_adapters import _branded_button, _branded_shell
from backend.v2.shared.comms.email_theme import COBALT, FONT_STACK, MAX_WIDTH


def test_branded_shell_uses_theme_and_has_no_reminder_footer_by_default() -> None:
    out = _branded_shell(academy_name="BLNO <Badminton>", inner_html="<p>x</p>")
    assert FONT_STACK in out
    assert f"max-width:{MAX_WIDTH}px" in out
    assert "BLNO &lt;Badminton&gt;" in out
    assert "please disregard" not in out


def test_branded_shell_reminder_footer_opt_in() -> None:
    out = _branded_shell(
        academy_name="A", inner_html="", footer_note="If you've already paid, please disregard this message."
    )
    assert "please disregard" in out


def test_branded_button_is_theme_button() -> None:
    out = _branded_button(label="Pay", url="https://x.test")
    assert f"background:{COBALT}" in out
```

Add to `test_enrollment_welcome_email.py`:

```python
from backend.v2.contexts.communications.application.whatsapp_groups_block import (
    GROUP_BLOCK_HEADING,
)


def test_group_chat_sits_right_after_where_and_uses_shared_block() -> None:
    _, body = _render(
        _session(
            whatsapp_group_link="https://chat.whatsapp.com/AbCd1234",
            venue_address="123 Main",
            parking_notes="Lot B",
        )
    )
    assert GROUP_BLOCK_HEADING in body
    assert body.index("Where") < body.index(GROUP_BLOCK_HEADING) < body.index("Parking")
    assert "Join the class WhatsApp group" in body
    assert "please disregard" not in body
```

- [ ] **Step 2: Run to verify failure**

Run: `backend/.venv/bin/python -m pytest backend/v2/tests/unit/test_email_adapters_theme.py backend/v2/tests/unit/test_enrollment_welcome_email.py -q`
Expected: failures (`footer_note` unexpected kwarg; "please disregard" present; group order).

- [ ] **Step 3: Implement in `email_adapters.py`**

Replace lines 45–80 (constants, `_branded_shell`, `_branded_button`) with:

```python
from backend.v2.shared.comms.email_theme import (
    COBALT,
    FONT_STACK,
    INK,
    MUTED,
    EmailBrand,
    button,
    format_money,
    shell,
)

# Re-exported for existing callers (roster_notifications, session_announcements,
# enrollment_welcome_email). New code should import email_theme directly.
_BRAND_HEADING = INK
_BRAND_ACCENT = COBALT
_BRAND_MUTED = MUTED
_BRAND_FONT = FONT_STACK


def _branded_shell(
    *, academy_name: str, inner_html: str, footer_note: str | None = None
) -> str:
    """The academy-branded shell shared by every transactional email.

    ``footer_note`` is for reminders only ("if you've already paid, please
    disregard"); a welcome or invoice must not carry it.
    """
    note_html = (
        f'<p style="font-size:12px;color:{MUTED};margin:20px 0 0;">{html.escape(footer_note)}</p>'
        if footer_note
        else ""
    )
    return shell(
        brand=EmailBrand(academy_name=academy_name), inner_html=inner_html, footer_html=note_html
    )


def _branded_button(*, label: str, url: str) -> str:
    return button(label, url)
```

In `send_invoice_email` (line ~206): replace the two amount lines with `amount = format_money(balance_due_cents, currency)` and `total = format_money(total_cents, currency)`; change the heading to `f"<h2 style='color: {_BRAND_HEADING}; font-size: 20px; margin: 0 0 12px;'>Your {safe_period} invoice</h2>"` and the first paragraph to `f"<p>Invoice <strong>{safe_invoice}</strong> is ready.</p>"`.

In `send_dunning_notice`: format amounts with `format_money` wherever `f"{currency.upper()} {…/100:.2f}"` appears (search the function for `/ 100`).

In `DuesReminderEmailAdapter.send_reminder`: format with `format_money`, and pass `footer_note="If you've already taken care of this, please disregard this message."` to `_branded_shell`. Keep `dues_reminder_text` in `shared/comms/whatsapp.py` in sync: change its `amount = …` line to `amount = format_money(total_due_cents, currency)` (import from `email_theme`), and update `tests/unit/test_whatsapp_link.py` expectations from `USD 60.00` style to `$60.00` if any assert on it.

- [ ] **Step 4: Implement in `enrollment_welcome_email.py`**

Add import `from backend.v2.contexts.communications.application.whatsapp_groups_block import WhatsAppGroupLink, render_whatsapp_groups_block` (composition may import contexts). Remove the trailing `if session.whatsapp_group_link:` block (lines ~216–228). Right after the "Where" block is appended (search for `parts.append(_block("Where"`), insert:

```python
    if session.whatsapp_group_link:
        # The href is escaped by the block; the *scheme* was allowlisted on the
        # way in (shared/security/external_url.py). Different controls.
        parts.append(
            _block(
                "Group chat",
                _branded_button(label="Join the class WhatsApp group", url=session.whatsapp_group_link)
                + render_whatsapp_groups_block(
                    [WhatsAppGroupLink(label=session.title, url=session.whatsapp_group_link)],
                    persona="parent",
                ),
            )
        )
```

Delete `_ETIQUETTE_TEMPLATE` and its `_ETIQUETTE` test constant usages; update any test asserting the old etiquette sentence to assert `PARENT_GROUP_NOTE` instead. (Search: `grep -n ETIQUETTE backend/v2/tests/unit/test_enrollment_welcome_email.py`.)

- [ ] **Step 5: Run the affected suites**

Run: `backend/.venv/bin/python -m pytest backend/v2/tests/unit/test_email_adapters_theme.py backend/v2/tests/unit/test_enrollment_welcome_email.py backend/v2/tests/unit/test_whatsapp_link.py backend/v2/tests/composition backend/v2/tests/contract -q -x`
Expected: pass. Fix any test that asserted `USD 60.00`-style strings or the old "Open WhatsApp group" label.

- [ ] **Step 6: Commit**

```bash
git add backend/v2/composition/email_adapters.py backend/v2/composition/enrollment_welcome_email.py backend/v2/shared/comms/whatsapp.py backend/v2/tests/unit/test_email_adapters_theme.py backend/v2/tests/unit/test_enrollment_welcome_email.py backend/v2/tests/unit/test_whatsapp_link.py
git commit -m "refactor(comms): billing and welcome emails on the shared theme; single money format

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Identity + billing context bodies use the theme

**Files:**
- Modify: `backend/v2/contexts/identity/application/use_cases/send_login_invite.py:98-121`
- Modify: `backend/v2/contexts/identity/application/use_cases/send_registration_verification_email.py:54-70`
- Modify: `backend/v2/contexts/billing/application/use_cases/send_add_card_reminder.py:29-47`
- Test: existing tests in `backend/v2/tests/application/` for these three use cases (`grep -rln "_invite_body\|_verification_body\|_reminder_body\|Set your password" backend/v2/tests`)

- [ ] **Step 1: Write a failing assertion in each existing test module** (add one test per module)

```python
def test_invite_body_uses_shared_shell() -> None:
    from backend.v2.contexts.identity.application.use_cases.send_login_invite import _invite_body
    from backend.v2.shared.comms.email_theme import FONT_STACK

    body = _invite_body(display_name="P", academy_name="A", reset_link="https://x.test")
    assert FONT_STACK in body
    assert "Sent by A" in body
```

(Repeat for `_verification_body(academy_name=..., verify_link=...)` and `_reminder_body(display_name=..., academy_name=..., setup_link=...)`.)

- [ ] **Step 2: Run to verify failure**

Run: `backend/.venv/bin/python -m pytest backend/v2/tests/application -q -k "invite_body or verification_body or reminder_body"`
Expected: 3 failures (`FONT_STACK` not in body).

- [ ] **Step 3: Implement**

`send_login_invite.py`:

```python
from backend.v2.shared.comms.email_theme import INK, MUTED, EmailBrand, button, shell


def _invite_body(*, display_name: str, academy_name: str, reset_link: str) -> str:
    safe_display_name = escape(display_name)
    safe_academy_name = escape(academy_name)
    inner = (
        f'<h2 style="color:{INK};font-size:20px;margin:0 0 12px;">'
        f"Your {safe_academy_name} account is ready</h2>"
        f"<p>Hi {safe_display_name},</p>"
        f"<p>Your account at <strong>{safe_academy_name}</strong> has been set up. Set your "
        f"password to log in, see your children's enrollment, and make payments.</p>"
        f'<p style="margin:24px 0;">{button("Set your password", reset_link)}</p>'
        f'<p style="color:{MUTED};font-size:13px;">This link expires after a short time. '
        f"If it has expired, ask your academy to send a new one, or use "
        f"&ldquo;Forgot password&rdquo; on the login page with this email address.</p>"
    )
    return shell(brand=EmailBrand(academy_name=academy_name), inner_html=inner)
```

`send_registration_verification_email.py`:

```python
from backend.v2.shared.comms.email_theme import INK, MUTED, EmailBrand, button, shell


def _verification_body(*, academy_name: str, verify_link: str) -> str:
    safe_academy_name = escape(academy_name)
    inner = (
        f'<h2 style="color:{INK};font-size:20px;margin:0 0 12px;">'
        f"Confirm your email for {safe_academy_name}</h2>"
        f"<p>Thanks for registering. Confirm your email address to finish setting up "
        f"your account and enroll your child.</p>"
        f'<p style="margin:24px 0;">{button("Verify email address", verify_link)}</p>'
        f'<p style="color:{MUTED};font-size:13px;">If you didn\'t request this, '
        f"you can ignore this email.</p>"
    )
    return shell(brand=EmailBrand(academy_name=academy_name), inner_html=inner)
```

`send_add_card_reminder.py`:

```python
from backend.v2.shared.comms.email_theme import INK, EmailBrand, button, shell


def _reminder_body(*, display_name: str, academy_name: str, setup_link: str) -> str:
    safe_display_name = escape(display_name)
    safe_academy_name = escape(academy_name)
    inner = (
        f'<h2 style="color:{INK};font-size:20px;margin:0 0 12px;">'
        f"Add a payment method for {safe_academy_name}</h2>"
        f"<p>Hi {safe_display_name},</p>"
        f"<p>Your account at <strong>{safe_academy_name}</strong> is set up, but we don't have "
        f"a payment method on file yet. Add one to keep your children's enrollment current.</p>"
        f'<p style="margin:24px 0;">{button("Add payment method", setup_link)}</p>'
    )
    return shell(brand=EmailBrand(academy_name=academy_name), inner_html=inner)
```

- [ ] **Step 4: Run tests + layering**

Run: `backend/.venv/bin/python -m pytest backend/v2/tests/application backend/v2/tests/structural -q -x`
Expected: pass (structural layering test allows `shared` imports).

- [ ] **Step 5: Commit**

```bash
git add backend/v2/contexts/identity/application/use_cases/send_login_invite.py backend/v2/contexts/identity/application/use_cases/send_registration_verification_email.py backend/v2/contexts/billing/application/use_cases/send_add_card_reminder.py backend/v2/tests/application
git commit -m "refactor(identity,billing): invite, verification and add-card emails on the shared theme

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Mockup pipeline (checked in)

**Files:**
- Create: `backend/v2/tests/fixtures/email_previews/__init__.py` (empty), `backend/v2/tests/fixtures/email_previews/render_previews.py`
- Create: `frontend/scripts/email-previews.mjs`

- [ ] **Step 1: Write the render script**

```python
# backend/v2/tests/fixtures/email_previews/render_previews.py
"""Render every outbound email template with sample data to HTML files.

Usage (from repo root):
    backend/.venv/bin/python -m backend.v2.tests.fixtures.email_previews.render_previews OUT_DIR
Then screenshot with: node frontend/scripts/email-previews.mjs OUT_DIR
Not collected by pytest (module name does not start with ``test_``).
"""

from __future__ import annotations

import pathlib
import sys
from datetime import UTC, datetime

from backend.v2.composition.email_adapters import _branded_button, _branded_shell
from backend.v2.composition.enrollment_welcome_email import render_welcome_email
from backend.v2.contexts.billing.application.use_cases.send_add_card_reminder import _reminder_body
from backend.v2.contexts.communications.application.digest_renderer import render_coach_digest
from backend.v2.contexts.communications.application.parent_digest_renderer import (
    render_parent_digest,
)
from backend.v2.contexts.communications.application.parent_digest_view import (
    ChildDigestView,
    DuesView,
    ParentDigestView,
)
from backend.v2.contexts.communications.application.whatsapp_groups_block import (
    WhatsAppGroupLink,
)
from backend.v2.contexts.enrollment.domain.models import Session
from backend.v2.contexts.identity.application.use_cases.send_login_invite import _invite_body
from backend.v2.shared.comms.email_theme import INK, EmailBrand, format_money
from backend.v2.tests.application.test_send_coach_daily_digest import _populated_plan

BRAND = EmailBrand(
    academy_name="BLNO Badminton", contact_email="hello@blno.test", contact_phone="(312) 555-0100"
)
UNSUB = "https://portal.test/unsubscribe?t=abc"
G1 = WhatsAppGroupLink(label="Beginner @ YWCA", url="https://chat.whatsapp.com/AAA", child_names=("Maithri",))
G2 = WhatsAppGroupLink(label="Intermediate @ YWCA", url="https://chat.whatsapp.com/BBB", child_names=("Arjun",))


def _child(name: str, **o: object) -> ChildDigestView:
    base: dict[str, object] = dict(
        child_name=name, session_time="6:00 - 6:45 PM", session_label="Beginner @ YWCA",
        focus_skill="Thumb grip", focus_status="practicing", level_name="Level 1",
        skills_completed=7, skills_total=10, skills_left=3, levels_to_go=3,
        cant_make_it_url="https://portal.test/parent/requests",
    )
    base.update(o)
    return ChildDigestView(**base)  # type: ignore[arg-type]


def render_all(out: pathlib.Path) -> None:
    out.mkdir(parents=True, exist_ok=True)

    def write(name: str, subject: str, body: str) -> None:
        (out / f"{name}.html").write_text(f"<!--{subject}-->\n{body}")

    a = ParentDigestView(
        parent_name="Priya", date_label="Thursday, September 3", program_name="Badminton Skill Pathway",
        children=(
            _child("Maithri"),
            _child("Arjun", session_time="7:00 - 7:45 PM", session_label="Intermediate @ YWCA",
                   focus_skill="Backhand lift", focus_status="learning", level_name="Level 2",
                   skills_completed=2, skills_total=12, skills_left=10, levels_to_go=2),
        ),
        on_portal=True,
        dues=DuesView(amount="$60.00", due_date="September 10", pay_url="https://portal.test/pay"),
        autopay_enabled=False, portal_url="https://portal.test/parent/dashboard",
        whatsapp_groups=(G1, G2),
    )
    write("parent_digest_A", *render_parent_digest(a, brand=BRAND, unsubscribe_url=UNSUB))

    b = ParentDigestView(
        parent_name="Priya", date_label="Thursday, September 3", program_name="Badminton Skill Pathway",
        children=(_child("Maithri", cant_make_it_url=None),), on_portal=False,
        dues=DuesView(amount="$60.00", due_date="August 10", pay_url="https://portal.test/pay", is_overdue=True),
        activate_url="https://portal.test/activate", reply_to="coach@blno.test",
        whatsapp_groups=(G1,),
    )
    write("parent_digest_B", *render_parent_digest(b, brand=BRAND, unsubscribe_url=UNSUB))

    write("coach_digest", *render_coach_digest(
        _populated_plan(), brand=BRAND, whatsapp_groups=[G1, G2],
        playlist_url="https://youtube.com/playlist", unsubscribe_url=UNSUB,
    ))

    inner = (
        f"<h2 style='color: {INK}; font-size: 20px; margin: 0 0 12px;'>Your September 2026 invoice</h2>"
        "<p>Invoice <strong>INV-2026-09-0042</strong> is ready.</p>"
        f"<p>Balance due: <strong>{format_money(12000, 'usd')}</strong> (invoice total {format_money(12000, 'usd')}).</p>"
        + _branded_button(label="Pay invoice", url="https://portal.test/pay")
    )
    write("invoice", "Invoice INV-2026-09-0042 for September 2026",
          _branded_shell(academy_name="BLNO Badminton", inner_html=inner))

    write("login_invite", "Set your password for BLNO Badminton",
          _invite_body(display_name="Priya", academy_name="BLNO Badminton", reset_link="https://portal.test/set"))
    write("add_card", "Add a payment method for BLNO Badminton",
          _reminder_body(display_name="Priya", academy_name="BLNO Badminton", setup_link="https://portal.test/card"))

    s = Session(
        session_id="s1", academy_id="a", coach_id="c", title="Beginner Badminton", location="YWCA Court 1",
        start_at=datetime(2026, 9, 8, 23, 0, tzinfo=UTC), end_at=datetime(2026, 9, 8, 23, 45, tzinfo=UTC),
        capacity=12, timezone="America/Chicago", days_of_week=["Tue", "Thu"], start_time="18:00", end_time="18:45",
        whatsapp_group_link="https://chat.whatsapp.com/AAA", venue_address="123 Main St, Chicago IL",
        parking_notes="Lot behind the building", what_to_bring="Racket, water bottle, indoor shoes",
        arrival_minutes_before=10, coach_contact_policy="Message the coach via the WhatsApp group.",
        absence_policy="Tell us by noon on the day.",
    )
    write("welcome", *render_welcome_email(session=s, academy_name="BLNO Badminton", student_name="Maithri", coach_name="Coach Ravi"))
    print("rendered", sorted(p.name for p in out.glob("*.html")))


if __name__ == "__main__":
    render_all(pathlib.Path(sys.argv[1]))
```

- [ ] **Step 2: Write the screenshot script**

```javascript
// frontend/scripts/email-previews.mjs
// Screenshot every *.html in DIR at phone width. Run from frontend/:
//   node scripts/email-previews.mjs /path/to/dir
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const dir = path.resolve(process.argv[2]);
const browser = await chromium.launch();
for (const f of fs.readdirSync(dir).filter((f) => f.endsWith(".html"))) {
  const page = await browser.newPage({ viewport: { width: 390, height: 800 }, deviceScaleFactor: 2 });
  await page.goto("file://" + path.join(dir, f));
  await page.screenshot({ path: path.join(dir, f.replace(".html", ".png")), fullPage: true });
  console.log("shot", f);
}
await browser.close();
```

- [ ] **Step 3: Run both**

```bash
backend/.venv/bin/python -m backend.v2.tests.fixtures.email_previews.render_previews /private/tmp/claude-501/-Users-ramc-Documents-Code-academy-manager/1786f2f3-3132-4754-bb74-917e9e32a660/scratchpad/mockups
cd frontend && node scripts/email-previews.mjs /private/tmp/claude-501/-Users-ramc-Documents-Code-academy-manager/1786f2f3-3132-4754-bb74-917e9e32a660/scratchpad/mockups
```
Expected: 7 html + 7 png files.

- [ ] **Step 4: Commit**

```bash
git add backend/v2/tests/fixtures/email_previews frontend/scripts/email-previews.mjs
git commit -m "chore(comms): checked-in email mockup pipeline (render + phone-width screenshots)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: MOCKUP GATE — show the owner, stop

- [ ] Send all 7 PNGs to the owner with `SendUserFile` (display `render`) and a one-line summary of what changed per template.
- [ ] Wait for feedback. Apply requested changes to Tasks 1–6 files, re-run Task 7 Step 3, re-send. Do not start Task 9 until the owner says the mockups are approved.

---

### Task 9: Plain-text twin in the Resend adapter

**Files:**
- Modify: `backend/v2/contexts/communications/infrastructure/resend_send_port.py:117-124`
- Test: existing `backend/v2/tests/infrastructure/test_resend_send_port.py` (find with `grep -rln "resend" backend/v2/tests/infrastructure`)

- [ ] **Step 1: Failing test** (add to the Resend port test module, using its existing monkeypatched `resend.Emails.send` capture)

```python
async def test_send_includes_plain_text_twin(monkeypatch) -> None:
    captured: dict = {}

    def fake_send(params):  # noqa: ANN001
        captured.update(params)
        return {"id": "m1"}

    monkeypatch.setattr("resend.Emails.send", fake_send)
    port = ResendEmailSendPort(api_key="k", from_address="a@b.test")  # match the existing ctor
    await port.send(
        recipient=ResolvedRecipient(user_id="u", email="p@x.test", display_name=None),
        subject="s",
        body='<p>Hello <a href="https://x.test/pay">Pay now</a></p>',
    )
    assert captured["text"] == "Hello Pay now (https://x.test/pay)"
```

- [ ] **Step 2: Run to verify failure**: `KeyError: 'text'`.

- [ ] **Step 3: Implement**

```python
from backend.v2.shared.comms.email_theme import html_to_text
# ...
            params: resend.Emails.SendParams = {
                "from": self._from_address,
                "to": [recipient.email],
                "subject": subject,
                "html": body,
            }
            try:
                params["text"] = html_to_text(body)
            except Exception:  # a text twin is a bonus, never a blocker
                log.warning("plain-text twin generation failed", exc_info=True)
```

- [ ] **Step 4: Run** the infrastructure tests. **Step 5: Commit** `feat(comms): send a plain-text part alongside HTML`.

---

### Task 10: Parent digest provider gathers groups, overdue flag, brand

**Files:**
- Modify: `backend/v2/contexts/communications/application/ports.py` (add Protocols)
- Modify: `backend/v2/contexts/communications/application/use_cases/send_parent_daily_digest.py:64-80, 123-131`
- Modify: `backend/v2/composition/digests.py:363-470, 629-652, 883-911, 912-931`
- Test: `backend/v2/tests/composition/test_parent_digest_provider.py`, `backend/v2/tests/application/test_send_parent_daily_digest.py`

**Interfaces:**
- Produces in `ports.py`:

```python
class AcademyBrandLookup(Protocol):
    async def brand_for(self, academy_id: str) -> EmailBrand | None: ...


class CoachGroupLinkProvider(Protocol):
    async def for_coach(self, coach_id: str) -> Sequence[WhatsAppGroupLink]: ...
```
- `SendParentDailyDigest.brands: AcademyBrandLookup | None = None`, resolved once per run via `_brand(academy_id)` that swallows exceptions → `None`.
- `_ParentDigestProvider.build_view` fills `whatsapp_groups` and `DuesView.is_overdue`.
- `composition/digests.py`: `_AcademyBrandLookup(academies)` mapping academy doc `display_name`, `brand_color`, `logo_url`, `contact_email`, `contact_phone` → `EmailBrand`.

- [ ] **Step 1: Failing provider tests** (append to `test_parent_digest_provider.py`; reuse `_full_family_provider`)

```python
from backend.v2.contexts.communications.application.whatsapp_groups_block import WhatsAppGroupLink


async def test_groups_cover_every_active_enrollment_not_just_today() -> None:
    today_session = SimpleNamespace(session_id="sess-1", title="Beginner", location="YWCA", timezone="UTC",
                                    whatsapp_group_link="https://chat.whatsapp.com/AAA")
    saturday = SimpleNamespace(session_id="sess-2", title="Saturday Open", location="Gym", timezone="UTC",
                               whatsapp_group_link="https://chat.whatsapp.com/BBB")
    no_link = SimpleNamespace(session_id="sess-3", title="Camp", location="", timezone="UTC", whatsapp_group_link=None)
    provider = _full_family_provider(
        enrollments=[SimpleNamespace(session_id="sess-1"), SimpleNamespace(session_id="sess-2"), SimpleNamespace(session_id="sess-3")],
        session=today_session,
    )
    provider._sessions.get_many = AsyncMock(return_value=[today_session, saturday, no_link])
    with tenant_scope("acad"):
        view = await provider.build_view("parent-1", date(2026, 9, 3))
    assert view is not None
    assert view.whatsapp_groups == (
        WhatsAppGroupLink(label="Beginner @ YWCA", url="https://chat.whatsapp.com/AAA", child_names=("Maithri",)),
        WhatsAppGroupLink(label="Saturday Open @ Gym", url="https://chat.whatsapp.com/BBB", child_names=("Maithri",)),
    )


async def test_group_lookup_failure_yields_no_block_not_a_crash() -> None:
    provider = _full_family_provider()
    provider._sessions.get_many = AsyncMock(side_effect=RuntimeError("mongo down"))
    with tenant_scope("acad"):
        view = await provider.build_view("parent-1", date(2026, 9, 3))
    assert view is not None and view.whatsapp_groups == ()


async def test_dues_overdue_flag() -> None:
    past = SimpleNamespace(balance_due_cents=6000, status="open", due_date=datetime(2026, 8, 10, tzinfo=UTC))
    provider = _full_family_provider(invoices=[past])
    with tenant_scope("acad"):
        view = await provider.build_view("parent-1", date(2026, 9, 3))
    assert view.dues is not None and view.dues.is_overdue is True
    future = SimpleNamespace(balance_due_cents=6000, status="open", due_date=datetime(2026, 9, 10, tzinfo=UTC))
    provider = _full_family_provider(invoices=[future])
    with tenant_scope("acad"):
        view = await provider.build_view("parent-1", date(2026, 9, 3))
    assert view.dues is not None and view.dues.is_overdue is False
```

(Check the module's existing imports for `date`, `datetime`, `UTC`, `AsyncMock`, `SimpleNamespace`, `tenant_scope`; add any missing.)

- [ ] **Step 2: Failing use-case test** (append to `test_send_parent_daily_digest.py`)

```python
async def test_brand_lookup_reaches_the_shell() -> None:
    # Build the use case the way the module's other tests do (`_build(...)`),
    # then set `use_case.brands = SimpleNamespace(brand_for=AsyncMock(return_value=EmailBrand(academy_name="Brand Co")))`
    # execute, and assert "Brand Co" in sender.sent[0]["body"].
```
Write it concretely against the file's existing `_build` helper.

- [ ] **Step 3: Run to verify failure**, then implement.

`ports.py` — add near `AcademySlugLookup`:

```python
from collections.abc import Sequence

from backend.v2.contexts.communications.application.whatsapp_groups_block import (
    WhatsAppGroupLink,
)
from backend.v2.shared.comms.email_theme import EmailBrand


class AcademyBrandLookup(Protocol):
    """Academy name/colour/logo/contact for the email shell. ``None`` → defaults."""

    async def brand_for(self, academy_id: str) -> EmailBrand | None: ...


class CoachGroupLinkProvider(Protocol):
    """WhatsApp group links for every session a coach is assigned to."""

    async def for_coach(self, coach_id: str) -> Sequence[WhatsAppGroupLink]: ...
```

`send_parent_daily_digest.py`:

```python
    brands: AcademyBrandLookup | None = None

    async def _brand(self, academy_id: str) -> EmailBrand | None:
        if self.brands is None:
            return None
        try:
            return await self.brands.brand_for(academy_id)
        except Exception:
            return None
```
Resolve `brand = await self._brand(command.academy_id)` next to `academy_slug`, and pass `brand=brand` into `render_parent_digest`.

`composition/digests.py` — parent provider:

```python
    async def build_view(...):
        ...  # after `if not children: return None`
        whatsapp_groups = await self._whatsapp_groups(children_students)
        ...
        return ParentDigestView(..., whatsapp_groups=whatsapp_groups)

    async def _whatsapp_groups(self, children_students: list[Any]) -> tuple[WhatsAppGroupLink, ...]:
        """Every ACTIVE enrollment's session link, across all children, deduped
        by URL. Any failure logs and yields no block: this must never cost a
        family its digest."""
        try:
            by_session: dict[str, list[str]] = {}
            for student in children_students:
                for enrollment in await self._enrollments.active_for_student(student.student_id):
                    by_session.setdefault(enrollment.session_id, []).append(student.full_name)
            if not by_session:
                return ()
            sessions = await self._sessions.get_many(list(by_session))
            links = [
                WhatsAppGroupLink(
                    label=self._session_label(session),
                    url=session.whatsapp_group_link,
                    child_names=tuple(by_session.get(session.session_id, ())),
                )
                for session in sessions
                if getattr(session, "whatsapp_group_link", None)
            ]
            return dedupe_group_links(links)
        except Exception:
            log.warning("parent digest: whatsapp group lookup failed", exc_info=True)
            return ()
```
(Add `log = logging.getLogger(__name__)` if the module lacks one; import `WhatsAppGroupLink, dedupe_group_links`.)

`_dues`: compute `is_overdue = earliest is not None and (earliest.date() if isinstance(earliest, datetime) else earliest) < datetime.now(UTC).date()` and pass `is_overdue=is_overdue`.

Brand lookup class next to `_AcademySlugLookup`:

```python
class _AcademyBrandLookup:
    """``AcademyBrandLookup`` over the academy document (fields set on the
    admin Settings → Academy page)."""

    def __init__(self, academies: Any) -> None:
        self._academies = academies

    async def brand_for(self, academy_id: str) -> EmailBrand | None:
        doc = await self._academies.find_by_id(academy_id)
        if not doc:
            return None
        return EmailBrand(
            academy_name=str(doc.get("display_name") or academy_id),
            brand_color=doc.get("brand_color") or None,
            logo_url=doc.get("logo_url") or None,
            contact_email=doc.get("contact_email") or None,
            contact_phone=doc.get("contact_phone") or None,
        )
```
Wire `brands=_AcademyBrandLookup(MongoAcademyRepository(db))` in `compose_send_parent_daily_digest`.

- [ ] **Step 4: Run** `backend/.venv/bin/python -m pytest backend/v2/tests/composition/test_parent_digest_provider.py backend/v2/tests/application/test_send_parent_daily_digest.py -q`. Expected: pass.

- [ ] **Step 5: Commit** `feat(comms): parent digest lists every enrolled class's WhatsApp group; overdue-aware dues; academy brand in shell`.

---

### Task 11: Coach digest use case gets group links + brand

**Files:**
- Modify: `backend/v2/contexts/communications/application/use_cases/send_coach_daily_digest.py:86-97, 146-152`
- Modify: `backend/v2/contexts/communications/application/use_cases/send_coach_digest_test.py` (same two additions)
- Modify: `backend/v2/composition/digests.py:267-332`
- Test: `backend/v2/tests/application/test_send_coach_daily_digest.py`, new `backend/v2/tests/composition/test_coach_group_link_provider.py`

- [ ] **Step 1: Failing tests**

```python
# append to test_send_coach_daily_digest.py
async def test_group_links_and_brand_reach_the_email() -> None:
    sender, use_case = _build(coaches=[_coach("coach-1")], plans={"coach-1": _populated_plan()})  # adapt to the file's helper
    use_case.group_links = SimpleNamespace(for_coach=AsyncMock(return_value=[
        WhatsAppGroupLink(label="Tuesday Juniors", url="https://chat.whatsapp.com/AAA")
    ]))
    use_case.brands = SimpleNamespace(brand_for=AsyncMock(return_value=EmailBrand(academy_name="Brand Co")))
    await use_case.execute(SendCoachDailyDigestCommand(academy_id="acad", digest_date=date(2026, 6, 12)))
    body = sender.sent[0]["body"]
    assert GROUP_BLOCK_HEADING in body and "Brand Co" in body


async def test_group_link_provider_failure_does_not_block_send() -> None:
    sender, use_case = _build(coaches=[_coach("coach-1")], plans={"coach-1": _populated_plan()})
    use_case.group_links = SimpleNamespace(for_coach=AsyncMock(side_effect=RuntimeError("x")))
    result = await use_case.execute(SendCoachDailyDigestCommand(academy_id="acad", digest_date=date(2026, 6, 12)))
    assert result.sent == 1
```

```python
# backend/v2/tests/composition/test_coach_group_link_provider.py
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.v2.composition.digests import _CoachGroupLinkProvider
from backend.v2.contexts.communications.application.whatsapp_groups_block import WhatsAppGroupLink


async def test_only_assigned_sessions_with_links_and_not_cancelled() -> None:
    sessions = SimpleNamespace(
        assigned_session_ids_for_coach=AsyncMock(return_value=["s1", "s2", "s3"]),
        get_many=AsyncMock(return_value=[
            SimpleNamespace(session_id="s1", title="Juniors", location="Court A", status="scheduled", whatsapp_group_link="https://chat.whatsapp.com/A"),
            SimpleNamespace(session_id="s2", title="Old", location="", status="cancelled", whatsapp_group_link="https://chat.whatsapp.com/B"),
            SimpleNamespace(session_id="s3", title="NoLink", location="", status="scheduled", whatsapp_group_link=None),
        ]),
    )
    links = await _CoachGroupLinkProvider(sessions=sessions).for_coach("coach-1")
    assert links == (WhatsAppGroupLink(label="Juniors @ Court A", url="https://chat.whatsapp.com/A"),)
```

- [ ] **Step 2: Run to verify failure**, then implement.

Use case (`send_coach_daily_digest.py` and `send_coach_digest_test.py`):

```python
    brands: AcademyBrandLookup | None = None
    group_links: CoachGroupLinkProvider | None = None

    async def _brand(self, academy_id: str) -> EmailBrand | None:
        if self.brands is None:
            return None
        try:
            return await self.brands.brand_for(academy_id)
        except Exception:
            return None

    async def _groups(self, coach_id: str) -> Sequence[WhatsAppGroupLink]:
        if self.group_links is None:
            return ()
        try:
            return await self.group_links.for_coach(coach_id)
        except Exception:
            return ()
```
Resolve `brand` once per run; per coach call `groups = await self._groups(coach.user_id)` and pass `brand=brand, whatsapp_groups=groups` into `render_coach_digest`.

Composition:

```python
class _CoachGroupLinkProvider:
    """``CoachGroupLinkProvider`` over the enrollment session repo: every
    session assigned to the coach (no date window — a running Tue/Thu series
    has a `start_at` months in the past), minus cancelled ones and ones with
    no link."""

    def __init__(self, *, sessions: Any) -> None:
        self._sessions = sessions

    async def for_coach(self, coach_id: str) -> tuple[WhatsAppGroupLink, ...]:
        ids = await self._sessions.assigned_session_ids_for_coach(coach_id)
        if not ids:
            return ()
        sessions = await self._sessions.get_many(list(ids))
        links = [
            WhatsAppGroupLink(label=_ParentDigestProvider._session_label(s), url=s.whatsapp_group_link)
            for s in sessions
            if getattr(s, "whatsapp_group_link", None) and str(getattr(s, "status", "")) != "cancelled"
        ]
        return dedupe_group_links(links)
```
Add `group_links` and `brands` to `_DigestParts` and wire them in `_build_digest_parts` (`_CoachGroupLinkProvider(sessions=sessions_repo)`, `_AcademyBrandLookup(MongoAcademyRepository(db))`), then pass both into `SendCoachDailyDigest(...)` and `SendCoachDigestTest(...)`.

- [ ] **Step 3: Run** the two test modules + `backend/v2/tests/composition -q`. **Step 4: Commit** `feat(comms): coach digest lists the WhatsApp groups for every assigned class`.

---

### Task 12: Tighten the link validator to chat.whatsapp.com + form helper text

**Files:**
- Modify: `backend/v2/shared/security/external_url.py` (add function)
- Modify: `backend/v2/contexts/enrollment/domain/models.py:58-70`, `backend/v2/contexts/enrollment/application/use_cases/admin_writes.py:455-459`, `backend/v2/interfaces/admin/views.py` (`_validated_group_link`)
- Modify: `frontend/app/(admin)/admin/sessions/[id]/SessionEditing.tsx:434-470`
- Test: `backend/v2/tests/unit/test_session_communication_pack.py`, `backend/v2/tests/interface/test_admin_sessions.py:2720-2760`

- [ ] **Step 1: Failing tests**

```python
# test_session_communication_pack.py
@pytest.mark.parametrize("bad", ["https://wa.me/15550100100", "https://example.com/chat.whatsapp.com/x", "https://chat.whatsapp.com/", "https://chat.whatsapp.com/a b"])
def test_non_group_whatsapp_links_are_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        _session(whatsapp_group_link=bad)


def test_group_link_host_is_case_insensitive() -> None:
    assert _session(whatsapp_group_link="https://Chat.WhatsApp.com/AbCd1234").whatsapp_group_link == "https://Chat.WhatsApp.com/AbCd1234"
```

Add `"https://wa.me/15550100100"` to the bad-link parametrisation in `test_admin_sessions.py` around line 2728 (expects 422).

- [ ] **Step 2: Implement**

```python
# external_url.py
_WHATSAPP_GROUP_HOST = "chat.whatsapp.com"
_WHATSAPP_TOKEN = re.compile(r"^/[A-Za-z0-9_-]{1,64}$")


def validate_whatsapp_group_link(value: str | None) -> str | None:
    """A WhatsApp *group invite* link only: ``https://chat.whatsapp.com/<token>``.

    ``wa.me`` and phone links open a personal chat, not a group; a paste of
    one here would send every family a dead link.
    """
    candidate = validate_external_url(value, field_label="WhatsApp group link")
    if candidate is None:
        return None
    parsed = urlparse(candidate)
    if parsed.scheme.lower() != "https" or parsed.netloc.lower() != _WHATSAPP_GROUP_HOST:
        raise InvalidExternalUrl(
            "The WhatsApp group link must start with https://chat.whatsapp.com/ "
            "(WhatsApp › Group info › Invite link)."
        )
    if not _WHATSAPP_TOKEN.match(parsed.path):
        raise InvalidExternalUrl("The WhatsApp group link is missing its invite code.")
    return candidate
```
Replace the three `validate_external_url(value, field_label="WhatsApp group link")` call sites with `validate_whatsapp_group_link(value)`.

Frontend: replace `looksLikeWebUrl(link)` check with `const linkLooksWrong = link !== "" && !/^https:\/\/chat\.whatsapp\.com\/[A-Za-z0-9_-]+$/i.test(link);` and the helper text with `Paste the invite link from WhatsApp › Group info › Invite link. It starts with https://chat.whatsapp.com/`. Add a permanent hint under the input (`<p className="text-xs text-rally-muted">`) with the same sentence when the link is empty.

- [ ] **Step 3: Run** `backend/.venv/bin/python -m pytest backend/v2/tests/unit/test_session_communication_pack.py backend/v2/tests/interface/test_admin_sessions.py -q -k "whatsapp or pack"` and `cd frontend && npx tsc --noEmit && npx vitest run app/\(admin\)/admin/sessions` (if a vitest exists for the page; otherwise `npm run lint`).

- [ ] **Step 4: Commit** `fix(enrollment): accept only chat.whatsapp.com invite links for the class group`.

---

### Task 13: Full gate, spec sync, PR

- [ ] Fix the spec's one leftover `Session.whatsapp_group_url` mention (architecture diagram line) → `whatsapp_group_link`; remove the "shows due date" and "tue, thu" items (not applicable), and the audit-script sentence (YAGNI).
- [ ] Run: `backend/.venv/bin/ruff check backend/v2 && backend/.venv/bin/ruff format --check backend/v2 && backend/.venv/bin/mypy backend/v2 && backend/.venv/bin/python -m pytest backend/v2/tests -q -n auto`
- [ ] Re-run Task 7 Step 3 and attach the final PNGs to the PR body.
- [ ] Add the release note file the CI gate requires (see `docs/release-notes/` convention: 3 exact sections, real PR number — open the PR first with a placeholder body, then add the note in a follow-up commit).
- [ ] `git push origin HEAD:refs/heads/feat/whatsapp-groups-slice1` and `gh pr create --base main --title "feat(comms): WhatsApp class groups in digests + unified Rally email theme" --body-file <body>` ending with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
