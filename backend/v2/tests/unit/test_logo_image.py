"""Logo re-encoding: format sniffing, size guards, metadata stripping."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from backend.v2.contexts.identity.application.academy_media import LogoRejected
from backend.v2.contexts.identity.infrastructure.logo_image import (
    MAX_OUTPUT_DIMENSION,
    process_logo_image,
)


def _png(size=(64, 32), mode="RGB", **save_kwargs) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, (200, 30, 30) if mode == "RGB" else (200, 30, 30, 128)).save(
        buf, format="PNG", **save_kwargs
    )
    return buf.getvalue()


def _jpeg(size=(64, 32), **save_kwargs) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 120, 200)).save(buf, format="JPEG", **save_kwargs)
    return buf.getvalue()


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def test_png_in_png_out() -> None:
    out = process_logo_image(_png())
    assert out.content_type == "image/png"
    assert _open(out.data).format == "PNG"
    assert (out.width, out.height) == (64, 32)


def test_jpeg_becomes_png() -> None:
    out = process_logo_image(_jpeg())
    assert _open(out.data).format == "PNG"


def test_transparency_is_kept() -> None:
    out = process_logo_image(_png(mode="RGBA"))
    img = _open(out.data)
    assert img.mode == "RGBA"
    assert img.getpixel((0, 0))[3] == 128


def test_large_image_is_downscaled_keeping_aspect() -> None:
    out = process_logo_image(_png(size=(2000, 1000)))
    assert max(out.width, out.height) == MAX_OUTPUT_DIMENSION
    assert out.height * 2 == out.width


def test_small_image_is_not_upscaled() -> None:
    out = process_logo_image(_png(size=(10, 10)))
    assert (out.width, out.height) == (10, 10)


def test_exif_is_stripped_and_orientation_applied() -> None:
    exif = Image.Exif()
    exif[0x010F] = "SecretCamera"  # Make
    exif[0x0112] = 6  # rotate 90 CW to display
    exif[0x8825] = {1: "N"}  # GPS IFD present
    data = _jpeg(size=(80, 40), exif=exif.tobytes())
    assert len(_open(data).getexif()) > 0  # precondition: input has EXIF
    out = process_logo_image(data)
    result = _open(out.data)
    assert len(result.getexif()) == 0
    assert b"SecretCamera" not in out.data
    assert b"Exif" not in out.data
    assert (out.width, out.height) == (40, 80)  # orientation applied first


def test_png_text_and_icc_chunks_are_stripped() -> None:
    from PIL import PngImagePlugin

    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "Someone Private")
    data = _png(pnginfo=info, icc_profile=b"\x00" * 128)
    assert b"Someone Private" in data
    out = process_logo_image(data)
    assert b"Someone Private" not in out.data
    assert b"iCCP" not in out.data
    assert _open(out.data).info.get("icc_profile") is None


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"not an image at all",
        b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
        b"<html><script>alert(1)</script></html>",
        b"GIF89a" + b"\x00" * 40,
        b"%PDF-1.7\n" + b"\x00" * 40,
    ],
)
def test_garbage_and_wrong_formats_are_rejected(payload: bytes) -> None:
    with pytest.raises(LogoRejected):
        process_logo_image(payload)


def test_gif_and_webp_disguised_as_png_are_rejected() -> None:
    for fmt in ("GIF", "WEBP", "BMP"):
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, format=fmt)
        with pytest.raises(LogoRejected):
            process_logo_image(buf.getvalue())


def test_truncated_png_is_rejected() -> None:
    data = _png(size=(200, 200))
    with pytest.raises(LogoRejected):
        process_logo_image(data[: len(data) // 2])


def test_png_with_trailing_junk_still_reencodes_cleanly() -> None:
    out = process_logo_image(_png() + b"<script>alert(1)</script>")
    assert b"<script>" not in out.data


def test_decompression_bomb_is_rejected_from_the_header() -> None:
    # A tiny file that declares a 30000 x 30000 canvas: refused before decode.
    buf = io.BytesIO()
    Image.new("1", (30000, 30000), 0).save(buf, format="PNG", optimize=True)
    data = buf.getvalue()
    assert len(data) < 200_000  # small on the wire, huge when decoded
    with pytest.raises(LogoRejected) as exc:
        process_logo_image(data)
    assert "too large" in str(exc.value)


def test_pixel_cap_boundary() -> None:
    process_logo_image(_png(size=(2048, 1)))
    with pytest.raises(LogoRejected):
        process_logo_image(_png(size=(2049, 1)))


def test_sixteen_bit_greyscale_is_scaled_not_saturated() -> None:
    buf = io.BytesIO()
    Image.new("I;16", (32, 32), 32768).save(buf, format="PNG")
    out = _open(process_logo_image(buf.getvalue()).data).convert("RGB")
    red, green, blue = out.getpixel((5, 5))
    assert 100 < red < 160 and red == green == blue
