"""The composition shell delegates to the shared theme."""

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
        academy_name="A",
        inner_html="",
        footer_note="If you've already paid, please disregard this message.",
    )
    assert "please disregard" in out


def test_branded_button_is_theme_button() -> None:
    out = _branded_button(label="Pay", url="https://x.test")
    assert f"background:{COBALT}" in out
