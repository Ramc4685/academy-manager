"""The composition shell delegates to the shared theme."""

from __future__ import annotations

from backend.v2.composition.email_adapters import _branded_button, _branded_shell
from backend.v2.shared.comms.email_theme import COBALT, FONT_STACK, MAX_WIDTH, EmailBrand


def test_branded_shell_uses_theme_and_has_no_reminder_footer_by_default() -> None:
    out = _branded_shell(academy_name="BLNO <Badminton>", inner_html="<p>x</p>")
    assert FONT_STACK in out
    assert f"max-width:{MAX_WIDTH}px" in out
    assert "BLNO &lt;Badminton&gt;" in out
    assert "please disregard" not in out


def test_branded_shell_reminder_footer_opt_in() -> None:
    out = _branded_shell(
        academy_name="A",
        inner_html="",
        footer_note="If you've already paid, please disregard this message.",
    )
    assert "please disregard" in out


def test_branded_button_is_theme_button() -> None:
    out = _branded_button(label="Pay", url="https://x.test")
    assert f"background:{COBALT}" in out


def test_branded_shell_carries_the_full_academy_brand_when_given() -> None:
    out = _branded_shell(
        academy_name="BLNO Badminton",
        inner_html="<p>x</p>",
        brand=EmailBrand(
            academy_name="ignored: the subject's name wins",
            logo_url="https://cdn.test/logo.png",
            brand_color="#0F766E",
            contact_email="desk@blno.test",
        ),
    )
    assert '<img src="https://cdn.test/logo.png" alt="BLNO Badminton"' in out
    assert "background:#0f766e" in out
    assert "Sent by BLNO Badminton<br />desk@blno.test" in out
    assert "ignored" not in out


def test_branded_shell_without_brand_is_unchanged() -> None:
    plain = _branded_shell(academy_name="BLNO Badminton", inner_html="<p>x</p>")
    same = _branded_shell(
        academy_name="BLNO Badminton",
        inner_html="<p>x</p>",
        brand=EmailBrand(academy_name="BLNO Badminton"),
    )
    assert plain == same
