"""Request shape of the real Firebase adapter, against a fake bucket client."""

from __future__ import annotations

import sys
import types

import pytest

from backend.v2.contexts.identity.application.academy_media import MediaStorageUnavailable
from backend.v2.contexts.identity.infrastructure import firebase_storage_media_store as mod


class _Blob:
    def __init__(self, sink: dict) -> None:
        self.sink = sink
        self.metadata: dict | None = None
        self.cache_control: str | None = None

    def upload_from_string(self, data, content_type, if_generation_match):
        self.sink.update(
            data=data,
            content_type=content_type,
            if_generation_match=if_generation_match,
            metadata=self.metadata,
            cache_control=self.cache_control,
        )
        if self.sink.get("boom"):
            raise RuntimeError("403")


def _install(monkeypatch, sink: dict) -> None:
    class _Bucket:
        def blob(self, path):
            sink["path"] = path
            return _Blob(sink)

    def bucket(name, app=None):
        sink["bucket"] = name
        return _Bucket()

    fake = types.SimpleNamespace(bucket=bucket)
    monkeypatch.setitem(sys.modules, "firebase_admin.storage", fake)
    monkeypatch.setattr(sys.modules["firebase_admin"], "storage", fake, raising=False)
    monkeypatch.setattr(mod, "_ensure_firebase_app", lambda: object())


@pytest.mark.asyncio
async def test_upload_sets_token_metadata_and_refuses_overwrite(monkeypatch) -> None:
    sink: dict = {}
    _install(monkeypatch, sink)
    url = await mod.FirebaseStorageMediaStore("b1").put_public(
        path="academies/a/logo/x.png", data=b"png", content_type="image/png"
    )
    token = sink["metadata"]["firebaseStorageDownloadTokens"]
    assert sink["if_generation_match"] == 0
    assert sink["bucket"] == "b1" and sink["path"] == "academies/a/logo/x.png"
    assert url == (
        "https://firebasestorage.googleapis.com/v0/b/b1/o/academies%2Fa%2Flogo%2Fx.png"
        f"?alt=media&token={token}"
    )


@pytest.mark.asyncio
async def test_any_failure_becomes_storage_unavailable(monkeypatch) -> None:
    sink: dict = {"boom": True}
    _install(monkeypatch, sink)
    with pytest.raises(MediaStorageUnavailable):
        await mod.FirebaseStorageMediaStore("b1").put_public(
            path="p", data=b"x", content_type="image/png"
        )
