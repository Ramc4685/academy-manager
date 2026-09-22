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
    brand = t.EmailBrand(academy_name="Acme", logo_url='https://cdn.test/logo.png" onerror=x')
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
    # Light blue: white text fails AA (1.65:1), so the button switches to ink.
    assert f"color:{t.INK}" in custom
    assert "color:#ffffff" not in custom


def test_primary_button_text_colour_meets_aa_on_brand_colour() -> None:
    light = {"#FFD400": "#ffd400", "#F5F5F5": "#f5f5f5", t.VOLT: t.VOLT}
    for accent, background in light.items():
        out = t.button("Go", "https://x.test", accent=accent)
        assert f"background:{background};color:{t.INK};border:1px solid {background};" in out
    dark = {"#1F2937": "#1f2937", "#000000": "#000000", t.COBALT: t.COBALT}
    for accent, background in dark.items():
        out = t.button("Go", "https://x.test", accent=accent)
        assert f"background:{background};color:#ffffff;border:1px solid {background};" in out
    # Mid-tones that pass with one of the two text colours keep their fill.
    assert f"background:#3b82f6;color:{t.INK};" in t.button(
        "Go", "https://x.test", accent="#3B82F6"
    )
    assert "background:#e11d48;color:#ffffff;" in t.button("Go", "https://x.test", accent="#E11D48")


def test_primary_button_darkens_fill_when_neither_text_colour_passes() -> None:
    out = t.button("Go", "https://x.test", accent="#7a7a7a")
    assert "background:#7a7a7a" not in out
    assert "background:#767677;color:#ffffff;border:1px solid #767677;" in out


def test_secondary_button_ignores_accent() -> None:
    out = t.button("Join", "https://x.test", accent="#FFD400", variant="secondary")
    assert f"background:#ffffff;color:{t.INK};" in out


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
