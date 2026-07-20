"""View model for the parent daily digest email.

This is the *contract* between the composition-root data provider (which reaches
across billing / student_progress / enrollment to assemble it) and the renderer
(which turns it into HTML). Keeping it a plain typed DTO — rather than
duck-typing the way the coach digest does — lets the renderer stay a pure
function with an explicit shape, and keeps communications free of any
cross-context import (ADR-0005): the provider constructs these dataclasses; the
renderer only reads them.

``on_portal`` selects the variant:

* ``True``  → Variant A: full digest with per-child can't-make-it links,
  progress bars, and (when applicable) dues + autopay rows that deep-link into
  the parent portal.
* ``False`` → Variant B: the portal links would dead-end at a login screen, so
  they collapse into a single "set up your account" call to action. When a
  balance is owed that CTA is dues-forward ("set up account & pay"); otherwise
  it is a soft "follow along" nudge.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChildDigestView:
    """One enrolled child with a session today."""

    child_name: str
    session_time: str  # e.g. "6:00 - 6:45 PM"
    session_label: str  # e.g. "Beginner @ YWCA"
    focus_skill: str = ""  # e.g. "Thumb grip"
    focus_status: str = ""  # e.g. "practicing" (already lowercased/spaced)
    level_name: str = ""  # e.g. "Level 1"
    skills_completed: int = 0
    skills_total: int = 0
    skills_left: int = 0
    levels_to_go: int = 0
    # Deep link into the portal attendance page with today's session
    # pre-selected. ``None`` in Variant B (no portal to link into).
    cant_make_it_url: str | None = None


@dataclass(frozen=True, slots=True)
class DuesView:
    """An outstanding balance for the family."""

    amount: str  # formatted, e.g. "$60.00"
    due_date: str  # formatted, e.g. "July 10"
    pay_url: str


@dataclass(frozen=True, slots=True)
class ParentDigestView:
    """Everything one family's morning digest needs.

    ``build_view`` returns ``None`` (not an empty view) when the family has no
    session today, so the send use case can skip them without emailing.
    """

    parent_name: str
    date_label: str  # e.g. "Thursday, July 16"
    program_name: str
    children: tuple[ChildDigestView, ...]
    on_portal: bool
    # Present only when a balance is owed (either variant).
    dues: DuesView | None = None
    # Variant A only: whether the family already has autopay. When False we show
    # the autopay nudge. Ignored in Variant B.
    autopay_enabled: bool = True
    # Variant A footer link into the portal.
    portal_url: str = ""
    # Variant B single CTA: the invite link with a continue-URL that lands on
    # the payments page after the parent sets a password.
    activate_url: str = ""
    # Variant B absence fallback ("reply to this email and we'll tell the
    # coach"). When set, shown as a reply-to hint.
    reply_to: str | None = None

    def has_children(self) -> bool:
        return bool(self.children)
