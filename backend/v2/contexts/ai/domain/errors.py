"""AI domain errors."""

from __future__ import annotations

from backend.v2.shared.http.errors import DomainError


class AiDisabled(DomainError):
    """``V2_AI_ENABLED`` is off or no ``V2_ANTHROPIC_API_KEY`` is set; the
    disabled port answers every call with this."""

    code = "Ai.Disabled"
    status_code = 503


class AiMonthlyCapReached(DomainError):
    """Recording this call would take the academy past its monthly AI call
    cap (``ai.monthly_call_cap`` on the academy document)."""

    code = "Ai.MonthlyCapReached"
    status_code = 429


class AiDailyCapReached(DomainError):
    """This feature already made its daily number of calls for the academy
    (``ai.daily_call_cap.<feature>`` on the academy document)."""

    code = "Ai.DailyCapReached"
    status_code = 429


class AiProviderError(DomainError):
    """The model provider answered with an error or could not be reached."""

    code = "Ai.ProviderError"
    status_code = 502


class AiAcademyNotFound(DomainError):
    """Platform admin asked for the AI usage of an unknown academy."""

    code = "Ai.AcademyNotFound"
    status_code = 404


class AiNotEntitled(DomainError):
    """The academy's platform plan does not include the ``ai`` feature."""

    code = "Ai.NotEntitled"
    status_code = 403


class AiImportSampleRejected(DomainError):
    """The spreadsheet handed to the roster-import copilot is over the import's
    own size or row cap, or is not readable as CSV."""

    code = "Ai.ImportSampleRejected"
    status_code = 422
