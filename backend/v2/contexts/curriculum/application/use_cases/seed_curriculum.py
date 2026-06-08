"""Seed the Badminton Skill Pathway curriculum.

This use case creates the academy's own badminton skill pathway.
It uses BWF Shuttle Time as an external structural reference ONLY.
No BWF lesson text, drill descriptions, or copyrighted content
is stored in any field. Only reference metadata is stored
(source name, module, lesson range, title, page hint, internal note).
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.curriculum.application.ports import (
    CriterionRepository,
    ExternalRefRepository,
    LevelRepository,
    ProgramRepository,
    SkillRepository,
)
from backend.v2.contexts.curriculum.domain.models import (
    ExternalLessonReference,
    Level,
    Program,
    Skill,
    SkillCriterion,
)
from backend.v2.shared.ids import new_ulid

_BADMINTON_PATHWAY_SLUG = "badminton-skill-pathway-v1"


# ---------------------------------------------------------------------------
# Curriculum data — academy's own progression model (not BWF content)
# ---------------------------------------------------------------------------

_LEVELS: list[dict] = [
    {
        "sequence": 1,
        "name": "Grip and Control",
        "description": "Foundation level — racket grip, shuttle control, and basic rallying.",
        "skills": [
            {
                "sequence": 1,
                "name": "Thumb grip",
                "description": "Demonstrate the backhand thumb grip.",
                "criteria": [
                    "Thumb is flat on back of handle",
                    "Back of hand leads on contact",
                    "Elbow in front of body",
                ],
            },
            {
                "sequence": 2,
                "name": "V grip",
                "description": "Demonstrate the forehand V grip.",
                "criteria": [
                    "V shape between thumb and forefinger",
                    "Palm faces shuttle on contact",
                    "Fingers are spread and relaxed",
                ],
            },
            {
                "sequence": 3,
                "name": "Grip change",
                "description": "Switch cleanly between thumb and V grip.",
                "criteria": [
                    "Changes grip by rolling with thumb",
                    "No full hand turn required",
                    "10 consecutive clean changes",
                ],
            },
            {
                "sequence": 4,
                "name": "Ready position",
                "description": "Hold correct ready position before each shot.",
                "criteria": [
                    "Knees slightly flexed",
                    "Weight on front of feet",
                    "Racket held in front of body above wrist height",
                ],
            },
            {
                "sequence": 5,
                "name": "Shuttle control",
                "description": "Keep shuttle in the air using controlled taps.",
                "criteria": [
                    "20 consecutive controlled taps without drop",
                    "Uses appropriate grip for each tap",
                ],
            },
            {
                "sequence": 6,
                "name": "Basic rally control",
                "description": "Complete a short cooperative rally with a partner.",
                "criteria": [
                    "5-shot cooperative rally completed",
                    "Shuttle travels cleanly over the net or marker",
                    "Player returns to ready position after each shot",
                ],
            },
        ],
        "ext_ref": {
            "module_name": "Starter Lessons",
            "lesson_range": "1-2",
            "reference_title": "Basic grips and grip changes",
            "page_hint": "p.9-15",
        },
    },
    {
        "sequence": 2,
        "name": "Net and Movement",
        "description": "Front court play, lunging, split step, and net shot technique.",
        "skills": [
            {
                "sequence": 1,
                "name": "Lunge",
                "description": "Perform a controlled lunge to reach a low shuttle.",
                "criteria": [
                    "Lead foot points toward shuttle",
                    "First contact is heel",
                    "Upright posture maintained",
                    "Safe recovery after lunge",
                ],
            },
            {
                "sequence": 2,
                "name": "Split step",
                "description": "Use a split step to react quickly to incoming shuttle.",
                "criteria": [
                    "Small hop before opponent contact",
                    "Lands in ready position",
                    "Feet approximately shoulder-width apart",
                ],
            },
            {
                "sequence": 3,
                "name": "Forecourt movement",
                "description": "Move to the frontcourt and recover correctly.",
                "criteria": [
                    "Uses chasse steps to reach net",
                    "Returns to base after each shot",
                    "Maintains low centre of gravity",
                ],
            },
            {
                "sequence": 4,
                "name": "Backhand net shot",
                "description": "Push shuttle gently over the net using backhand.",
                "criteria": [
                    "Thumb grip used",
                    "Racket held out in front of body",
                    "6 of 10 attempts land in the forecourt on the other side",
                ],
            },
            {
                "sequence": 5,
                "name": "Forehand net shot",
                "description": "Push shuttle gently over the net using forehand.",
                "criteria": [
                    "V grip used",
                    "Elbow away from body",
                    "6 of 10 attempts land in the forecourt on the other side",
                ],
            },
            {
                "sequence": 6,
                "name": "Net rally",
                "description": "Sustain a cooperative net rally with a partner.",
                "criteria": [
                    "8-shot net rally completed",
                    "Shuttle stays at tape height or below on each shot",
                    "Appropriate grip used throughout",
                ],
            },
        ],
        "ext_ref": {
            "module_name": "Starter Lessons",
            "lesson_range": "3-6",
            "reference_title": "Net play and starting movement",
            "page_hint": "p.16-30",
        },
    },
    {
        "sequence": 3,
        "name": "Serve and Lift",
        "description": "Starting a rally legally — backhand serve, high serve, and frontcourt lifts.",
        "skills": [
            {
                "sequence": 1,
                "name": "Backhand serve",
                "description": "Serve legally using a backhand push below waist height.",
                "criteria": [
                    "Shuttle hit from hand",
                    "Contact below waist",
                    "7 of 10 serves land in the correct service box",
                ],
            },
            {
                "sequence": 2,
                "name": "Forehand high serve",
                "description": "Serve high and deep using a forehand underarm swing.",
                "criteria": [
                    "Full underarm swing",
                    "Weight transfers from back to front foot",
                    "6 of 10 serves land in the rearcourt area",
                ],
            },
            {
                "sequence": 3,
                "name": "Backhand lift",
                "description": "Hit a backhand lift from the frontcourt to the rearcourt.",
                "criteria": [
                    "Starts from a net position",
                    "Shuttle travels high to the rearcourt",
                    "6 of 10 lifts clear the net and reach back service line",
                ],
            },
            {
                "sequence": 4,
                "name": "Forehand lift",
                "description": "Hit a forehand lift from the frontcourt to the rearcourt.",
                "criteria": [
                    "V grip used",
                    "Forearm rotates on contact",
                    "6 of 10 lifts clear the net and reach back service line",
                ],
            },
            {
                "sequence": 5,
                "name": "Serve and rally start",
                "description": "Start a rally legally from a serve and continue it.",
                "criteria": [
                    "Serve is legal (contact below waist)",
                    "Rally continues for at least 4 shots after serve",
                    "Player recovers to ready position after serve",
                ],
            },
        ],
        "ext_ref": {
            "module_name": "Starter Lessons",
            "lesson_range": "7-10",
            "reference_title": "Serve, lift, and frontcourt rally",
            "page_hint": "p.31-45",
        },
    },
    {
        "sequence": 4,
        "name": "Midcourt Speed",
        "description": "Faster flat rallying, forehand and backhand drives, and block defense.",
        "skills": [
            {
                "sequence": 1,
                "name": "Forehand drive",
                "description": "Hit a flat forehand drive at tape height.",
                "criteria": [
                    "V grip used",
                    "Short racket movement",
                    "10-shot forehand drive cooperative rally completed",
                ],
            },
            {
                "sequence": 2,
                "name": "Backhand drive",
                "description": "Hit a flat backhand drive at tape height.",
                "criteria": [
                    "Thumb grip used",
                    "Elbow in front of body on contact",
                    "10-shot backhand drive cooperative rally completed",
                ],
            },
            {
                "sequence": 3,
                "name": "Flat rally",
                "description": "Sustain a controlled flat rally from midcourt.",
                "criteria": [
                    "Shuttle stays at tape height throughout",
                    "Both forehand and backhand drives used",
                    "Controlled rally of 15 shots",
                ],
            },
            {
                "sequence": 4,
                "name": "Racket speed",
                "description": "Show fast racket preparation and short swing.",
                "criteria": [
                    "Racket held in front of body between shots",
                    "Grip tightens only at contact",
                    "No large back-swing on drives",
                ],
            },
            {
                "sequence": 5,
                "name": "Block defense",
                "description": "Return an attacking shot using a block.",
                "criteria": [
                    "Racket in ready position before the shot arrives",
                    "Short pushing action used",
                    "6 of 10 blocks land in the forecourt",
                ],
            },
        ],
        "ext_ref": {
            "module_name": "Swing and Throw",
            "lesson_range": "11-12",
            "reference_title": "Midcourt drives and development",
            "page_hint": "p.49-55",
        },
    },
    {
        "sequence": 5,
        "name": "Rearcourt Shots",
        "description": "Overhead technique — clear, drop, smash, and the scissor jump.",
        "skills": [
            {
                "sequence": 1,
                "name": "Forehand clear",
                "description": "Hit a high forehand overhead clear to the rearcourt.",
                "criteria": [
                    "Side-on preparation",
                    "Arms and elbows at shoulder height on backswing",
                    "7 of 10 clears reach the baseline area",
                ],
            },
            {
                "sequence": 2,
                "name": "Forehand drop",
                "description": "Hit a forehand overhead drop shot to the frontcourt.",
                "criteria": [
                    "Same preparation as clear",
                    "Deceleration used on contact instead of full swing",
                    "6 of 10 drops land between the net and short service line",
                ],
            },
            {
                "sequence": 3,
                "name": "Forehand smash",
                "description": "Execute a controlled forehand smash.",
                "criteria": [
                    "Interception point is in front of the body",
                    "Shuttle directed downward",
                    "Contact made safely at full arm extension",
                ],
            },
            {
                "sequence": 4,
                "name": "Smash block",
                "description": "Block a smash back into the forecourt.",
                "criteria": [
                    "Racket held in front of body",
                    "Short push action used",
                    "6 of 10 smash blocks controlled back over the net",
                ],
            },
            {
                "sequence": 5,
                "name": "Scissor jump",
                "description": "Show the correct scissor jump footwork for rearcourt shots.",
                "criteria": [
                    "Side-on position before jump",
                    "Lands on non-racket foot",
                    "Forward movement after landing",
                ],
            },
        ],
        "ext_ref": {
            "module_name": "Throw and Hit",
            "lesson_range": "13-18",
            "reference_title": "Overhead shots and smash",
            "page_hint": "p.59-82",
        },
    },
    {
        "sequence": 6,
        "name": "Match and Tactics",
        "description": "Singles and doubles scoring, space use, positioning, and independent match play.",
        "skills": [
            {
                "sequence": 1,
                "name": "Singles scoring",
                "description": "Score a singles game correctly.",
                "criteria": [
                    "Calls score correctly throughout a game",
                    "Serves from correct court based on score",
                    "Understands deuce and setting",
                ],
            },
            {
                "sequence": 2,
                "name": "Intentional space use",
                "description": "Hit purposefully into open court space.",
                "criteria": [
                    "Changes shot direction deliberately",
                    "Can explain why a shot was chosen",
                    "Coach observes intentional placement in at least 3 rallies",
                ],
            },
            {
                "sequence": 3,
                "name": "Doubles serve setup",
                "description": "Set up correctly for doubles serve and return.",
                "criteria": [
                    "Serves from correct court",
                    "Partner positions correctly",
                    "Understands side-by-side and front-back formations",
                ],
            },
            {
                "sequence": 4,
                "name": "Doubles positioning",
                "description": "Show basic attacking and defensive doubles formations.",
                "criteria": [
                    "Moves to net after partner's attack",
                    "Drops to defensive side position when opponent attacks",
                    "Communicates with partner during play",
                ],
            },
            {
                "sequence": 5,
                "name": "Attack-neutral-defense awareness",
                "description": "Recognize and respond to attacking, neutral, and defensive situations.",
                "criteria": [
                    "Identifies situation correctly when prompted",
                    "Adjusts shot selection based on shuttle height",
                    "Coach observes appropriate shot choices in 3+ rallies",
                ],
            },
            {
                "sequence": 6,
                "name": "Full match play",
                "description": "Play a full singles or doubles game independently.",
                "criteria": [
                    "Applies scoring rules without prompting",
                    "Serves and receives correctly",
                    "Plays respectfully for a full game to 21 points",
                ],
            },
        ],
        "ext_ref": {
            "module_name": "Learn to Win",
            "lesson_range": "19-22",
            "reference_title": "Singles and doubles tactics",
            "page_hint": "p.86-102",
        },
    },
]


async def seed_badminton_pathway(
    *,
    academy_id: str,
    programs: ProgramRepository,
    levels: LevelRepository,
    skills: SkillRepository,
    criteria: CriterionRepository,
    refs: ExternalRefRepository,
    created_by: str = "system",
) -> Program:
    """Idempotent: creates the Badminton Skill Pathway if it does not exist.

    Checks for an existing active badminton program with the same sport.
    If one already exists, returns it without creating duplicates.
    """
    existing = await programs.list_active()
    for prog in existing:
        if prog.sport == "badminton":
            return prog

    now = datetime.now(UTC)
    program = Program(
        program_id=str(new_ulid()),
        academy_id=academy_id,
        sport="badminton",
        name="Badminton Skill Pathway",
        description=(
            "Academy skill-based progression for badminton. "
            "Students advance by demonstrating mastered skills, not by time or attendance."
        ),
        is_active=True,
        created_at=now,
        updated_at=now,
        created_by=created_by,
    )
    await programs.save(program)

    for level_data in _LEVELS:
        level = Level(
            level_id=str(new_ulid()),
            program_id=program.program_id,
            academy_id=academy_id,
            sequence=level_data["sequence"],
            name=level_data["name"],
            description=level_data["description"],
            completion_rule="ALL_REQUIRED_SKILLS",
            requires_coach_recommendation=True,
            requires_admin_approval=False,
            is_active=True,
            created_at=now,
            updated_at=now,
            created_by=created_by,
        )
        await levels.save(level)

        # Seed skills for this level
        first_skill_id: str | None = None
        for skill_data in level_data["skills"]:
            skill = Skill(
                skill_id=str(new_ulid()),
                level_id=level.level_id,
                program_id=program.program_id,
                academy_id=academy_id,
                sequence=skill_data["sequence"],
                name=skill_data["name"],
                description=skill_data["description"],
                is_required=True,
                scoring_type="ATTEMPT_BASED",
                pass_threshold_pct=70.0,
                coach_override_allowed=False,
                is_active=True,
                created_at=now,
                updated_at=now,
                created_by=created_by,
            )
            await skills.save(skill)
            if first_skill_id is None:
                first_skill_id = skill.skill_id

            # Seed criteria for this skill
            for i, criterion_desc in enumerate(skill_data["criteria"]):
                criterion = SkillCriterion(
                    criterion_id=str(new_ulid()),
                    skill_id=skill.skill_id,
                    level_id=level.level_id,
                    program_id=program.program_id,
                    academy_id=academy_id,
                    description=criterion_desc,
                    display_order=i,
                    created_at=now,
                    created_by=created_by,
                )
                await criteria.save(criterion)

        # Seed the external reference for this level (reference metadata ONLY —
        # never lesson body text). It is anchored to the level's first skill.
        ext = level_data["ext_ref"]
        if first_skill_id is not None:
            ref = ExternalLessonReference(
                ref_id=str(new_ulid()),
                skill_id=first_skill_id,
                academy_id=academy_id,
                source="BWF_SHUTTLE_TIME",
                source_title="BWF Shuttle Time",
                module_name=ext["module_name"],
                lesson_range=ext["lesson_range"],
                reference_title=ext["reference_title"],
                page_hint=ext.get("page_hint"),
                internal_note="External structural reference only. Do not reproduce content.",
                created_at=now,
                created_by=created_by,
            )
            await refs.save(ref)

    return program
