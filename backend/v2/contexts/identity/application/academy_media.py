"""Academy logo upload (Settings overhaul Phase 4, PR 13b).

The use case owns the rules; the bytes-to-PNG conversion and the object store
are injected (``ImageProcessor``, ``MediaObjectStore``) so this module never
imports Pillow or Firebase and tests run against a fake store.

Rules:

* The academy comes from the resolved tenant (``academy_id`` argument, taken
  from auth claims by the route), never from the request body.
* Objects are never deleted or overwritten: each upload gets a fresh uuid
  path, so an email sent last month keeps pointing at last month's logo.
* One audit row per ATTEMPT in ``academy_media``, written before any work so
  rejected uploads count toward the hourly cap and a stored object always has
  a row (status ``pending`` -> ``stored`` / ``rejected`` / ``failed``).
* Pillow work runs in a worker thread behind a small semaphore, so it never
  blocks the event loop and concurrent uploads are bounded.
* The use case does NOT write ``academies.logo_url``. The route returns the
  URL and the Settings form saves it through ``PATCH /admin/academy``, the one
  writer of that field.
"""

from __future__ import annotations

import asyncio
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
#: Images decoded at once per process (bounds CPU and peak memory).
MAX_CONCURRENT_PROCESSING = 2


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
    async def record(self, doc: dict[str, Any]) -> str: ...
    async def update(self, media_id: str, fields: dict[str, Any]) -> None: ...
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
        self._slots = asyncio.Semaphore(MAX_CONCURRENT_PROCESSING)

    async def execute(self, *, academy_id: str, uploaded_by: str, raw: bytes) -> UploadedLogo:
        if len(raw) > MAX_UPLOAD_BYTES:
            raise LogoTooLarge("That image is over 2 MB. Choose a smaller PNG or JPG.")
        now = self._now()
        # Insert first, then count: the row counts itself, so parallel bursts
        # see each other and rejected files are throttled too.
        media_id = await self._repo.record(
            {
                "kind": "logo",
                "status": "pending",
                "uploaded_by": uploaded_by,
                "original_size_bytes": len(raw),
                "created_at": now,
            }
        )
        if await self._repo.count_since(now - timedelta(hours=1)) > MAX_UPLOADS_PER_HOUR:
            await self._repo.update(media_id, {"status": "rate_limited"})
            raise LogoRateLimited("Too many uploads. Try again in a little while.")
        try:
            async with self._slots:
                processed = await asyncio.to_thread(self._process, raw)
        except LogoRejected:
            await self._repo.update(media_id, {"status": "rejected"})
            raise
        except BaseException:
            # Includes cancellation (client gone), so no row stays "pending".
            await asyncio.shield(self._repo.update(media_id, {"status": "failed"}))
            raise
        object_path = f"academies/{academy_id}/logo/{uuid4().hex}.png"
        try:
            url = await self._store.put_public(
                path=object_path, data=processed.data, content_type=processed.content_type
            )
        except MediaStorageUnavailable:
            await self._repo.update(media_id, {"status": "failed"})
            raise
        try:
            await self._repo.update(
                media_id,
                {
                    "status": "stored",
                    "object_path": object_path,
                    "logo_url": url,
                    "size_bytes": len(processed.data),
                    "sha256": hashlib.sha256(processed.data).hexdigest(),
                    "content_type": processed.content_type,
                    "width": processed.width,
                    "height": processed.height,
                },
            )
        except Exception:
            # The object exists but its row is still "pending": log the path so
            # it can be reconciled by hand.
            log.error(
                "academy_media %s stored %s but finalising the row failed", media_id, object_path
            )
            raise
        return UploadedLogo(logo_url=url)
