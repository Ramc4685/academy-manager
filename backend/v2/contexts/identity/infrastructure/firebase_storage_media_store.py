"""Firebase Storage adapter for academy media.

Objects are written through the Admin SDK (which bypasses Storage rules) and
made readable by a per-object Firebase download token, so the URL works in
email clients and needs no CSP change. The bucket itself is never public.
Existing objects are never overwritten (``if_generation_match=0``).
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote
from uuid import uuid4

from backend.v2.contexts.identity.application.academy_media import MediaStorageUnavailable
from backend.v2.contexts.identity.infrastructure.firebase_admin_adapter import (
    _ensure_firebase_app,
)

log = logging.getLogger(__name__)

_CACHE_CONTROL = "public, max-age=31536000, immutable"


def firebase_url_base(bucket: str) -> str:
    """The prefix every download URL of ``bucket`` starts with."""
    return f"https://firebasestorage.googleapis.com/v0/b/{bucket}/o/"


def firebase_download_url(bucket: str, path: str, token: str) -> str:
    return f"{firebase_url_base(bucket)}{quote(path, safe='')}?alt=media&token={token}"


class FirebaseStorageMediaStore:
    def __init__(self, bucket_name: str) -> None:
        self._bucket_name = bucket_name

    def _upload(self, path: str, data: bytes, content_type: str, token: str) -> None:
        from firebase_admin import storage

        bucket = storage.bucket(self._bucket_name, app=_ensure_firebase_app())
        blob = bucket.blob(path)
        blob.metadata = {"firebaseStorageDownloadTokens": token}
        blob.cache_control = _CACHE_CONTROL
        blob.upload_from_string(data, content_type=content_type, if_generation_match=0)

    async def put_public(self, *, path: str, data: bytes, content_type: str) -> str:
        token = str(uuid4())
        try:
            await asyncio.to_thread(self._upload, path, data, content_type, token)
        except Exception as exc:
            log.exception("media upload to %s failed", self._bucket_name)
            raise MediaStorageUnavailable("media storage failed") from exc
        return firebase_download_url(self._bucket_name, path, token)

    def _delete(self, path: str) -> None:
        from firebase_admin import storage
        from google.api_core.exceptions import NotFound

        bucket = storage.bucket(self._bucket_name, app=_ensure_firebase_app())
        try:
            bucket.blob(path).delete()
        except NotFound:
            return

    async def delete_public(self, *, path: str) -> None:
        """Delete one object; an already-missing object is fine."""
        await asyncio.to_thread(self._delete, path)
