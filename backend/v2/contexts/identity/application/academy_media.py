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

Landing-page photos (Settings overhaul Phase 6) reuse this whole path with a
``purpose``: ``logo`` (default; exactly the rules above), ``hero``,
``gallery`` and ``coach``. Photos get a larger byte cap and are re-encoded as
metadata-free JPEG with a per-purpose long edge; each purpose stores under its
own object path, per academy. A ``gallery`` photo may show children, so the
upload itself is refused unless the caller confirmed parent or guardian
consent. Like the logo, the URL is only returned: the public page settings
write path (``PATCH /admin/academy/public-page``) saves it and stamps consent.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, Protocol
from uuid import uuid4

log = logging.getLogger(__name__)

#: Largest accepted upload, in bytes (the mockup says "up to 2 MB").
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
#: Uploads per academy per hour (all purposes) before the endpoint answers
#: 429. Raised from 20 when photos joined the endpoint: setting up a page
#: (hero, a dozen gallery photos, coach portraits) is one sitting.
MAX_UPLOADS_PER_HOUR = 40
#: Images decoded at once per process (bounds CPU and peak memory).
MAX_CONCURRENT_PROCESSING = 2
#: Largest accepted landing-page photo (hero, gallery, coach), in bytes.
MAX_PHOTO_UPLOAD_BYTES = 5 * 1024 * 1024
#: Longest side of a stored hero or gallery photo, and of a coach portrait.
HERO_GALLERY_MAX_EDGE = 2400
COACH_MAX_EDGE = 800

MediaPurpose = Literal["logo", "hero", "gallery", "coach"]
MEDIA_PURPOSES: Final[tuple[str, ...]] = ("logo", "hero", "gallery", "coach")


@dataclass(frozen=True)
class PurposeRule:
    max_bytes: int
    #: Long edge of the stored photo; ``None`` means the logo pipeline.
    max_edge: int | None


PURPOSE_RULES: Final[dict[str, PurposeRule]] = {
    "logo": PurposeRule(MAX_UPLOAD_BYTES, None),
    "hero": PurposeRule(MAX_PHOTO_UPLOAD_BYTES, HERO_GALLERY_MAX_EDGE),
    "gallery": PurposeRule(MAX_PHOTO_UPLOAD_BYTES, HERO_GALLERY_MAX_EDGE),
    "coach": PurposeRule(MAX_PHOTO_UPLOAD_BYTES, COACH_MAX_EDGE),
}

GALLERY_CONSENT_REQUIRED = (
    "Confirm that parents or guardians of anyone shown agreed to this photo being published."
)


def too_large_message(max_bytes: int) -> str:
    return f"That image is over {max_bytes // (1024 * 1024)} MB. Choose a smaller PNG or JPG."


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
#: Photo re-encoder: ``(raw bytes, long edge in px) -> ProcessedImage``.
PhotoProcessor = Callable[[bytes, int], ProcessedImage]


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
    purpose: str = "logo"

    @property
    def url(self) -> str:
        return self.logo_url


class UploadAcademyLogo:
    def __init__(
        self,
        *,
        store: MediaObjectStore,
        media_repo: AcademyMediaRepo,
        process_image: ImageProcessor,
        process_photo: PhotoProcessor | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._repo = media_repo
        self._process = process_image
        self._process_photo = process_photo
        self._now = now or (lambda: datetime.now(UTC))
        self._slots = asyncio.Semaphore(MAX_CONCURRENT_PROCESSING)

    async def execute(
        self,
        *,
        academy_id: str,
        uploaded_by: str,
        raw: bytes,
        purpose: str = "logo",
        consent: bool = False,
    ) -> UploadedLogo:
        rule = PURPOSE_RULES.get(purpose)
        if rule is None:
            raise LogoRejected("Choose what the image is for: logo, hero, gallery or coach.")
        if purpose == "gallery" and not consent:
            # Before any row or work: nothing was attempted.
            raise LogoRejected(GALLERY_CONSENT_REQUIRED)
        if len(raw) > rule.max_bytes:
            raise LogoTooLarge(too_large_message(rule.max_bytes))
        now = self._now()
        # Insert first, then count: the row counts itself, so parallel bursts
        # see each other and rejected files are throttled too.
        media_id = await self._repo.record(
            {
                "kind": purpose,
                "status": "pending",
                **({"consent_confirmed": True} if purpose == "gallery" else {}),
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
                if rule.max_edge is None:
                    processed = await asyncio.to_thread(self._process, raw)
                else:
                    if self._process_photo is None:
                        raise MediaStorageUnavailable("photo processing is not configured")
                    processed = await asyncio.to_thread(self._process_photo, raw, rule.max_edge)
        except LogoRejected:
            await self._repo.update(media_id, {"status": "rejected"})
            raise
        except BaseException:
            # Includes cancellation (client gone), so no row stays "pending".
            await asyncio.shield(self._repo.update(media_id, {"status": "failed"}))
            raise
        extension = "jpg" if processed.content_type == "image/jpeg" else "png"
        object_path = f"academies/{academy_id}/{purpose}/{uuid4().hex}.{extension}"
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
        return UploadedLogo(logo_url=url, purpose=purpose)
