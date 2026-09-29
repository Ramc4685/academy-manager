"""Academy logo upload (Settings overhaul Phase 4, PR 13b).

The use case owns the rules; the bytes-to-PNG conversion and the object store
are injected (``ImageProcessor``, ``MediaObjectStore``) so this module never
imports Pillow or Firebase and tests run against a fake store.

Rules:

* The academy comes from the resolved tenant (``academy_id`` argument, taken
  from auth claims by the route), never from the request body.
* Objects are never deleted or overwritten: each upload gets a fresh uuid
  path, so an email sent last month keeps pointing at last month's logo.
* One audit row per stored object in ``academy_media``.
* The use case does NOT write ``academies.logo_url``. The route returns the
  URL and the Settings form saves it through ``PATCH /admin/academy``, the one
  writer of that field.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

log = logging.getLogger(__name__)

#: Largest accepted upload, in bytes (the mockup says "up to 2 MB").
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
#: Uploads per academy per hour before the endpoint answers 429.
MAX_UPLOADS_PER_HOUR = 20


class LogoRejected(ValueError):
    """The file cannot be used as a logo. The message is safe to show."""


class LogoTooLarge(LogoRejected):
    """The file is over ``MAX_UPLOAD_BYTES``."""


class LogoRateLimited(RuntimeError):
    """Too many uploads for this academy in the last hour."""


class MediaStorageUnavailable(RuntimeError):
    """The object store failed. Nothing was stored."""


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    width: int
    height: int
    content_type: str = "image/png"


ImageProcessor = Callable[[bytes], ProcessedImage]


class MediaObjectStore(Protocol):
    async def put_public(self, *, path: str, data: bytes, content_type: str) -> str:
        """Store a NEW object and return its public URL.

        Must raise ``MediaStorageUnavailable`` on any failure, and must refuse
        (not overwrite) a path that already exists.
        """
        ...


class AcademyMediaRepo(Protocol):
    async def record(self, doc: dict[str, Any]) -> None: ...
    async def count_since(self, since: datetime) -> int: ...


@dataclass(frozen=True)
class UploadedLogo:
    logo_url: str


class UploadAcademyLogo:
    def __init__(
        self,
        *,
        store: MediaObjectStore,
        media_repo: AcademyMediaRepo,
        process_image: ImageProcessor,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._repo = media_repo
        self._process = process_image
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(self, *, academy_id: str, uploaded_by: str, raw: bytes) -> UploadedLogo:
        if len(raw) > MAX_UPLOAD_BYTES:
            raise LogoTooLarge("That image is over 2 MB. Choose a smaller PNG or JPG.")
        now = self._now()
        if await self._repo.count_since(now - timedelta(hours=1)) >= MAX_UPLOADS_PER_HOUR:
            raise LogoRateLimited("Too many uploads. Try again in a little while.")
        processed = self._process(raw)
        object_path = f"academies/{academy_id}/logo/{uuid4().hex}.png"
        url = await self._store.put_public(
            path=object_path, data=processed.data, content_type=processed.content_type
        )
        await self._repo.record(
            {
                "kind": "logo",
                "object_path": object_path,
                "logo_url": url,
                "uploaded_by": uploaded_by,
                "size_bytes": len(processed.data),
                "original_size_bytes": len(raw),
                "sha256": hashlib.sha256(processed.data).hexdigest(),
                "content_type": processed.content_type,
                "width": processed.width,
                "height": processed.height,
                "created_at": now,
            }
        )
        return UploadedLogo(logo_url=url)
