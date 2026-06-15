"""Seed lesson cards and curriculum video references from the content JSON.

All teaching content seeded here is ORIGINAL academy wording (see the JSON
``_license_note`` and the :class:`LessonCard` docstring). BWF Shuttle Time is
cited as a structural reference only; no copyrighted lesson text is stored.

Idempotent: cards upsert by ``(academy_id, program_id, slug)`` and video refs
upsert by their identity tuple, both keyed on a ``content_hash`` so a reseed
is a no-op unless the JSON entry changed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.v2.contexts.curriculum.application.ports import (
    CurriculumVideoRefRepository,
    LessonCardRepository,
    LevelRepository,
    ProgramRepository,
    SkillRepository,
)
from backend.v2.contexts.curriculum.domain.models import (
    CurriculumVideoRef,
    LessonCard,
    LessonResourceLink,
)
from backend.v2.shared.ids import new_ulid

_CONTENT_PATH = Path(__file__).resolve().parents[2] / "content" / "badminton_lesson_cards.json"


class PathwayNotSeededError(Exception):
    """Raised when no active badminton program exists to attach cards to."""


class LessonCardSeedError(Exception):
    """Raised when the content JSON references a level/skill that does not resolve."""


@dataclass
class LessonCardSeedResult:
    program_id: str
    cards_created: int = 0
    cards_updated: int = 0
    cards_unchanged: int = 0
    video_refs_created: int = 0
    video_refs_updated: int = 0
    video_refs_unchanged: int = 0


def _hash(entry: object) -> str:
    return hashlib.sha256(
        json.dumps(entry, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def load_content(content_path: Path | None = None) -> dict[str, Any]:
    path = content_path or _CONTENT_PATH
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


async def seed_lesson_cards(
    *,
    academy_id: str,
    programs: ProgramRepository,
    levels: LevelRepository,
    skills: SkillRepository,
    cards: LessonCardRepository,
    video_refs: CurriculumVideoRefRepository,
    created_by: str = "system",
    program_id: str | None = None,
    content_path: Path | None = None,
) -> LessonCardSeedResult:
    content = load_content(content_path)

    if program_id:
        program = await programs.get(program_id)
        if program is not None and (not program.is_active or program.sport != "badminton"):
            program = None
    else:
        program = None
        for prog in await programs.list_active():
            if prog.sport == "badminton":
                program = prog
                break
    if program is None:
        raise PathwayNotSeededError(
            "No active badminton program found. Seed the pathway before lesson cards."
        )

    # Cards reference curriculum by sequence; ids are per-academy ULIDs, so
    # resolve sequence -> id once up front.
    level_by_seq: dict[int, str] = {}
    skill_by: dict[tuple[int, int], str] = {}
    for level in await levels.list_for_program(program.program_id):
        level_by_seq[level.sequence] = level.level_id
        for skill in await skills.list_for_level(level.level_id):
            skill_by[(level.sequence, skill.sequence)] = skill.skill_id

    now = datetime.now(UTC)
    result = LessonCardSeedResult(program_id=program.program_id)
    source = content.get("source", "BWF_SHUTTLE_TIME")

    for entry in content.get("cards", []):
        level_seq = int(entry["level_sequence"])
        level_id = level_by_seq.get(level_seq)
        if level_id is None:
            raise LessonCardSeedError(
                f"Card {entry['slug']}: level_sequence {level_seq} does not resolve."
            )
        skill_ids: list[str] = []
        for skill_seq in entry.get("skill_sequences", []):
            skill_id = skill_by.get((level_seq, int(skill_seq)))
            if skill_id is None:
                raise LessonCardSeedError(
                    f"Card {entry['slug']}: skill_sequence "
                    f"{level_seq}.{skill_seq} does not resolve."
                )
            skill_ids.append(skill_id)

        content_hash = _hash(entry)
        existing = await cards.get_by_slug(program.program_id, entry["slug"])
        card = LessonCard(
            card_id=existing.card_id if existing else str(new_ulid()),
            academy_id=academy_id,
            program_id=program.program_id,
            level_id=level_id,
            skill_ids=skill_ids,
            slug=entry["slug"],
            lesson_number=int(entry["lesson_number"]),
            title=entry["title"],
            goal_summary=entry.get("goal_summary", ""),
            teaching_points=list(entry.get("teaching_points", [])),
            equipment=list(entry.get("equipment", [])),
            activity_summary=entry.get("activity_summary", ""),
            safety_notes=list(entry.get("safety_notes", [])),
            source=source,
            module_name=entry.get("module_name", ""),
            lesson_range=entry.get("lesson_range", ""),
            page_hint=entry.get("page_hint"),
            resource_links=[
                LessonResourceLink(kind=link["kind"], title=link["title"], url=link.get("url"))
                for link in entry.get("resource_links", [])
            ],
            content_hash=content_hash,
            display_order=int(entry.get("display_order", 0)),
            is_active=True,
            created_at=existing.created_at if existing else now,
            updated_at=now,
            created_by=existing.created_by if existing else created_by,
        )
        if existing is None:
            await cards.save(card)
            result.cards_created += 1
        elif existing.content_hash != content_hash:
            await cards.replace(card)
            result.cards_updated += 1
        else:
            result.cards_unchanged += 1

    await _seed_video_refs(
        content=content,
        academy_id=academy_id,
        program_id=program.program_id,
        level_by_seq=level_by_seq,
        skill_by=skill_by,
        video_refs=video_refs,
        created_by=created_by,
        now=now,
        result=result,
    )
    return result


async def _seed_video_refs(
    *,
    content: dict[str, Any],
    academy_id: str,
    program_id: str,
    level_by_seq: dict[int, str],
    skill_by: dict[tuple[int, int], str],
    video_refs: CurriculumVideoRefRepository,
    created_by: str,
    now: datetime,
    result: LessonCardSeedResult,
) -> None:
    items: list[tuple[str, str, str | None, dict[str, Any]]] = []
    for entry in content.get("level_videos", []):
        level_seq = int(entry["level_sequence"])
        level_id = level_by_seq.get(level_seq)
        if level_id is None:
            raise LessonCardSeedError(f"level_video: level_sequence {level_seq} does not resolve.")
        items.append(("LEVEL", level_id, None, entry))
    for entry in content.get("skill_videos", []):
        level_seq = int(entry["level_sequence"])
        skill_seq = int(entry["skill_sequence"])
        level_id = level_by_seq.get(level_seq)
        skill_id = skill_by.get((level_seq, skill_seq))
        if level_id is None or skill_id is None:
            raise LessonCardSeedError(f"skill_video: {level_seq}.{skill_seq} does not resolve.")
        items.append(("SKILL", level_id, skill_id, entry))

    for scope, level_id, skill_id, entry in items:
        url = entry["url"]
        content_hash = _hash(entry)
        existing = await video_refs.get_by_identity(
            scope=scope, level_id=level_id, skill_id=skill_id, url=url
        )
        ref = CurriculumVideoRef(
            ref_id=existing.ref_id if existing else str(new_ulid()),
            academy_id=academy_id,
            program_id=program_id,
            scope=scope,  # type: ignore[arg-type]
            level_id=level_id,
            skill_id=skill_id,
            title=entry["title"],
            url=url,
            display_order=int(entry.get("display_order", 0)),
            content_hash=content_hash,
            is_active=True,
            created_at=existing.created_at if existing else now,
            created_by=existing.created_by if existing else created_by,
        )
        if existing is None:
            await video_refs.save(ref)
            result.video_refs_created += 1
        elif existing.content_hash != content_hash:
            await video_refs.replace(ref)
            result.video_refs_updated += 1
        else:
            result.video_refs_unchanged += 1
