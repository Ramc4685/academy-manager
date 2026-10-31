"""Safe landing-page photo re-encoding (Pillow): hero, gallery, coach.

Same trust model as ``logo_image``: the format is what Pillow detects
(PNG or JPEG only, never the filename or client Content-Type) and the output
is a fresh JPEG built from raw pixels, so EXIF (including GPS), ICC profiles
and text chunks cannot survive. Phone photos are large, so the source caps
are higher than a logo's, but still checked from the header before any pixel
is decoded: a per-side limit and a total-pixel limit bound peak memory.
JPEG sources are downscaled by the decoder itself while reading.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps

from backend.v2.contexts.identity.application.academy_media import LogoRejected, ProcessedImage

#: Largest accepted source width/height (from the header).
MAX_SOURCE_DIMENSION = 8000
#: Largest accepted source canvas (width x height), about 30 megapixels.
MAX_SOURCE_PIXELS = 30_000_000
#: PNG has no decoder-side downscale: it is fully decoded, then copied a few
#: times, so it gets a lower canvas cap (about 16 megapixels, ~64 MB per RGBA
#: copy) than JPEG. Phone photos are JPEG; a PNG this big is a screenshot or
#: an export.
MAX_PNG_PIXELS = 16_000_000
#: JPEG quality of the stored photo.
JPEG_QUALITY = 85

_TOO_LARGE = (
    f"That image is too large. Use one up to {MAX_SOURCE_DIMENSION} pixels on a side "
    "and about 30 megapixels."
)
_PNG_TOO_LARGE = "That PNG is too large. Use one up to about 16 megapixels, or save it as a JPG."
_BAD_IMAGE = "That file is not a PNG or JPG image. Choose a PNG or JPG."


def process_photo_image(raw: bytes, max_edge: int) -> ProcessedImage:
    try:
        return _process(raw, max_edge)
    except LogoRejected:
        raise
    except Image.DecompressionBombError:
        raise LogoRejected(_TOO_LARGE) from None
    except (OSError, ValueError, SyntaxError, EOFError):
        raise LogoRejected(_BAD_IMAGE) from None


def _process(raw: bytes, max_edge: int) -> ProcessedImage:
    if not raw:
        raise LogoRejected("That file is empty. Choose a PNG or JPG.")
    with Image.open(io.BytesIO(raw), formats=["PNG", "JPEG"]) as opened:
        width, height = opened.size
        if width < 1 or height < 1:
            raise LogoRejected(_BAD_IMAGE)
        if (
            width > MAX_SOURCE_DIMENSION
            or height > MAX_SOURCE_DIMENSION
            or width * height > MAX_SOURCE_PIXELS
        ):
            raise LogoRejected(_TOO_LARGE)
        if opened.format == "PNG" and width * height > MAX_PNG_PIXELS:
            raise LogoRejected(_PNG_TOO_LARGE)
        if opened.format == "JPEG":
            # Decode at a reduced scale (never below the target size).
            opened.draft("RGB", (max_edge, max_edge))
        opened.load()
        oriented = ImageOps.exif_transpose(opened)
        if oriented.mode in ("I;16", "I;16B", "I;16L", "I"):
            oriented = oriented.point(lambda value: value / 256).convert("L")
        has_alpha = oriented.mode in ("RGBA", "LA", "PA") or "transparency" in oriented.info
        if has_alpha:
            rgba = oriented.convert("RGBA")
            image = Image.new("RGB", rgba.size, (255, 255, 255))
            image.paste(rgba, mask=rgba.getchannel("A"))
        else:
            image = oriented.convert("RGB")
    image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    image.info.clear()
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return ProcessedImage(
        data=out.getvalue(), width=image.width, height=image.height, content_type="image/jpeg"
    )
