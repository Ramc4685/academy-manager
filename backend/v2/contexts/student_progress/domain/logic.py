"""Student progress domain logic — pure functions, no I/O."""

from __future__ import annotations


def calculate_skill_pass(
    attempts: int,
    successes: int,
    threshold_pct: float,
) -> bool:
    """Return True if successes/attempts meets the pass threshold.

    Args:
        attempts: Total number of attempts recorded.
        successes: Number of successful attempts.
        threshold_pct: Pass threshold as a percentage (0-100).

    Returns:
        True if the skill is considered passed, False otherwise.
    """
    if attempts <= 0:
        return False
    return (successes / attempts) * 100.0 >= threshold_pct


def check_level_completion(
    required_skill_ids: list[str],
    passed_skill_ids: set[str],
) -> bool:
    """Return True if all required skills have been passed.

    Args:
        required_skill_ids: IDs of skills that are marked is_required=True.
        passed_skill_ids: IDs of skills whose status is PASSED.

    Returns:
        True if all required skills appear in the passed set.
    """
    if not required_skill_ids:
        return True
    return all(skill_id in passed_skill_ids for skill_id in required_skill_ids)


def generate_cert_number(
    academy_id: str,
    student_id: str,
    level_sequence: int,
    timestamp_ms: int,
) -> str:
    """Generate a unique, human-readable certificate number.

    Format: {ACADEMY_PREFIX}-L{SEQ}-{STUDENT_SUFFIX}-{TIMESTAMP}
    Example: ACM-L3-A1B2-1717613400000
    """
    academy_prefix = (academy_id[:3]).upper()
    student_suffix = (student_id[-4:]).upper()
    return f"{academy_prefix}-L{level_sequence}-{student_suffix}-{timestamp_ms}"
