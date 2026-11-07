"""Bounded, memory-only artwork conversion using Pillow 12.0.0.

Only the first frame is decoded. EXIF orientation is applied before fitting;
metadata is not copied to the output JPEG. No artwork or placeholder files are
written, and no source data is logged. Keep processing on the caller's worker.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
from io import BytesIO
import warnings

from PIL import Image, ImageOps


MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_DECODED_PIXELS = 16_000_000
MAX_OUTPUT_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class ArtworkResult:
    status: str
    jpeg: bytes | None = field(default=None, repr=False)
    width: int | None = None
    height: int | None = None
    detail: str = ""


def _limit(name: str, value: int, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


class ArtworkProcessor:
    """Make a 128px or 160px square JPEG, cropping (default) or padding.

    ``background`` is an RGB tuple used for both alpha compositing and padding.
    Tiny inputs may be upscaled only to the fixed bounded output size. Pixel
    limits are checked before load/transpose/resize. Pillow bomb warnings/errors
    become too_large results without changing Pillow's global decoder settings.
    """

    def __init__(
        self, size: int = 160, *, fit: str = "crop",
        background: tuple[int, int, int] = (0, 0, 0), quality: int = 85,
        max_input_bytes: int = MAX_INPUT_BYTES,
        max_pixels: int = MAX_DECODED_PIXELS,
        max_output_bytes: int = MAX_OUTPUT_BYTES,
    ) -> None:
        if type(size) is not int or size not in (128, 160):
            raise ValueError("size must be 128 or 160")
        if fit not in ("crop", "pad"):
            raise ValueError("fit must be crop or pad")
        if (not isinstance(background, tuple) or len(background) != 3
                or any(type(value) is not int or not 0 <= value <= 255 for value in background)):
            raise ValueError("background must be an RGB tuple")
        self.size, self.fit, self.background = size, fit, background
        self.quality = _limit("quality", quality, 95)
        self.max_input_bytes = _limit("max_input_bytes", max_input_bytes, MAX_INPUT_BYTES)
        self.max_pixels = _limit("max_pixels", max_pixels, MAX_DECODED_PIXELS)
        self.max_output_bytes = _limit("max_output_bytes", max_output_bytes, MAX_OUTPUT_BYTES)

    def process(self, data: bytes | None) -> ArtworkResult:
        if data is None or data == b"":
            return ArtworkResult("missing", detail="No artwork was supplied.")
        if not isinstance(data, bytes):
            return ArtworkResult("invalid", detail="Artwork must be bytes.")
        if len(data) > self.max_input_bytes:
            return ArtworkResult("too_large", detail="Artwork input exceeds the byte limit.")
        try:
            with warnings.catch_warnings(), ExitStack() as images:
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                stream = images.enter_context(BytesIO(data))
                image = images.enter_context(Image.open(stream))
                image.seek(0)
                width, height = image.size
                if width <= 0 or height <= 0:
                    return ArtworkResult("invalid", detail="Artwork has invalid dimensions.")
                if width * height > self.max_pixels:
                    return ArtworkResult("too_large", detail="Artwork exceeds the decoded pixel limit.")
                image.load()
                oriented = ImageOps.exif_transpose(image)
                images.callback(oriented.close)
                if oriented.mode in ("RGBA", "LA") or "transparency" in oriented.info:
                    rgba = oriented.convert("RGBA")
                    images.callback(rgba.close)
                    rgb = Image.new("RGB", oriented.size, self.background)
                    images.callback(rgb.close)
                    alpha = rgba.getchannel("A")
                    images.callback(alpha.close)
                    rgb.paste(rgba, mask=alpha)
                else:
                    rgb = oriented.convert("RGB")
                    images.callback(rgb.close)
                target = (self.size, self.size)
                if self.fit == "crop":
                    square = ImageOps.fit(rgb, target, method=Image.Resampling.LANCZOS)
                else:
                    square = ImageOps.pad(rgb, target, method=Image.Resampling.LANCZOS,
                                          color=self.background)
                images.callback(square.close)
                with BytesIO() as output:
                    square.save(output, format="JPEG", quality=self.quality, optimize=True)
                    if output.tell() > self.max_output_bytes:
                        return ArtworkResult("too_large", detail="JPEG exceeds the output byte limit.")
                    jpeg = output.getvalue()
            return ArtworkResult("ok", jpeg, self.size, self.size, "Artwork converted to RGB JPEG.")
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            return ArtworkResult("too_large", detail="Pillow rejected an image decompression bomb.")
        except Exception:
            # Third-party image decoders can raise several exception families for
            # corrupt headers/EXIF. None should escape into playback controls.
            return ArtworkResult("invalid", detail="Artwork is unsupported, corrupt, or truncated.")
