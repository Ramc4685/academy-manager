from __future__ import annotations

from backend.v2.contexts.communications.application.whatsapp_groups_block import (
    COACH_GROUP_NOTE,
    GROUP_BLOCK_HEADING,
    PARENT_GROUP_NOTE,
    WhatsAppGroupLink,
    dedupe_group_links,
    render_whatsapp_groups_block,
)

L1 = WhatsAppGroupLink(
    label="Beginner @ YWCA", url="https://chat.whatsapp.com/AAA", child_names=("Maithri",)
)
L2 = WhatsAppGroupLink(
    label="Intermediate @ YWCA", url="https://chat.whatsapp.com/BBB", child_names=("Arjun",)
)


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
