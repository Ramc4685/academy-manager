"""POST /admin/academy/media contract."""

from __future__ import annotations

import io

from PIL import Image

from backend.v2.contexts.identity.application.academy_media import UploadAcademyLogo
from backend.v2.contexts.identity.infrastructure.logo_image import process_logo_image
from backend.v2.contexts.identity.infrastructure.photo_image import process_photo_image
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
        store=store,
        media_repo=repo,
        process_image=process_logo_image,
        process_photo=process_photo_image,
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
        for _ in range(100):  # 6.4 MB, past the 5 MB photo cap
            yield b"\x00" * (64 * 1024)

    r = admin_client.post(
        URL,
        content=chunks(),
        headers={"content-type": "multipart/form-data; boundary=b", "content-length": "100"},
    )
    assert r.status_code in (411, 413)
    assert not store.objects


# --- landing-page photo purposes -------------------------------------------


def _jpeg(size=(1600, 900)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, format="JPEG")
    return buf.getvalue()


def test_default_purpose_is_logo_and_response_keeps_logo_url(admin_client):
    _wire(admin_client)
    body = _post(admin_client, _png()).json()
    assert body["purpose"] == "logo"
    assert body["logo_url"] == body["url"]


def test_hero_photo_upload_stores_a_jpeg_under_the_hero_path(admin_client):
    store, repo = _wire(admin_client)

    r = _post(admin_client, _jpeg(), name="court.jpg", ctype="image/jpeg", purpose="hero")

    assert r.status_code == 200, r.text
    (path,) = store.objects
    assert path.startswith("academies/acad/hero/") and path.endswith(".jpg")
    assert r.json()["url"].startswith("https://firebasestorage.googleapis.com/")
    assert r.json()["logo_url"] is None and r.json()["purpose"] == "hero"
    assert repo.rows[0]["kind"] == "hero"


def test_plain_admin_can_upload_photos(admin_only_client):
    _wire(admin_only_client)
    for purpose, extra in (("hero", {}), ("coach", {}), ("gallery", {"consent": "true"})):
        r = _post(
            admin_only_client, _jpeg(), name="a.jpg", ctype="image/jpeg", purpose=purpose, **extra
        )
        assert r.status_code == 200, (purpose, r.text)


def test_gallery_without_consent_is_422_with_a_clear_message(admin_client):
    store, repo = _wire(admin_client)
    for form in ({"purpose": "gallery"}, {"purpose": "gallery", "consent": "false"}):
        r = _post(admin_client, _jpeg(), name="a.jpg", ctype="image/jpeg", **form)
        assert r.status_code == 422
        assert "parents or guardians" in r.json()["detail"]
    assert not store.objects and not repo.rows


def test_unknown_purpose_is_422(admin_client):
    store, _ = _wire(admin_client)
    assert _post(admin_client, _png(), purpose="banner").status_code == 422
    assert not store.objects


def test_photo_can_be_up_to_5_mb_and_logo_stays_2_mb(admin_client):
    store, _ = _wire(admin_client)
    over_logo = b"\x00" * (2 * 1024 * 1024 + 1)

    r = _post(admin_client, over_logo)
    assert r.status_code == 413 and "2 MB" in r.json()["detail"]
    # Same size as a hero is not a size problem (it is junk bytes: 422).
    assert _post(admin_client, over_logo, purpose="hero").status_code == 422
    r = _post(admin_client, b"\x00" * (5 * 1024 * 1024 + 1), purpose="hero")
    assert r.status_code == 413 and "5 MB" in r.json()["detail"]
    assert not store.objects


def test_photo_academy_and_path_come_from_claims(admin_client):
    store, _ = _wire(admin_client)
    _post(
        admin_client,
        _jpeg(),
        name="a.jpg",
        ctype="image/jpeg",
        purpose="coach",
        academy_id="acad_other",
    )
    (path,) = store.objects
    assert path.startswith("academies/acad/coach/") and "acad_other" not in path
