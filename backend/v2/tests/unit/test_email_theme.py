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
