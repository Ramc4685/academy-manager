"""PATCH /admin/academy output carries the same effective reply-to as GET."""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.identity.application.update_academy_use_case import UpdateAcademyUseCase


class _Repo:
    def __init__(self, doc: dict[str, Any]) -> None:
        self.doc = doc

    async def update_by_id(self, academy_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self.doc = {**self.doc, **fields}
        return self.doc

    async def upsert_defaults(self, academy_id: str) -> dict[str, Any]:
        return self.doc


async def test_patch_output_falls_back_to_support_email() -> None:
    repo = _Repo({"academy_id": "a1"})
    out = await UpdateAcademyUseCase(repo).execute("a1", {"support_email": "help@example.com"})
    assert out.effective_reply_to == "help@example.com"
    assert out.effective_reply_to_source == "support_email"


async def test_patch_output_prefers_explicit_reply_to() -> None:
    repo = _Repo({"academy_id": "a1", "support_email": "help@example.com"})
    out = await UpdateAcademyUseCase(repo).execute("a1", {"email_reply_to": "desk@example.com"})
    assert out.effective_reply_to == "desk@example.com"
    assert out.effective_reply_to_source == "reply_to"


async def test_patch_output_is_null_when_neither_is_set() -> None:
    out = await UpdateAcademyUseCase(_Repo({"academy_id": "a1"})).execute("a1", {})
    assert out.effective_reply_to is None
    assert out.effective_reply_to_source is None
