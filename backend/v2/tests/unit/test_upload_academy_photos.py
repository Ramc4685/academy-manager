"""Landing-page photo uploads (hero, gallery, coach) through UploadAcademyLogo."""

from __future__ import annotations

import io
import re
from datetime import UTC, datetime

import pytest
from PIL import Image

from backend.v2.contexts.identity.application.academy_media import (
    MAX_PHOTO_UPLOAD_BYTES,
    MAX_UPLOAD_BYTES,
    LogoRejected,
    LogoTooLarge,
    UploadAcademyLogo,
)
from backend.v2.contexts.identity.infrastructure.logo_image import process_logo_image
from backend.v2.contexts.identity.infrastructure.photo_image import (
    MAX_SOURCE_DIMENSION,
    process_photo_image,
)
from backend.v2.tests.fixtures.fake_media_store import FakeMediaRepo, FakeMediaStore

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _img(size=(3000, 1500), fmt="JPEG", mode="RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, (10, 120, 200)[: len(mode)]).save(buf, format=fmt)
    return buf.getvalue()


def _make(*, with_photo: bool = True):
    store, repo = FakeMediaStore(), FakeMediaRepo()
    uc = UploadAcademyLogo(
        store=store,
        media_repo=repo,
        process_image=process_logo_image,
        process_photo=process_photo_image if with_photo else None,
        now=lambda: NOW,
    )
    return uc, store, repo


@pytest.mark.asyncio
@pytest.mark.parametrize(("purpose", "edge"), [("hero", 2400), ("gallery", 2400), ("coach", 800)])
async def test_photo_is_reencoded_to_jpeg_under_its_own_path(purpose: str, edge: int) -> None:
    uc, store, repo = _make()

    out = await uc.execute(
        academy_id="acad_x", uploaded_by="u1", raw=_img(), purpose=purpose, consent=True
    )

    (path,) = store.objects
    assert re.fullmatch(rf"academies/acad_x/{purpose}/[0-9a-f]{{32}}\.jpg", path)
    obj = store.objects[path]
    assert obj["content_type"] == "image/jpeg"
    stored = Image.open(io.BytesIO(obj["data"]))  # type: ignore[arg-type]
    assert stored.format == "JPEG"
    assert max(stored.size) == edge
    assert out.url == out.logo_url and out.purpose == purpose
    assert repo.rows[0]["kind"] == purpose and repo.rows[0]["status"] == "stored"


@pytest.mark.asyncio
async def test_photo_metadata_is_stripped() -> None:
    exif = Image.Exif()
    exif[0x010F] = "SecretCamera"  # Make
    exif[0x8825] = {1: "N", 2: (29.0, 45.0, 0.0)}  # GPS block
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), (1, 2, 3)).save(buf, format="JPEG", exif=exif)
    assert b"SecretCamera" in buf.getvalue()
    uc, store, _ = _make()

    await uc.execute(academy_id="a", uploaded_by="u", raw=buf.getvalue(), purpose="hero")

    (obj,) = store.objects.values()
    data: bytes = obj["data"]  # type: ignore[assignment]
    assert b"SecretCamera" not in data
    assert not Image.open(io.BytesIO(data)).getexif()


@pytest.mark.asyncio
async def test_gallery_without_consent_is_refused_before_anything_happens() -> None:
    uc, store, repo = _make()

    with pytest.raises(LogoRejected, match="parents or guardians"):
        await uc.execute(academy_id="a", uploaded_by="u", raw=_img(), purpose="gallery")

    assert not store.objects and not repo.rows


@pytest.mark.asyncio
async def test_hero_and_coach_do_not_need_consent() -> None:
    uc, store, _ = _make()
    await uc.execute(academy_id="a", uploaded_by="u", raw=_img(), purpose="hero")
    await uc.execute(academy_id="a", uploaded_by="u", raw=_img(), purpose="coach")
    assert len(store.objects) == 2


@pytest.mark.asyncio
async def test_photo_limit_is_5_mb_but_the_logo_stays_2_mb() -> None:
    uc, store, _ = _make()
    big = b"\x00" * (MAX_UPLOAD_BYTES + 1)

    with pytest.raises(LogoTooLarge, match="over 2 MB"):
        await uc.execute(academy_id="a", uploaded_by="u", raw=big)  # default = logo
    with pytest.raises(LogoRejected):  # under the photo cap: reaches the decoder
        await uc.execute(academy_id="a", uploaded_by="u", raw=big, purpose="hero")
    with pytest.raises(LogoTooLarge, match="over 5 MB"):
        await uc.execute(
            academy_id="a",
            uploaded_by="u",
            raw=b"\x00" * (MAX_PHOTO_UPLOAD_BYTES + 1),
            purpose="hero",
        )
    assert not store.objects


@pytest.mark.asyncio
async def test_unknown_purpose_is_rejected() -> None:
    uc, store, _ = _make()
    with pytest.raises(LogoRejected):
        await uc.execute(academy_id="a", uploaded_by="u", raw=_img(), purpose="banner")
    assert not store.objects


@pytest.mark.asyncio
async def test_logo_is_unchanged_by_the_new_pipeline() -> None:
    uc, store, _ = _make()
    await uc.execute(academy_id="acad_x", uploaded_by="u", raw=_img((80, 80), "PNG"))
    (path,) = store.objects
    assert re.fullmatch(r"academies/acad_x/logo/[0-9a-f]{32}\.png", path)
    assert store.objects[path]["content_type"] == "image/png"


def test_photo_processor_rejects_oversized_canvas_and_bad_files() -> None:
    with pytest.raises(LogoRejected, match="too large"):
        process_photo_image(_img((MAX_SOURCE_DIMENSION + 1, 10), "PNG"), 2400)
    with pytest.raises(LogoRejected, match="too large"):
        process_photo_image(_img((7000, 6000), "PNG"), 2400)  # 42 MP > cap
    with pytest.raises(LogoRejected, match="not a PNG or JPG"):
        process_photo_image(b"<html>nope</html>", 800)
    with pytest.raises(LogoRejected, match="empty"):
        process_photo_image(b"", 800)
    gif = io.BytesIO()
    Image.new("RGB", (8, 8)).save(gif, format="GIF")
    with pytest.raises(LogoRejected):
        process_photo_image(gif.getvalue(), 800)


def test_photo_processor_flattens_transparency_and_never_upscales() -> None:
    out = process_photo_image(_img((100, 60), "PNG", "RGBA"), 2400)
    assert (out.width, out.height) == (100, 60)
    assert out.content_type == "image/jpeg"


def test_a_huge_png_is_refused_but_the_same_canvas_as_jpeg_is_allowed() -> None:
    """PNG is fully decoded (no draft), so it has a lower pixel cap than JPEG."""
    import io

    from PIL import Image

    from backend.v2.contexts.identity.application.academy_media import LogoRejected
    from backend.v2.contexts.identity.infrastructure.photo_image import (
        MAX_PNG_PIXELS,
        process_photo_image,
    )

    side = int(MAX_PNG_PIXELS**0.5) + 50
    canvas = Image.new("L", (side, side), 128)
    png = io.BytesIO()
    canvas.save(png, format="PNG")
    with pytest.raises(LogoRejected, match="PNG is too large"):
        process_photo_image(png.getvalue(), 800)
    jpeg = io.BytesIO()
    canvas.save(jpeg, format="JPEG")
    assert process_photo_image(jpeg.getvalue(), 800).width <= 800
