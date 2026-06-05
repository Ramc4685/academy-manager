"""Student progress use cases."""

from __future__ import annotations

from backend.v2.contexts.student_progress.application.use_cases.get_certificates import (
    GetStudentCertificates,
    GetStudentCertificatesCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.get_level_up_queue import (
    GetLevelUpQueue,
    GetLevelUpQueueCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.get_passport import (
    GetStudentPassport,
    GetStudentPassportCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.get_student_progress import (
    GetStudentProgress,
)
from backend.v2.contexts.student_progress.application.use_cases.place_student import (
    PlaceStudentInLevel,
    PlaceStudentInLevelCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.recommend_level_up import (
    RecommendLevelUp,
    RecommendLevelUpCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.record_test_attempt import (
    RecordTestAttempt,
    RecordTestAttemptCommand,
    RecordTestAttemptResult,
)
from backend.v2.contexts.student_progress.application.use_cases.review_level_up import (
    ReviewLevelUpCommand,
    ReviewLevelUpRecommendation,
    ReviewLevelUpResult,
)
from backend.v2.contexts.student_progress.application.use_cases.update_skill_status import (
    UpdateSkillStatus,
    UpdateSkillStatusCommand,
)

__all__ = [
    "GetLevelUpQueue",
    "GetLevelUpQueueCommand",
    "GetStudentCertificates",
    "GetStudentCertificatesCommand",
    "GetStudentPassport",
    "GetStudentPassportCommand",
    "GetStudentProgress",
    "PlaceStudentInLevel",
    "PlaceStudentInLevelCommand",
    "RecordTestAttempt",
    "RecordTestAttemptCommand",
    "RecordTestAttemptResult",
    "RecommendLevelUp",
    "RecommendLevelUpCommand",
    "ReviewLevelUpCommand",
    "ReviewLevelUpRecommendation",
    "ReviewLevelUpResult",
    "UpdateSkillStatus",
    "UpdateSkillStatusCommand",
]
