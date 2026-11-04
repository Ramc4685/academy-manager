"""UploadAcademyLogo use case against the fake store."""

from __future__ import annotations

import asyncio
import hashlib
import io
import re
from datetime import UTC, datetime

import pytest
from PIL import Image

from backend.v2.contexts.identity.application.academy_media import (
    MAX_UPLOAD_BYTES,
    MAX_UPLOADS_PER_HOUR,
    LogoRateLimited,
    LogoRejected,
    LogoTooLarge,
    MediaStorageUnavailable,
    UploadAcademyLogo,
)
from backend.v2.contexts.identity.infrastructure.logo_image import process_logo_image
from backend.v2.tests.fixtures.fake_media_store import FakeMediaRepo, FakeMediaStore

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (5, 5, 5)).save(buf, format="PNG")
    return buf.getvalue()


def _make(store=None, repo=None) -> tuple[UploadAcademyLogo, FakeMediaStore, FakeMediaRepo]:
    store = store or FakeMediaStore()
    repo = repo or FakeMediaRepo()
    return (
        UploadAcademyLogo(
            store=store, media_repo=repo, process_image=process_logo_image, now=lambda: NOW
        ),
        store,
        repo,
    )


@pytest.mark.asyncio
async def test_stores_png_under_the_academys_path_and_returns_a_token_url() -> None:
    uc, store, repo = _make()

    out = await uc.execute(academy_id="acad_x", uploaded_by="u1", raw=_png())

    (path,) = store.objects
    assert re.fullmatch(r"academies/acad_x/logo/[0-9a-f]{32}\.png", path)
    obj = store.objects[path]
    assert obj["content_type"] == "image/png"
    assert Image.open(io.BytesIO(obj["data"])).format == "PNG"  # type: ignore[arg-type]
    assert out.logo_url.startswith("https://firebasestorage.googleapis.com/v0/b/test-bucket/o/")
    assert "academies%2Facad_x%2Flogo%2F" in out.logo_url
    assert f"alt=media&token={obj['token']}" in out.logo_url
    (row,) = repo.rows
    assert row["status"] == "stored"
    assert row["object_path"] == path
    assert row["uploaded_by"] == "u1"
    assert row["sha256"] == hashlib.sha256(obj["data"]).hexdigest()  # type: ignore[arg-type]
    assert row["size_bytes"] == len(obj["data"])  # type: ignore[arg-type]
    assert row["created_at"] == NOW


@pytest.mark.asyncio
async def test_each_upload_gets_a_new_object_and_old_ones_stay() -> None:
    uc, store, _ = _make()
    a = await uc.execute(academy_id="acad_x", uploaded_by="u1", raw=_png())
    b = await uc.execute(academy_id="acad_x", uploaded_by="u1", raw=_png())
    assert a.logo_url != b.logo_url
    assert len(store.objects) == 2


@pytest.mark.asyncio
async def test_oversize_is_refused_before_any_work() -> None:
    uc, store, repo = _make()
    with pytest.raises(LogoTooLarge):
        await uc.execute(academy_id="a", uploaded_by="u", raw=b"\x00" * (MAX_UPLOAD_BYTES + 1))
    assert not store.objects and not repo.rows


@pytest.mark.asyncio
async def test_rejected_image_stores_nothing() -> None:
    uc, store, repo = _make()
    with pytest.raises(LogoRejected):
        await uc.execute(academy_id="a", uploaded_by="u", raw=b"GIF89a....")
    assert not store.objects
    # Rejected attempts are recorded, so they count toward the hourly cap.
    assert [r["status"] for r in repo.rows] == ["rejected"]


@pytest.mark.asyncio
async def test_rate_limit() -> None:
    uc, store, repo = _make(repo=FakeMediaRepo(existing_recent=MAX_UPLOADS_PER_HOUR))
    with pytest.raises(LogoRateLimited):
        await uc.execute(academy_id="a", uploaded_by="u", raw=_png())
    assert not store.objects
    assert [r["status"] for r in repo.rows] == ["rate_limited"]


@pytest.mark.asyncio
async def test_repeated_garbage_uploads_hit_the_cap() -> None:
    uc, _, _ = _make()
    for _ in range(MAX_UPLOADS_PER_HOUR):
        with pytest.raises(LogoRejected):
            await uc.execute(academy_id="a", uploaded_by="u", raw=b"nope")
    with pytest.raises(LogoRateLimited):
        await uc.execute(academy_id="a", uploaded_by="u", raw=b"nope")


@pytest.mark.asyncio
async def test_processing_runs_off_the_event_loop_thread() -> None:
    import threading

    seen: list[int] = []

    def proc(raw: bytes):
        seen.append(threading.get_ident())
        return process_logo_image(raw)

    uc = UploadAcademyLogo(
        store=FakeMediaStore(), media_repo=FakeMediaRepo(), process_image=proc, now=lambda: NOW
    )
    await uc.execute(academy_id="a", uploaded_by="u", raw=_png())
    assert seen and seen[0] != threading.get_ident()


@pytest.mark.asyncio
async def test_storage_failure_marks_the_attempt_failed() -> None:
    uc, _, repo = _make(store=FakeMediaStore(fail=True))
    with pytest.raises(MediaStorageUnavailable):
        await uc.execute(academy_id="a", uploaded_by="u", raw=_png())
    assert [r["status"] for r in repo.rows] == ["failed"]
    assert "object_path" not in repo.rows[0]


@pytest.mark.asyncio
async def test_fake_store_refuses_overwrite_like_the_real_adapter() -> None:
    store = FakeMediaStore()
    await store.put_public(path="p", data=b"1", content_type="image/png")
    with pytest.raises(MediaStorageUnavailable):
        await store.put_public(path="p", data=b"2", content_type="image/png")


@pytest.mark.asyncio
async def test_cancelled_processing_marks_the_attempt_failed() -> None:
    """A client that disconnects mid-decode must not leave a 'pending' row."""

    def cancel(_raw: bytes):
        raise asyncio.CancelledError

    repo = FakeMediaRepo()
    uc = UploadAcademyLogo(
        store=FakeMediaStore(), media_repo=repo, process_image=cancel, now=lambda: NOW
    )
    with pytest.raises(asyncio.CancelledError):
        await uc.execute(academy_id="a", uploaded_by="u", raw=_png())
    assert [r["status"] for r in repo.rows] == ["failed"]
