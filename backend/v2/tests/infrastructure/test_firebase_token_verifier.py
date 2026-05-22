from __future__ import annotations

import backend.v2.contexts.identity.infrastructure.firebase_token_verifier as verifier_module
import pytest
from backend.v2.contexts.identity.infrastructure.firebase_token_verifier import (
    FirebaseTokenVerifier,
)


@pytest.mark.asyncio
async def test_firebase_token_verifier_delegates_to_legacy_project_aware_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def fake_verify(token: str) -> dict[str, object]:
        seen.append(token)
        return {"email": "coach@example.com"}

    monkeypatch.setattr(verifier_module, "_load_legacy_verifier", lambda: fake_verify)

    claims = await FirebaseTokenVerifier().verify("id-token")

    assert seen == ["id-token"]
    assert claims == {"email": "coach@example.com"}
