"""B5: narrate the owner's month-close view (paid, owner-only).

The model sees a reduced copy of the payload the owner already sees on
``GET /admin/reports/month-close`` (``reduce_month_close_payload``) and
answers with a short summary and up to three "fix first" links. It never
computes money: after the call every number in the answer must already be in
the input and every href must be an odd-item href or a fixed admin page.

Order, pinned by tests: entitlement (403) -> cap (429) -> complete -> record
the call (always, before parsing) -> parse (502) -> number and href check (502).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from backend.v2.contexts.ai.application.ports import AiEntitlement, LlmPort
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.domain.errors import AiNotEntitled, AiProviderError
from backend.v2.contexts.ai.domain.prompts import PROMPTS

FEATURE = "month_close_narrator"
MAX_TOKENS = 1200
#: Linked items the model sees per odd check (the payload ships up to 20).
MAX_ITEMS_PER_CHECK = 5
#: Hrefs the answer may use besides the odd items' own.
FIXED_HREFS: frozenset[str] = frozenset(
    {"/admin/payments", "/admin/dues", "/admin/families", "/admin/billing-health", "/admin/reports"}
)
_UNREADABLE = "the model's answer could not be read"
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
#: Any run of digits, with optional thousands separators and decimals, and an
#: optional leading dollar sign.
_NUMBER = re.compile(r"\$?\d[\d,]*(?:\.\d+)?")


class MonthClosePayloadSource(Protocol):
    """The existing month-close reader (``app.state.admin_month_close``)."""

    async def build(self, period: str | None = None) -> dict[str, Any]: ...


# --------------------------------------------------------------------------- input


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OddItemInput(_Strict):
    label: str
    href: str


class OddInput(_Strict):
    code: str
    label: str
    count: int
    items: list[OddItemInput] = Field(max_length=MAX_ITEMS_PER_CHECK)


class MoneyInput(_Strict):
    billed_cents: int
    collected_cents: int
    outstanding_cents: int
    collection_rate: float | None


class InvoicesInput(_Strict):
    generated: int
    emailed: int
    autopay_notices: int
    not_sent: int
    voided: int


class AutopayRunInput(_Strict):
    has_run: bool
    charge_on_varies: bool
    scheduled: int
    succeeded: int
    failed: int
    pending: int


class MonthCloseNarratorInput(_Strict):
    """Exactly what the model sees. ``extra="forbid"`` on every level."""

    period: str
    timezone: str
    money: MoneyInput
    invoices: InvoicesInput
    autopay_run: AutopayRunInput
    odd: list[OddInput]
    warnings: list[str]


def _count(section: dict[str, Any], key: str) -> int:
    tally = section.get(key)
    return int(tally.get("count", 0)) if isinstance(tally, dict) else 0


def reduce_month_close_payload(payload: dict[str, Any]) -> MonthCloseNarratorInput:
    """Pure: pick the allowed facts out of ``build_month_close_view``'s dict.

    Everything else (void reasons, tuition discounts, item ids and kinds,
    charge dates, anything a future reader adds) is dropped here, so the model
    never sees a field this function does not name.
    """
    money = payload.get("money") or {}
    invoices = payload.get("invoices") or {}
    run = payload.get("autopay_run") or {}
    return MonthCloseNarratorInput(
        period=str(payload.get("period", "")),
        timezone=str(payload.get("timezone", "")),
        money=MoneyInput(
            billed_cents=int(money.get("billed_cents", 0)),
            collected_cents=int(money.get("collected_cents", 0)),
            outstanding_cents=int(money.get("outstanding_cents", 0)),
            collection_rate=money.get("collection_rate"),
        ),
        invoices=InvoicesInput(
            generated=int(invoices.get("generated", 0)),
            emailed=int(invoices.get("emailed", 0)),
            autopay_notices=int(invoices.get("autopay_notices", 0)),
            not_sent=int(invoices.get("not_sent", 0)),
            voided=int(invoices.get("voided", 0)),
        ),
        autopay_run=AutopayRunInput(
            has_run=bool(run.get("has_run", False)),
            charge_on_varies=bool(run.get("charge_on_varies", False)),
            scheduled=_count(run, "scheduled"),
            succeeded=_count(run, "succeeded"),
            failed=_count(run, "failed"),
            pending=_count(run, "pending"),
        ),
        odd=[
            OddInput(
                code=str(check.get("code", "")),
                label=str(check.get("label", "")),
                count=int(check.get("count", 0)),
                items=[
                    OddItemInput(label=str(item.get("label", "")), href=str(item.get("href", "")))
                    for item in (check.get("items") or [])[:MAX_ITEMS_PER_CHECK]
                    if isinstance(item, dict)
                ],
            )
            for check in payload.get("odd") or []
            if isinstance(check, dict)
        ],
        warnings=[str(w) for w in payload.get("warnings") or []],
    )


# --------------------------------------------------------------------------- output


class FixFirst(_Strict):
    text: str = Field(min_length=1, max_length=120)
    href: str = Field(min_length=1)


class Narrative(_Strict):
    summary: str = Field(min_length=1)
    fix_first: list[FixFirst] = Field(max_length=3)

    @field_validator("summary")
    @classmethod
    def _at_most_120_words(cls, value: str) -> str:
        if len(value.split()) > 120:
            raise ValueError("summary is over 120 words")
        return value


class MonthCloseNarrative(_Strict):
    summary: str
    fix_first: list[FixFirst]
    prompt_version: str
    generated_at: datetime


def parse_narrative(text: str) -> Narrative:
    fenced = _FENCE.match(text)
    body = fenced.group(1) if fenced else text
    try:
        return Narrative.model_validate(json.loads(body))
    except (ValueError, ValidationError) as exc:
        raise AiProviderError(_UNREADABLE) from exc


def allowed_numbers(inp: MonthCloseNarratorInput) -> frozenset[str]:
    """Every number token the answer may contain, as normalised strings.

    A cents value is allowed as cents, as whole dollars, and as dollars with
    two decimals; counts as given; the rate as given and as a whole percent;
    and the period's year and month digits. Digits inside labels (invoice
    numbers, family names) are NOT added here: a label may be quoted only
    verbatim, and :func:`check_narrative` removes verbatim labels before it
    scans for numbers, so a name's digits never authorise an invented figure.
    """
    allowed: set[str] = set()
    for value in (inp.money.billed_cents, inp.money.collected_cents, inp.money.outstanding_cents):
        allowed.update({str(value), str(value // 100), f"{value // 100}.{value % 100:02d}"})
    rate = inp.money.collection_rate
    if rate is not None:
        allowed.update({str(rate), str(round(rate * 100))})
    run = inp.autopay_run
    counts = [
        *inp.invoices.model_dump().values(),
        run.scheduled,
        run.succeeded,
        run.failed,
        run.pending,
        *(check.count for check in inp.odd),
    ]
    allowed.update(str(value) for value in counts)
    year, _, month = inp.period.partition("-")
    allowed.update({year, month, month.lstrip("0") or "0"})
    return frozenset(allowed)


def check_narrative(narrative: Narrative, inp: MonthCloseNarratorInput) -> None:
    """The never-computes-money rule: raise ``AiProviderError`` on any number
    not in the input or any href outside the input's items and ``FIXED_HREFS``."""
    allowed = allowed_numbers(inp)
    labels = sorted(
        {label for check in inp.odd for label in (check.label, *(i.label for i in check.items))},
        key=len,
        reverse=True,
    )
    texts = [narrative.summary, *(fix.text for fix in narrative.fix_first)]
    for label in labels:
        texts = [text.replace(label, " ") for text in texts]
    for token in (m.group(0) for text in texts for m in _NUMBER.finditer(text)):
        if token.lstrip("$").replace(",", "") not in allowed:
            raise AiProviderError(f"{_UNREADABLE}: number {token!r} is not in the month-close view")
    hrefs = FIXED_HREFS | {item.href for check in inp.odd for item in check.items}
    for fix in narrative.fix_first:
        if fix.href not in hrefs:
            raise AiProviderError(f"{_UNREADABLE}: link {fix.href!r} is not a month-close link")


