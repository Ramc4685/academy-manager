"""Safe logo re-encoding (Pillow).

Never trusts the filename or client Content-Type: the format is what Pillow
detects, restricted to PNG and JPEG. The output is always a fresh PNG built
from raw pixels, so EXIF, ICC profiles and text chunks cannot survive.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps

from backend.v2.contexts.identity.application.academy_media import LogoRejected, ProcessedImage

#: Largest accepted source width/height. Checked from the header, before any
#: pixel is decoded, so a small file declaring a huge canvas is refused cheaply.
MAX_SOURCE_DIMENSION = 2048
#: Longest side of the stored logo.
MAX_OUTPUT_DIMENSION = 512

_TOO_LARGE = (
    f"That image is too large. Use one up to {MAX_SOURCE_DIMENSION} x "
    f"{MAX_SOURCE_DIMENSION} pixels."
)
_BAD_IMAGE = "That file is not a PNG or JPG image. Choose a PNG or JPG."


def process_logo_image(raw: bytes) -> ProcessedImage:
    try:
        return _process(raw)
    except LogoRejected:
        raise
    except Image.DecompressionBombError:
        # Pillow refuses absurd canvases while opening, before our own check.
        raise LogoRejected(_TOO_LARGE) from None
    except (OSError, ValueError, SyntaxError, EOFError):
        # UnidentifiedImageError is an OSError; truncated or corrupt data too.
        raise LogoRejected(_BAD_IMAGE) from None


def _process(raw: bytes) -> ProcessedImage:
    if not raw:
        raise LogoRejected("That file is empty. Choose a PNG or JPG.")
    with Image.open(io.BytesIO(raw), formats=["PNG", "JPEG"]) as opened:
        width, height = opened.size
        if width < 1 or height < 1:
            raise LogoRejected(_BAD_IMAGE)
        if width > MAX_SOURCE_DIMENSION or height > MAX_SOURCE_DIMENSION:
            raise LogoRejected(_TOO_LARGE)
        if opened.format == "JPEG":
            # Let the decoder downscale while reading (the output is 512 px).
            opened.draft("RGB", (MAX_OUTPUT_DIMENSION * 2, MAX_OUTPUT_DIMENSION * 2))
        opened.load()
        oriented = ImageOps.exif_transpose(opened)
        has_alpha = oriented.mode in ("RGBA", "LA", "PA") or "transparency" in oriented.info
        image = oriented.convert("RGBA" if has_alpha else "RGB")
    image.thumbnail((MAX_OUTPUT_DIMENSION, MAX_OUTPUT_DIMENSION), Image.Resampling.LANCZOS)
    # Drop every metadata channel (EXIF, ICC, text chunks); PNG save writes
    # only what is in ``info``/``pnginfo``, and both are empty.
    image.info.clear()
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return ProcessedImage(data=out.getvalue(), width=image.width, height=image.height)
