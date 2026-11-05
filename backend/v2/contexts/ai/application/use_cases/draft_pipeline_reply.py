"""B3: draft a reply to a pipeline lead (AI strategy Phase 2, Track B, paid).

The one place the model sees a lead: an explicit ``extra=forbid`` input built
from the facts this slice allows and nothing else (no parent name, email,
phone, address, notes or other families; the composition adapter decides what
``InquiryFacts`` carries, and ``test_ai_pipeline_reply`` pins the absence of
the rest). Order: entitlement (403) -> cap (429) -> complete -> record the
spent call BEFORE parsing -> strict parse (502). The draft is returned to the
staff member and written nowhere; the send route is the human approval.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.v2.contexts.ai.application.ports import AiEntitlement, LlmPort
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.domain.errors import AiNotEntitled, AiProviderError
from backend.v2.contexts.ai.domain.prompts import PROMPTS
from backend.v2.shared.http.errors import DomainError

FEATURE = "pipeline_reply"
MAX_TOKENS = 800
MAX_INQUIRY_CHARS = 2000
MAX_CLASS_LINES = 6

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
#: Any link-looking token, case-insensitive: a scheme, www., mailto:, or a
#: bare domain (two or more letters after a dot, so "e.g." does not match).
_URL = re.compile(
    r"(?i)(?:[a-z][a-z0-9+.-]*:)?//\S+|www\.\S+|mailto:\S+|\b[\w-]+(?:\.[a-z]{2,})+(?:/\S*)?"
)


class InquiryNotFound(DomainError):
    """No lead with this id in the caller's academy."""

    code = "Ai.InquiryNotFound"
    status_code = 404


@dataclass(frozen=True)
class InquiryFacts:
    """What the lead store hands the draft: the lead's own text and the
    child's age and interest as stored. No name, email or phone, by type."""

    inquiry_message: str | None
    child_ages: tuple[str, ...]
    interest: str | None


@dataclass(frozen=True)
class ReplyContext:
    academy_name: str
    public_page_url: str | None
    trial_offer: str | None
    #: Up to MAX_CLASS_LINES lines: name, schedule summary, price line.
    class_context: tuple[str, ...]


class InquirySource(Protocol):
    async def inquiry_facts(self, contact_id: str) -> InquiryFacts | None: ...


class ReplyContextSource(Protocol):
    async def reply_context(self) -> ReplyContext: ...


class StaffNames(Protocol):
    async def first_name(self, user_id: str) -> str | None: ...


class PipelineReplyInput(BaseModel):
    """Exactly what the model sees. ``extra="forbid"`` so a new field on the
    contact can never ride along by accident."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    academy_name: str
    staff_first_name: str
    #: The lead's own words from the website form: untrusted data.
    inquiry_message: str | None = Field(default=None, max_length=MAX_INQUIRY_CHARS)
    child_ages: list[str] = Field(default_factory=list)
    interest: str | None = None
    class_context: list[str] = Field(default_factory=list, max_length=MAX_CLASS_LINES)
    trial_offer: str | None = None
    public_page_url: str | None = None


class ReplyDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: str = Field(min_length=1, max_length=90)
    body: str = Field(min_length=1, max_length=900)
    key_points: list[str] = Field(default_factory=list, max_length=4)


@dataclass(frozen=True)
class PipelineReplyDraft:
    draft: ReplyDraft
    prompt_version: str


def _allowed_link_forms(allowed_url: str | None) -> frozenset[str]:
    """The exact spellings of the public page URL a draft may contain: the
    full URL, without its scheme, the bare host, and host + path. Structural,
    never a substring match, so "evil.example" cannot ride on a longer URL."""
    if not allowed_url:
        return frozenset()
    parts = urlsplit(allowed_url.strip().lower())
    host = parts.hostname or ""
    if not host:
        return frozenset()
    path = parts.path.rstrip("/")
    full = allowed_url.strip().lower().rstrip("/")
    return frozenset({full, f"{host}{path}", host, f"{parts.scheme}://{host}", f"//{host}{path}"})


def parse_reply_draft(text: str, *, allowed_url: str | None) -> ReplyDraft:
    """Strict parse of the model's answer; any failure is a 502."""
    raw = text.strip()
    fenced = _FENCE.match(raw)
    if fenced:
        raw = fenced.group(1)
    try:
        draft = ReplyDraft.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as exc:
        raise AiProviderError("the model's answer could not be read") from exc
    allowed = _allowed_link_forms(allowed_url)
    for url in _URL.findall(draft.body):
        found = url.rstrip(".,;)").rstrip("/").lower()
        if found not in allowed:
            raise AiProviderError("the model's answer could not be read", reason="invented_link")
    return draft


class DraftPipelineReply:
    def __init__(
        self,
        *,
        llm: LlmPort,
        record_ai_call: RecordAiCall,
        entitlement: AiEntitlement,
        inquiries: InquirySource,
        context: ReplyContextSource,
        staff: StaffNames,
    ) -> None:
        self._llm = llm
        self._record = record_ai_call
        self._entitlement = entitlement
        self._inquiries = inquiries
        self._context = context
        self._staff = staff

    async def execute(self, *, contact_id: str, staff_user_id: str) -> PipelineReplyDraft:
        facts = await self._inquiries.inquiry_facts(contact_id)
        if facts is None:
            raise InquiryNotFound("contact not found", contact_id=contact_id)
        if not await self._entitlement.has_ai():
            raise AiNotEntitled("AI replies are part of the Growth plan")
        async with self._record.reserve(FEATURE):
            context = await self._context.reply_context()
            message = (facts.inquiry_message or "")[:MAX_INQUIRY_CHARS] or None
            payload = PipelineReplyInput(
                academy_name=context.academy_name,
                staff_first_name=await self._staff.first_name(staff_user_id) or "the team",
                inquiry_message=message,
                child_ages=list(facts.child_ages),
                interest=facts.interest,
                class_context=list(context.class_context[:MAX_CLASS_LINES]),
                trial_offer=context.trial_offer,
                public_page_url=context.public_page_url,
            )
            prompt = PROMPTS[FEATURE]
            result = await self._llm.complete(
                prompt_version=prompt.version,
                system=prompt.system_text,
                user=json.dumps(payload.model_dump(mode="json"), ensure_ascii=False),
                max_tokens=MAX_TOKENS,
            )
        # The tokens are spent whatever the answer looks like: record first.
        await self._record.execute(
            feature=FEATURE,
            prompt_version=prompt.version,
            result=result,
            approver=staff_user_id,
        )
        draft = parse_reply_draft(result.text, allowed_url=context.public_page_url)
        return PipelineReplyDraft(draft=draft, prompt_version=prompt.version)
