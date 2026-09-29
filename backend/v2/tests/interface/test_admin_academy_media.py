"""POST /admin/academy/media contract."""

from __future__ import annotations

import io

from PIL import Image

from backend.v2.contexts.identity.application.academy_media import UploadAcademyLogo
from backend.v2.contexts.identity.infrastructure.logo_image import process_logo_image
from backend.v2.tests.fixtures.fake_media_store import FakeMediaRepo, FakeMediaStore

URL = "/api/v2/admin/academy/media"


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (60, 60), (0, 90, 200)).save(buf, format="PNG")
    return buf.getvalue()


def _wire(client, **store_kwargs):
    store = FakeMediaStore(**store_kwargs)
    repo = FakeMediaRepo()
    client.use_cases.upload_academy_logo = UploadAcademyLogo(
        store=store, media_repo=repo, process_image=process_logo_image
    )
    return store, repo


def _post(client, data: bytes, name="logo.png", ctype="image/png", **form):
    return client.post(URL, files={"file": (name, data, ctype)}, data=form)


def test_uploads_and_returns_logo_url(admin_client):
    store, repo = _wire(admin_client)

    r = _post(admin_client, _png())

    assert r.status_code == 200, r.text
    (path,) = store.objects
    assert path.startswith("academies/acad/logo/")
    assert r.json()["logo_url"].startswith("https://firebasestorage.googleapis.com/v0/b/")
    assert repo.rows[0]["uploaded_by"] == "u-admin"
    # single writer: the route never touches academies.logo_url
    admin_client.use_cases.update_academy_use_case.execute.assert_not_awaited()


def test_plain_admin_without_owner_can_upload(admin_only_client):
    _wire(admin_only_client)
    assert _post(admin_only_client, _png()).status_code == 200


def test_academy_comes_from_claims_not_the_request(admin_client):
    store, _ = _wire(admin_client)

    r = _post(admin_client, _png(), academy_id="acad_other")

    assert r.status_code == 200, r.text
    (path,) = store.objects
    assert path.startswith("academies/acad/logo/")
    assert "acad_other" not in path


def test_coach_and_parent_cannot_upload(coach_on_admin_client, parent_on_admin_client):
    # Admin routes answer non-admin personas with 404 by design. The gate
    # fires before the 503 for "storage not configured" could.
    for client in (coach_on_admin_client, parent_on_admin_client):
        assert _post(client, _png()).status_code == 404


def test_503_when_storage_not_configured(admin_client):
    admin_client.use_cases.upload_academy_logo = None
    r = _post(admin_client, _png())
    assert r.status_code == 503
    assert "Paste a link" in r.json()["detail"]


def test_oversize_body_is_refused_413(admin_client):
    store, _ = _wire(admin_client)
    r = _post(admin_client, b"\x00" * (2 * 1024 * 1024 + 100 * 1024))
    assert r.status_code == 413
    assert not store.objects


def test_file_just_over_2mb_is_413_by_the_use_case(admin_client):
    store, _ = _wire(admin_client)
    r = _post(admin_client, b"\x00" * (2 * 1024 * 1024 + 1))
    assert r.status_code == 413
    assert not store.objects


def test_html_disguised_as_png_is_422(admin_client):
    store, _ = _wire(admin_client)
    r = _post(admin_client, b"<html><script>alert(1)</script></html>", name="logo.png")
    assert r.status_code == 422
    assert not store.objects


def test_gif_bytes_with_png_content_type_is_422(admin_client):
    store, _ = _wire(admin_client)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="GIF")
    assert _post(admin_client, buf.getvalue(), name="a.png", ctype="image/png").status_code == 422
    assert not store.objects


def test_missing_file_field_is_422(admin_client):
    _wire(admin_client)
    r = admin_client.post(URL, files={"other": ("a.png", _png(), "image/png")})
    assert r.status_code == 422


def test_storage_outage_is_502(admin_client):
    _wire(admin_client, fail=True)
    r = _post(admin_client, _png())
    assert r.status_code == 502


def test_patch_logo_url_must_be_https(admin_client):
    for bad in (
        "http://cdn.example.com/a.png",
        "javascript:alert(1)",
        "//cdn.example.com/a.png",
        "not a url",
    ):
        r = admin_client.patch("/api/v2/admin/academy", json={"logo_url": bad})
        assert r.status_code == 422, bad
    admin_client.use_cases.update_academy_use_case.execute.assert_not_awaited()


def test_chunked_framing_is_refused_before_reading(admin_client):
    """A tiny Content-Length next to chunked framing must not bound nothing."""
    store, _ = _wire(admin_client)
    r = admin_client.post(
        URL,
        content=b"x" * 10,
        headers={"content-type": "multipart/form-data; boundary=b", "transfer-encoding": "chunked"},
    )
    assert r.status_code == 411
    assert not store.objects


def test_body_is_cut_off_on_the_wire_past_the_limit(admin_client):
    """Whatever Content-Length claims, a body streamed past the limit is 413."""
    store, _ = _wire(admin_client)

    def chunks():
        for _ in range(40):
            yield b"\x00" * (64 * 1024)

    r = admin_client.post(
        URL,
        content=chunks(),
        headers={"content-type": "multipart/form-data; boundary=b", "content-length": "100"},
    )
    assert r.status_code in (411, 413)
    assert not store.objects
