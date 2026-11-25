"""Class recap: the shared record of what one dated class occurrence taught.

One recap per occurrence.

* ``taught_skill_ids`` is the class-level record. It stands on its own: a
  class can have taught a skill with nobody yet known to have practised it,
  and teaching the group never credits any one child.
* ``practice`` holds practised skills PER CHILD (Maya only practised X, Leo
  only Y). Every practised skill is also taught, and every credited child must
  be marked present (or late) for that occurrence.
* A recap never passes a skill. Passes belong to the existing pass pipeline
  (tap-to-master / test attempts); a report's pass claim is a follow-up only.

The rest of this module is the deterministic gate for after-class reports:

* :func:`alias_report` redacts contact details and replaces roster names with
  local aliases (``S1``, ``K1``), so the model never sees names, stable ids
  or the full roster, and refuses ambiguous duplicate first names up front;
* :func:`resolve_report` checks every claim against the report text itself
  (quoted evidence, grounded skill names, explicit group wording, present
  marks), and only ever ADDS to the existing recap. A claim that contradicts
  recorded practice becomes a question, never a silent removal.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Attendance marks that confirm a child was in the class.
CONFIRMED_PRESENT = frozenset({"present", "late"})

RecapSource = Literal["direct", "report"]
ReportOutcome = Literal["applied", "needs_clarification", "sent_to_owner"]

MAX_TAUGHT_SKILLS = 30
MAX_PARTICIPANTS = 100
MAX_PASSES = 200


class ChildPractice(BaseModel):
    model_config = {"frozen": True}

    student_id: str = Field(min_length=1)
    skill_ids: tuple[str, ...] = Field(min_length=1, max_length=MAX_TAUGHT_SKILLS)


class ChildPass(BaseModel):
    """The coach saw this child meet this skill's criterion in this class.
    Applied through the pass pipeline once per class, child and skill; a
    later revision never removes it (a formal reassessment does)."""

    model_config = {"frozen": True}

    student_id: str
    skill_id: str
    #: The recap revision that first recorded it (corrections keep it).
    added_revision: int = Field(ge=1)


class ClassRecap(BaseModel):
    model_config = {"frozen": True}

    recap_id: str
    academy_id: str
    occurrence_id: str
    session_id: str
    class_starts_at: datetime
    taught_skill_ids: tuple[str, ...] = ()
    practice: tuple[ChildPractice, ...] = ()
    passes: tuple[ChildPass, ...] = ()
    revision: int = Field(default=0, ge=0)
    last_mutation_id: str | None = None
    source: RecapSource = "direct"
    source_report_id: str | None = None
    updated_by: str
    updated_at: datetime

    def practiced_by(self, student_id: str) -> tuple[str, ...]:
        for row in self.practice:
            if row.student_id == student_id:
                return row.skill_ids
        return ()


class PassClaim(BaseModel):
    """A child passed a skill. From a report it is only a follow-up for the
    coach; on direct recap entry it is saved and run through the pass pipeline."""

    model_config = {"frozen": True}

    student_id: str
    skill_id: str


class ClassReport(BaseModel):
    """A coach's private after-class report. Visible to its author and the
    academy owner only; never shown to parents."""

    model_config = {"frozen": True}

    report_id: str
    academy_id: str
    occurrence_id: str
    class_starts_at: datetime
    author_id: str
    text: str
    submitted_at: datetime
    outcome: ReportOutcome
    #: The coach asked for AI and the academy's AI was available for it.
    ai_used: bool = False
    questions: tuple[str, ...] = ()
    pass_claims: tuple[PassClaim, ...] = ()
    applied_revision: int | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    #: Set while the submit that stored the report is still reading it; the
    #: stored outcome stays ``sent_to_owner`` until that submit finishes, so an
    #: interrupted read is already the owner's to handle.
    processing_until: datetime | None = None


# --- local aliasing (nothing personal leaves the app) -----------------------

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")


class RosterName(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    full_name: str


class AliasedSkill(BaseModel):
    model_config = {"frozen": True}

    alias: str
    skill_id: str
    name: str


class AliasedReport(BaseModel):
    """The report as the model may see it, and the local key back to ids."""

    model_config = {"frozen": True}

    text: str
    student_aliases: dict[str, str]  # alias -> student_id
    skills: tuple[AliasedSkill, ...]
    questions: tuple[str, ...] = ()


def first_name(full_name: str) -> str:
    """Empty for a nameless row: never a stand-in word like "Student" that
    ordinary report text would then match."""
    parts = full_name.split()
    return parts[0] if parts else ""


def _word(name: str) -> re.Pattern[str]:
    # Hyphens join names: "Mary" must not match inside "Mary-Jane".
    return re.compile(rf"(?<![\w-]){re.escape(name)}(?![\w-])", re.IGNORECASE)


_RAW_ALIAS = re.compile(r"(?<!\w)[SK]\d+(?!\w)", re.IGNORECASE)


def alias_report(
    text: str, roster: list[RosterName], skills: list[tuple[str, str]]
) -> AliasedReport:
    """Redact contact details and swap roster names for ``S<n>`` aliases.

    Full names are replaced first (longest first), so "Maya Lopez"
    disambiguates two Mayas; a first or full name still shared by two roster
    children is a question and the report is not sent anywhere. Codes the
    coach typed that look like aliases (``S1``) are refused: they would let
    the text name a child it never named. ``skills`` is ``(skill_id, name)``.
    """
    out = _PHONE.sub("[number]", _EMAIL.sub("[email]", text))
    questions: list[str] = []
    if _RAW_ALIAS.search(out):
        questions.append("Write students' and skills' names, not codes like S1.")
    aliases: dict[str, str] = {}
    ordered = sorted(roster, key=lambda r: (r.full_name.lower(), r.student_id))
    by_alias = {f"S{i}": row for i, row in enumerate(ordered, start=1)}
    fulls: dict[str, list[str]] = {}
    for alias, row in by_alias.items():
        aliases[alias] = row.student_id
        full = " ".join(row.full_name.split())
        if len(full.split()) > 1:
            fulls.setdefault(full.lower(), []).append(alias)
    for full, owners in sorted(fulls.items(), key=lambda kv: -len(kv[0])):
        pattern = _word(full)
        if len(owners) == 1:
            out = pattern.sub(owners[0], out)
        elif pattern.search(out):
            questions.append(
                f"More than one student is named {full.title()}. "
                "Record them on the recap form instead."
            )
            out = pattern.sub("[student]", out)
    firsts: dict[str, list[str]] = {}
    for alias, row in by_alias.items():
        name = first_name(row.full_name).lower()
        if name:
            firsts.setdefault(name, []).append(alias)
    for name, owners in firsts.items():
        pattern = _word(name)
        hits = [m.group(0) for m in pattern.finditer(out)]
        if not hits:
            continue
        if any(hit[0].islower() for hit in hits):
            # "will" may be Will or the word: ask rather than guess either way.
            questions.append(
                f'Is "{next(h for h in hits if h[0].islower())}" {name.title()} or an '
                "ordinary word? Write students' names with a capital letter, or reword it."
            )
        elif len(owners) > 1:
            questions.append(f"More than one student is named {name.title()}. Use their full name.")
        else:
            out = pattern.sub(owners[0], out)
    aliased_skills = tuple(
        AliasedSkill(alias=f"K{i}", skill_id=sid, name=name)
        for i, (sid, name) in enumerate(skills, start=1)
    )
    return AliasedReport(
        text=out, student_aliases=aliases, skills=aliased_skills, questions=tuple(questions)
    )


# --- what the reader proposes (in aliases) ----------------------------------


class TaughtClaim(BaseModel):
    model_config = {"frozen": True}

    skills: tuple[str, ...]
    evidence: str


class PracticeClaim(BaseModel):
    model_config = {"frozen": True}

    who: Literal["group", "listed"]
    students: tuple[str, ...] = ()
    except_students: tuple[str, ...] = ()
    skills: tuple[str, ...]
    evidence: str


class PassStatement(BaseModel):
    model_config = {"frozen": True}

    student: str
    skill: str
    evidence: str


class ReportFacts(BaseModel):
    """An interpreter's reading of an aliased report: aliases only, each claim
    with the report words it rests on. Nothing here is trusted yet."""

    model_config = {"frozen": True}

    taught: tuple[TaughtClaim, ...] = ()
    practice: tuple[PracticeClaim, ...] = ()
    passes: tuple[PassStatement, ...] = ()
    questions: tuple[str, ...] = ()


class ResolvedReport(BaseModel):
    model_config = {"frozen": True}

    taught_skill_ids: tuple[str, ...] = ()
    practice: tuple[ChildPractice, ...] = ()
    pass_claims: tuple[PassClaim, ...] = ()
    questions: tuple[str, ...] = ()


_GROUP = re.compile(
    r"\b(everyone|everybody|all of (them|us|the (kids|students|players|children|class))"
    r"|(the )?whole (class|group)|all (the )?(kids|students|players|children)"
    r"|the (class|group) all|all \d+ of them)\b",
    re.IGNORECASE,
)
_PASS = re.compile(r"\b(pass(ed|es)?|master(ed|s)?|got it|nailed it|can now)\b", re.IGNORECASE)
# Words that say the children actually did it, not just watched or heard it.
_PRACTICE = re.compile(
    r"\b(practi[cs]\w*|drill\w*|work(ed|ing)? on|did|do(ing)?|join\w*|tried|rall(y|ied|ies)"
    r"|play\w*|hit\w*|ran|went through|took turns)\b",
    re.IGNORECASE,
)
# Negation or sitting out: a claim resting on such words is never applied.
_NEGATIVE = re.compile(
    r"\b(not|no|never|none|nobody|without|sat out|sit(s|ting)? out|missed|absent|injured"
    r"|hurt|skipped|rested|watched|left early|next (week|time|class))\b|n't\b",
    re.IGNORECASE,
)
_EXCLUSION = re.compile(
    r"\b(except|but|apart from|other than|besides|excluding|aside from)\b", re.IGNORECASE
)
_SENTENCE = re.compile(r"[.!?;\n]+")
_STOP = frozenset({"the", "and", "with", "for", "from", "into", "drill", "level", "shot"})
# Coaches' everyday words for a curriculum skill, canonicalised before grounding.
_SKILL_SYNONYMS = ((re.compile(r"\bscissors? kicks?\b"), "scissor jump"),)


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _words(name: str) -> list[str]:
    return [t[:5] for t in re.findall(r"[a-z]+", name.lower())]


def _stems(name: str) -> list[str]:
    return [t[:5] for t in re.findall(r"[a-z]+", name.lower()) if len(t) >= 3 and t not in _STOP]


def _phrase(name: str, ev: str) -> bool:
    words = _words(name)
    pattern = r"\b" + r"\w*[\s-]+".join(map(re.escape, words))
    return bool(words) and re.search(pattern, ev) is not None


def _grounded_skill(name: str, evidence: str, catalog: list[str]) -> bool:
    """A skill counts as named when the quote holds its whole name as a
    phrase ("forehand clears"), or a word that no other catalog skill shares
    ("smashes" grounds "Jump smash" unless "Smash defence" also exists).
    Words match from their start, so "low" is not in "follow" nor "serve" in
    "observed"."""
    ev = _norm(evidence)
    for pattern, canonical in _SKILL_SYNONYMS:
        if pattern.search(ev):
            if _norm(name) == canonical:
                return True
            ev = pattern.sub(" ", ev)  # "kick" there must not ground "Kick serve"
    if _phrase(name, ev):
        # "smash" inside "jump smash" names Jump smash, not a plain Smash skill.
        mine = set(_words(name))
        return not any(mine < set(_words(o)) and _phrase(o, ev) for o in catalog)
    others = {s for other in catalog if _norm(other) != _norm(name) for s in _stems(other)}
    return any(re.search(rf"\b{re.escape(s)}", ev) for s in _stems(name) if s not in others)


def _sentence_of(text: str, fragment: str) -> str:
    """The sentence(s) of ``text`` around ``fragment`` (both normalised), so a
    quote cannot drop the "not" just before it."""
    start = text.find(fragment)
    if start < 0:
        return fragment
    end = start + len(fragment)
    left = max((m.end() for m in _SENTENCE.finditer(text, 0, start)), default=0)
    right = _SENTENCE.search(text, end)
    return text[left : right.start() if right else len(text)]


def _aliases_near(text: str, *cues: re.Pattern[str]) -> set[str]:
    """Aliases in any sentence matching one of ``cues``."""
    found: set[str] = set()
    for sentence in _SENTENCE.split(text):
        if any(cue.search(sentence) for cue in cues):
            found.update(re.findall(r"(?<!\w)S\d+(?!\w)", sentence))
    return found


def _mentions(alias: str, evidence: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", evidence) is not None


def resolve_report(
    facts: ReportFacts,
    *,
    aliased: AliasedReport,
    attendance: dict[str, str],
    first_names: dict[str, str],
    existing: ClassRecap | None,
) -> ResolvedReport:
    """Turn aliased claims into ids that may be ADDED to the recap.

    Every claim must quote the report; skills must be named in the quote;
    named children must be in the quote; "group" needs explicit group words;
    only confirmed present children are credited. A claim whose sentence
    negates ("did not", "sat out") is never applied, and practice needs words
    that say the children did it, so a taught-only report never becomes
    practice. A child in any sentence that excludes, negates or sits someone
    out is never credited by a group claim, even when the reading forgot to
    list them. A child the report excludes from a skill they already have
    recorded, or both credits and excludes, is a question. Any question means
    nothing is applied.
    """
    text = _norm(aliased.text)
    skills = {s.alias: s for s in aliased.skills}
    catalog = [s.name for s in aliased.skills]
    students = aliased.student_aliases
    present = [sid for sid, mark in attendance.items() if mark in CONFIRMED_PRESENT]
    held_back = _aliases_near(aliased.text, _NEGATIVE, _EXCLUSION)
    sat_out = _aliases_near(aliased.text, _NEGATIVE)

    def name_of(sid: str) -> str:
        return first_names.get(sid) or "A student"

    def unalias(question: str) -> str:
        return re.sub(
            r"(?<!\w)S\d+(?!\w)",
            lambda m: name_of(students[m.group(0)]) if m.group(0) in students else "a student",
            question.strip()[:200],
        )

    questions = list(aliased.questions) + [unalias(q) for q in facts.questions if q.strip()]

    def quoted(evidence: str) -> bool:
        ev = _norm(evidence)
        return len(ev) >= 3 and ev in text

    def ground_skills(claim_skills: tuple[str, ...], evidence: str) -> list[str]:
        ids: list[str] = []
        for alias in claim_skills:
            skill = skills.get(alias)
            if skill is None or not _grounded_skill(skill.name, evidence, catalog):
                label = skill.name if skill is not None else "a skill"
                questions.append(f"I could not find {label} in the report. Which skill was it?")
            else:
                ids.append(skill.skill_id)
        return ids

    def negated(evidence: str) -> bool:
        if _NEGATIVE.search(_sentence_of(text, _norm(evidence))):
            questions.append(
                "Part of the report says something did not happen. "
                "Record that class on the recap form instead."
            )
            return True
        return False

    taught: list[str] = []
    for taught_claim in facts.taught:
        if not quoted(taught_claim.evidence):
            questions.append("Part of the reading did not match the report. Please rephrase.")
            continue
        if negated(taught_claim.evidence):
            continue
        taught.extend(ground_skills(taught_claim.skills, taught_claim.evidence))

    added: dict[str, list[str]] = {}
    left_out: set[tuple[str, str]] = set()
    for claim in facts.practice:
        if not quoted(claim.evidence):
            questions.append("Part of the reading did not match the report. Please rephrase.")
            continue
        if negated(claim.evidence):
            continue
        if not _PRACTICE.search(_sentence_of(text, _norm(claim.evidence))):
            questions.append("Did the students practise it, or was it only taught? Say who did.")
            continue
        claim_skills = ground_skills(claim.skills, claim.evidence)
        excluded = set()
        for alias in claim.except_students:
            if alias in students and (_mentions(alias, claim.evidence) or alias in held_back):
                excluded.add(students[alias])
            else:
                questions.append("Who sat out? Name them in the report.")
        if claim.who == "group":
            excluded |= {students[a] for a in held_back if a in students}
            if not _GROUP.search(claim.evidence):
                questions.append("Who took part? Say everyone, or name the students.")
                continue
            if not present:
                questions.append(
                    "No one is marked present for this class yet. "
                    "Mark attendance, then submit again."
                )
                continue
            credited = [sid for sid in present if sid not in excluded]
        else:
            credited = []
            for alias in claim.students:
                sid = students.get(alias)
                if sid is None or not _mentions(alias, claim.evidence):
                    questions.append("The report named someone I could not match. Who was it?")
                elif attendance.get(sid) not in CONFIRMED_PRESENT:
                    questions.append(
                        f"{name_of(sid)} is not marked present. "
                        "Correct attendance or the report first."
                    )
                elif alias in sat_out:
                    questions.append(
                        f"The report also says {name_of(sid)} sat out or did not do something. "
                        "Which skills did they practise?"
                    )
                elif sid not in excluded:
                    credited.append(sid)
        left_out.update((sid, skill_id) for sid in excluded for skill_id in claim_skills)
        for sid in excluded:
            already = set(existing.practiced_by(sid)) if existing is not None else set()
            for skill_id in claim_skills:
                if skill_id in already:
                    questions.append(
                        f"{name_of(sid)} is already recorded as practising "
                        f"{aliased_name(aliased, skill_id)}. "
                        "Correct the recap form if that was wrong."
                    )
        for sid in credited:
            added.setdefault(sid, []).extend(claim_skills)
        taught.extend(claim_skills)

    passes: list[PassClaim] = []
    for statement in facts.passes:
        sid = students.get(statement.student)
        skill = skills.get(statement.skill)
        if (
            sid is not None
            and skill is not None
            and quoted(statement.evidence)
            and _mentions(statement.student, statement.evidence)
            and _PASS.search(statement.evidence)
            and not _NEGATIVE.search(_sentence_of(text, _norm(statement.evidence)))
            and _grounded_skill(skill.name, statement.evidence, catalog)
        ):
            passes.append(PassClaim(student_id=sid, skill_id=skill.skill_id))

    for sid, ids in added.items():
        for skill_id in ids:
            if (sid, skill_id) in left_out:
                questions.append(
                    f"The report both includes and leaves out {name_of(sid)} for "
                    f"{aliased_name(aliased, skill_id)}. Which is right?"
                )
    if not questions and not taught:
        questions.append("Which skills did the class work on?")
    if questions:
        return ResolvedReport(questions=tuple(dict.fromkeys(questions)), pass_claims=())
    practice = tuple(
        ChildPractice(student_id=sid, skill_ids=tuple(dict.fromkeys(ids)))
        for sid, ids in added.items()
        if ids
    )
    return ResolvedReport(
        taught_skill_ids=tuple(dict.fromkeys(taught)),
        practice=practice,
        pass_claims=tuple(dict.fromkeys(passes)),
    )


def aliased_name(aliased: AliasedReport, skill_id: str) -> str:
    return next((s.name for s in aliased.skills if s.skill_id == skill_id), "that skill")


def merge_practice(
    base: tuple[ChildPractice, ...], additions: tuple[ChildPractice, ...]
) -> tuple[ChildPractice, ...]:
    """Union per child; nothing recorded is ever dropped."""
    merged: dict[str, list[str]] = {row.student_id: list(row.skill_ids) for row in base}
    for row in additions:
        current = merged.setdefault(row.student_id, [])
        current.extend(sid for sid in row.skill_ids if sid not in current)
    return tuple(
        ChildPractice(student_id=sid, skill_ids=tuple(ids)) for sid, ids in merged.items() if ids
    )
