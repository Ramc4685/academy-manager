"""Roster-import copilot (Phase 2 slice B2): masking, what the model is shown,
the cap pre-check, strict parsing, and the per-academy sharing switch."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.v2.composition.ai_import import AcademyImportValueSharing
from backend.v2.contexts.ai.application.use_cases import map_import_columns as mic
from backend.v2.contexts.ai.application.use_cases.map_import_columns import (
    MapImportColumns,
    mask_cell,
    read_sample,
)
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.domain.errors import (
    AiImportSampleRejected,
    AiMonthlyCapReached,
    AiProviderError,
)
from backend.v2.contexts.ai.domain.models import DEFAULT_MODEL, AiCallRecord, LlmResult
from backend.v2.contexts.ai.domain.prompts import PROMPTS
from backend.v2.contexts.crm.domain import family_import as crm
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.fixtures.ai_counters import counters_at

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
CSV = (
    "Guardian,E-mail,Phone,Child,DOB\n"
    "Jane Doe,jane.doe@gmail.com,3095550123,Sam Doe,2015-03-04\n"
    "Ann Roe,ann@example.org,(309) 555-0199,Kit Roe,2016-07-08\n"
)
GOOD_ANSWER = json.dumps(
    {
        "mappings": [
            {
                "target": "parent_name",
                "source_headers": ["Guardian"],
                "confidence": "high",
                "note": "",
            },
            {
                "target": "parent_email",
                "source_headers": ["E-mail"],
                "confidence": "high",
                "note": "",
            },
            {
                "target": "parent_phone",
                "source_headers": ["Phone"],
                "confidence": "high",
                "note": "",
            },
            {
                "target": "student_name",
                "source_headers": ["Child"],
                "confidence": "high",
                "note": "",
            },
            {
                "target": "student_date_of_birth",
                "source_headers": ["DOB"],
                "confidence": "medium",
                "note": "Looks like ISO dates.",
            },
        ],
        "unmapped_headers": [],
        "notes": "",
    }
)


def test_caps_and_columns_mirror_the_crm_import() -> None:
    assert mic.MAX_IMPORT_BYTES == crm.MAX_IMPORT_BYTES
    assert mic.MAX_IMPORT_ROWS == crm.MAX_IMPORT_ROWS
    assert mic.IMPORT_COLUMNS == crm.IMPORT_COLUMNS
    assert mic.REQUIRED_COLUMNS == crm.REQUIRED_COLUMNS
    assert PROMPTS[mic.FEATURE].version == "roster-import-map-v1"


@pytest.mark.parametrize(
    ("raw", "masked"),
    [
        ("Jane Doe", "Aaaa Aaa"),
        ("jane.doe@gmail.com", "aaaa.aaa@aaaaa.aaa"),
        ("(309) 555-0123", "(999) 999-9999"),
        ("2015-03-04", "9999-99-99"),
        ("x" * 40, "a" * 24),
    ],
)
def test_mask_cell_keeps_only_the_shape(raw: str, masked: str) -> None:
    assert mask_cell(raw) == masked


def test_read_sample_keeps_label_like_headers_and_caps_rows() -> None:
    many = "A,B\n" + "".join(f"Row {i},{i}\n" for i in range(8))
    sample = read_sample(many, share_values=False)
    assert sample.headers == ("A", "B") == sample.file_headers
    assert len(sample.rows) == mic.SAMPLE_ROWS
    assert sample.rows[0] == ("Aaa 9", "9")
    assert sample.masked is True


HEADERLESS_CSV = CSV.split("\n", 1)[1]


def test_read_sample_relabels_a_header_row_that_is_really_data() -> None:
    # No header row: the email relabels every column, so the names go too.
    sample = read_sample(HEADERLESS_CSV, share_values=False)
    assert sample.headers == tuple(f"(column {i})" for i in range(1, 6))
    assert sample.file_headers[0] == "Jane Doe"
    # A phone or a date in any header cell also means a headerless file.
    for row in (
        "Guardian,3095550123,Child",
        "Guardian,(309) 555-0123,Child",
        "Guardian,Child,2015-03-04",
    ):
        assert read_sample(row + "\na,b,c\n", share_values=False).headers == (
            "(column 1)",
            "(column 2)",
            "(column 3)",
        )
    # Label-like headers stay; only an over-long one relabels itself.
    sample = read_sample("Guardian,Long header " + "x" * 40 + "\na,b\n", share_values=False)
    assert sample.headers == ("Guardian", "(column 2)")
    # Sharing on sends headers as written.
    assert read_sample(HEADERLESS_CSV, share_values=True).headers[0] == "Jane Doe"


@pytest.mark.parametrize("share_values", [False, True])
def test_duplicate_headers_are_refused_before_any_model_call(share_values: bool) -> None:
    with pytest.raises(AiImportSampleRejected, match="Columns 1 and 3 have the same name") as info:
        read_sample("parent name,Child,Parent Name\na,b,c\n", share_values=share_values)
    # By position only: in a headerless file the header text is a person's name.
    assert "Parent Name" not in str(info.value)
    assert info.value.details == {"columns": [1, 3]}


async def test_phone_only_headerless_row_leaks_nothing() -> None:
    # No email anywhere: the phone alone must mark the row as data.
    csv_text = "Jane Doe,3095550123,Sam Doe,2015-03-04\nAnn Roe,3095550199,Kit Roe,2016-07-08\n"
    answer = _answer(
        mappings=[
            {"target": "parent_name", "source_headers": ["(column 1)"], "confidence": "low"},
            {"target": "student_name", "source_headers": ["(column 3)"], "confidence": "low"},
        ],
        unmapped_headers=["(column 2)", "(column 4)"],
    )
    llm = FakeLlm(answer)
    use_case, _ = _use_case(llm)
    result = await use_case.execute(csv_text=csv_text, approver="u")
    user = llm.calls[0]["user"]
    for secret in ("Jane", "Doe", "Sam", "3095550123", "2015-03-04"):
        assert secret not in user
    assert json.loads(user)["headers"] == [f"(column {i})" for i in range(1, 5)]
    assert result.draft.mappings[0].source_headers == ["Jane Doe"]
    assert result.draft.unmapped_headers == ["3095550123", "2015-03-04"]


async def test_headerless_file_leaks_nothing_and_answers_in_file_headers() -> None:
    answer = _answer(
        mappings=[
            {"target": "parent_name", "source_headers": ["(column 1)"], "confidence": "low"},
            {"target": "student_name", "source_headers": ["(column 4)"], "confidence": "low"},
        ],
        unmapped_headers=["(column 2)", "(column 3)", "(column 5)"],
    )
    llm = FakeLlm(answer)
    use_case, _ = _use_case(llm)
    result = await use_case.execute(csv_text=HEADERLESS_CSV, approver="u")
    user = llm.calls[0]["user"]
    for secret in ("Jane", "Doe", "jane.doe@gmail.com", "3095550123", "2015-03-04"):
        assert secret not in user
    assert result.draft.mappings[0].source_headers == ["Jane Doe"]
    assert result.draft.unmapped_headers == ["jane.doe@gmail.com", "3095550123", "2015-03-04"]


def test_read_sample_refuses_what_the_import_refuses() -> None:
    with pytest.raises(AiImportSampleRejected):
        read_sample("a,b\n" + "x,y\n" * (mic.MAX_IMPORT_ROWS + 1), share_values=False)
    with pytest.raises(AiImportSampleRejected):
        read_sample("a,b\n" + "x" * mic.MAX_IMPORT_BYTES, share_values=False)
    with pytest.raises(AiImportSampleRejected):
        read_sample("a,b\n", share_values=False)
    with pytest.raises(AiImportSampleRejected):
        read_sample("", share_values=False)


class FakeLlm:
    def __init__(self, text: str = GOOD_ANSWER) -> None:
        self.text = text
        self.calls: list[dict] = []

    async def complete(self, *, prompt_version: str, system: str, user: str, max_tokens: int):
        self.calls.append(
            {
                "prompt_version": prompt_version,
                "system": system,
                "user": user,
                "max_tokens": max_tokens,
            }
        )
        return LlmResult(
            text=self.text, input_tokens=5, output_tokens=5, cost_cents=1, model=DEFAULT_MODEL
        )


class FakeCalls:
    def __init__(self, used: int = 0) -> None:
        self.used = used
        self.recorded: list[AiCallRecord] = []

    async def count_since(self, since: datetime) -> int:
        return self.used

    async def record(self, call: AiCallRecord) -> None:
        self.recorded.append(call)


class FakeCap:
    def __init__(self, cap: int = 200) -> None:
        self.cap = cap

    async def monthly_cap(self) -> int:
        return self.cap


class FakeSharing:
    def __init__(self, value: bool) -> None:
        self.value = value

    async def share_values(self) -> bool:
        return self.value


def _use_case(llm: FakeLlm, *, share: bool = False, used: int = 0, cap: int = 200):
    calls = FakeCalls(used)
    record = RecordAiCall(
        calls=calls, counters=counters_at(used, NOW), cap_source=FakeCap(cap), clock=lambda: NOW
    )
    return MapImportColumns(llm=llm, record_ai_call=record, sharing=FakeSharing(share)), calls


async def test_valid_answer_becomes_a_draft_and_is_recorded() -> None:
    llm = FakeLlm()
    use_case, calls = _use_case(llm)
    result = await use_case.execute(csv_text=CSV, approver="u-admin")
    assert [m.target for m in result.draft.mappings] == list(mic.IMPORT_COLUMNS)
    assert result.sample_mode == "masked"
    assert result.prompt_version == "roster-import-map-v1"
    (call,) = llm.calls
    assert call["prompt_version"] == "roster-import-map-v1"
    assert call["system"] == PROMPTS["roster_import_map"].system_text
    assert call["max_tokens"] == mic.MAX_TOKENS
    (row,) = calls.recorded
    assert row.feature == "roster_import_map" and row.approver == "u-admin"


async def test_masked_message_carries_shapes_not_values() -> None:
    llm = FakeLlm()
    use_case, _ = _use_case(llm, share=False)
    await use_case.execute(csv_text=CSV, approver="u")
    user = llm.calls[0]["user"]
    for secret in ("Jane Doe", "jane.doe@gmail.com", "3095550123", "Sam Doe", "2015-03-04"):
        assert secret not in user
    for shape in ("Aaaa Aaa", "aaaa.aaa@aaaaa.aaa", "9999999999", "(999) 999-9999", "9999-99-99"):
        assert shape in user
    for header in ("Guardian", "E-mail", "Phone", "Child", "DOB"):
        assert header in user
    assert json.loads(user).keys() == {
        "headers",
        "sample_rows_are",
        "sample_rows",
        "target_columns",
    }


async def test_shared_message_carries_the_real_sample_cells() -> None:
    llm = FakeLlm()
    use_case, _ = _use_case(llm, share=True)
    result = await use_case.execute(csv_text=CSV, approver="u")
    user = llm.calls[0]["user"]
    assert result.sample_mode == "values"
    for value in ("Jane Doe", "jane.doe@gmail.com", "3095550123"):
        assert value in user


async def test_cap_reached_refuses_before_the_model_is_called() -> None:
    llm = FakeLlm()
    use_case, calls = _use_case(llm, used=200, cap=200)
    with pytest.raises(AiMonthlyCapReached):
        await use_case.execute(csv_text=CSV, approver="u")
    assert llm.calls == [] and calls.recorded == []


def _answer(**changes) -> str:
    body = json.loads(GOOD_ANSWER)
    body.update(changes)
    return json.dumps(body)


@pytest.mark.parametrize(
    "text",
    [
        "not json at all",
        _answer(mappings=json.loads(GOOD_ANSWER)["mappings"] * 2),  # duplicate targets
        _answer(
            mappings=[{"target": "parent_name", "source_headers": ["Nope"], "confidence": "high"}]
        ),
        _answer(mappings=json.loads(GOOD_ANSWER)["mappings"][1:]),  # parent_name missing
        _answer(unmapped_headers=["Guardian"]),  # a header both mapped and unmapped
        _answer(extra="field"),
    ],
)
async def test_unreadable_answers_are_a_provider_error_but_still_recorded(text: str) -> None:
    llm = FakeLlm(text)
    use_case, calls = _use_case(llm)
    with pytest.raises(AiProviderError):
        await use_case.execute(csv_text=CSV, approver="u")
    assert len(calls.recorded) == 1


async def test_fenced_json_is_accepted() -> None:
    llm = FakeLlm("```json\n" + GOOD_ANSWER + "\n```")
    use_case, _ = _use_case(llm)
    result = await use_case.execute(csv_text=CSV, approver="u")
    assert len(result.draft.mappings) == 5


async def test_sharing_switch_is_read_per_academy() -> None:
    db = AsyncMongoMockClient()["test_db"]
    await db["academies"].insert_many(
        [
            {"academy_id": "acad-a", "ai": {"share_import_values": True, "monthly_call_cap": 7}},
            {"academy_id": "acad-b", "ai": {"share_import_values": False}},
            {"academy_id": "acad-c"},
        ]
    )
    sharing = AcademyImportValueSharing(MongoAcademyRepository(db))
    with tenant_scope("acad-a"):
        assert await sharing.share_values() is True
    with tenant_scope("acad-b"):
        assert await sharing.share_values() is False
    with tenant_scope("acad-c"):
        assert await sharing.share_values() is False
        await sharing.set_share_values(True)
        assert await sharing.share_values() is True
    with tenant_scope("acad-a"):
        await sharing.set_share_values(False)
        assert await sharing.share_values() is False
    doc = await db["academies"].find_one({"academy_id": "acad-a"})
    assert doc["ai"]["monthly_call_cap"] == 7  # the cap next to it is untouched


async def test_message_never_carries_more_than_five_data_rows() -> None:
    llm = FakeLlm(
        _answer(
            mappings=[
                m
                for m in json.loads(GOOD_ANSWER)["mappings"]
                if m["source_headers"][0] in ("Guardian", "Child")
            ]
        )
    )
    use_case, _ = _use_case(llm, share=True)
    csv_text = "Guardian,Child\n" + "".join(f"Parent {i},Kid {i}\n" for i in range(20))
    await use_case.execute(csv_text=csv_text, approver="u")
    facts = json.loads(llm.calls[0]["user"])
    assert len(facts["sample_rows"]) == 5
    assert "Parent 7" not in llm.calls[0]["user"]