# --------------------------------------------------------------------------- use case


class NarrateMonthClose:
    def __init__(
        self,
        *,
        llm: LlmPort,
        entitlement: AiEntitlement,
        record_ai_call: RecordAiCall,
        source: MonthClosePayloadSource,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._llm = llm
        self._entitlement = entitlement
        self._record = record_ai_call
        self._source = source
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, *, period: str, approver: str) -> MonthCloseNarrative:
        if not await self._entitlement.has_ai():
            raise AiNotEntitled("AI summaries are part of the Growth plan")
        await self._record.assert_under_cap()
        inp = reduce_month_close_payload(await self._source.build(period))
        prompt = PROMPTS[FEATURE]
        result = await self._llm.complete(
            prompt_version=prompt.version,
            system=prompt.system_text,
            user=json.dumps(inp.model_dump(), sort_keys=True),
            max_tokens=MAX_TOKENS,
        )
        # Recorded before parsing: a malformed answer still spent tokens.
        await self._record.execute(
            feature=FEATURE, prompt_version=prompt.version, result=result, approver=approver
        )
        narrative = parse_narrative(result.text)
        check_narrative(narrative, inp)
        return MonthCloseNarrative(
            summary=narrative.summary,
            fix_first=narrative.fix_first,
            prompt_version=prompt.version,
            generated_at=self._clock(),
        )
