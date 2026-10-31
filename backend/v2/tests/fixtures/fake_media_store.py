"""In-memory ``MediaObjectStore`` mirroring the real Firebase adapter.

Mirrors the semantics that matter: an existing path is REFUSED (the real
adapter uploads with ``if_generation_match=0``), every object carries its own
download token, and the returned URL has the real Firebase download shape.
"""

from __future__ import annotations

from uuid import uuid4

from backend.v2.contexts.identity.application.academy_media import MediaStorageUnavailable
from backend.v2.contexts.identity.infrastructure.firebase_storage_media_store import (
    firebase_download_url,
)


class FakeMediaStore:
    def __init__(self, bucket: str = "test-bucket", *, fail: bool = False) -> None:
        self.bucket = bucket
        self.fail = fail
        self.objects: dict[str, dict[str, object]] = {}

    async def put_public(self, *, path: str, data: bytes, content_type: str) -> str:
        if self.fail:
            raise MediaStorageUnavailable("boom")
        if path in self.objects:
            raise MediaStorageUnavailable("object already exists")
        token = str(uuid4())
        self.objects[path] = {"data": data, "content_type": content_type, "token": token}
        return firebase_download_url(self.bucket, path, token)

    async def delete_public(self, *, path: str) -> None:
        if self.fail:
            raise MediaStorageUnavailable("boom")
        self.objects.pop(path, None)


class FakeMediaRepo:
    def __init__(self, existing_recent: int = 0) -> None:
        self.rows: list[dict[str, object]] = []
        self.existing_recent = existing_recent

    async def record(self, doc: dict[str, object]) -> str:
        self.rows.append(dict(doc))
        return str(len(self.rows) - 1)

    async def update(self, media_id: str, fields: dict[str, object]) -> None:
        self.rows[int(media_id)].update(fields)

    async def count_since(self, since) -> int:
        return self.existing_recent + len(self.rows)
