"""Synthetic, memory-only artwork fixtures; no real artwork is stored."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from io import BytesIO

from PIL import Image, ImageFile
import pytest

from passport_companion.artwork import (
    MAX_DECODED_PIXELS, MAX_INPUT_BYTES, MAX_OUTPUT_BYTES,
    ArtworkProcessor, ArtworkResult,
)


def encode(image: Image.Image, format: str = "PNG", **options: object) -> bytes:
    with BytesIO() as output:
        image.save(output, format=format, **options)
        return output.getvalue()


def picture(size: tuple[int, int] = (64, 32), color: object = (25, 80, 135),
            mode: str = "RGB", **options: object) -> bytes:
    with Image.new(mode, size, color) as image:
        return encode(image, **options)


def decode(result: ArtworkResult) -> Image.Image:
    assert result.status == "ok" and result.jpeg is not None
    with Image.open(BytesIO(result.jpeg)) as image:
        assert image.format == "JPEG" and image.mode == "RGB"
        image.load()
        return image.copy()


def near(actual: tuple[int, ...], expected: tuple[int, ...], tolerance: int = 6) -> None:
    assert all(abs(left - right) <= tolerance for left, right in zip(actual, expected)), (actual, expected)


@pytest.mark.parametrize("size", [128, 160])
@pytest.mark.parametrize("fit", ["crop", "pad"])
def test_square_rgb_jpeg_dimensions_and_bounded_bytes(size: int, fit: str) -> None:
    result = ArtworkProcessor(size, fit=fit).process(picture())
    assert result.width == result.height == size
    assert result.jpeg.startswith(b"\xff\xd8") and len(result.jpeg) <= MAX_OUTPUT_BYTES
    with decode(result) as image:
        assert image.size == (size, size)
        near(image.getpixel((size // 2, size // 2)), (25, 80, 135))


def test_default_crop_is_centered() -> None:
    with Image.new("RGB", (320, 40), (230, 15, 15)) as image:
        image.paste((15, 30, 230), (140, 0, 180, 40))
        result = ArtworkProcessor().process(encode(image))
    with decode(result) as square:
        near(square.getpixel((10, 80)), (15, 30, 230))
        near(square.getpixel((150, 80)), (15, 30, 230))


def test_padding_preserves_aspect_and_uses_configured_background() -> None:
    result = ArtworkProcessor(128, fit="pad", background=(240, 240, 240)).process(picture())
    with decode(result) as image:
        near(image.getpixel((64, 5)), (240, 240, 240))
        near(image.getpixel((64, 64)), (25, 80, 135))
        near(image.getpixel((64, 122)), (240, 240, 240))


def test_exif_orientation_applies_before_fit_and_metadata_is_not_copied() -> None:
    with Image.new("RGB", (80, 40), (230, 20, 20)) as image:
        image.paste((20, 20, 230), (40, 0, 80, 40))
        exif = image.getexif()
        exif[274] = 6
        exif[315] = "Fictional Artwork Generator"
        data = encode(image, format="JPEG", exif=exif, quality=100, subsampling=0)
    result = ArtworkProcessor(fit="pad", background=(240, 240, 240)).process(data)
    with decode(result) as square:
        near(square.getpixel((80, 30)), (230, 20, 20))
        near(square.getpixel((80, 130)), (20, 20, 230))
        near(square.getpixel((5, 80)), (240, 240, 240))
    with Image.open(BytesIO(result.jpeg)) as encoded:
        assert 274 not in encoded.getexif() and 315 not in encoded.getexif()


@pytest.mark.parametrize("mode", ["RGBA", "LA"])
def test_alpha_is_composited_on_solid_background(mode: str) -> None:
    color = (220, 40, 60, 0) if mode == "RGBA" else (180, 0)
    data = picture((16, 16), color, mode)
    result = ArtworkProcessor(background=(50, 100, 150)).process(data)
    with decode(result) as image:
        near(image.getpixel((80, 80)), (50, 100, 150))


def test_partial_alpha_is_not_simply_discarded() -> None:
    data = picture((16, 16), (200, 100, 0, 128), "RGBA")
    result = ArtworkProcessor(background=(0, 0, 200)).process(data)
    with decode(result) as image:
        near(image.getpixel((80, 80)), (100, 50, 100))


def test_palette_transparency_is_composited() -> None:
    with Image.new("P", (32, 16), 0) as image:
        palette = [0, 0, 0, 20, 210, 40] + [0] * (768 - 6)
        image.putpalette(palette)
        image.paste(1, (16, 0, 32, 16))
        data = encode(image, transparency=0)
    result = ArtworkProcessor(background=(220, 230, 240)).process(data)
    with decode(result) as square:
        near(square.getpixel((20, 80)), (220, 230, 240))
        near(square.getpixel((140, 80)), (20, 210, 40))


def test_rgb_png_transparency_color_key_is_composited() -> None:
    data = picture((8, 8), (25, 80, 135), transparency=(25, 80, 135))
    result = ArtworkProcessor(background=(200, 210, 220)).process(data)
    with decode(result) as image:
        near(image.getpixel((80, 80)), (200, 210, 220))


@pytest.mark.parametrize(("mode", "color", "format"), [
    ("L", 120, "PNG"), ("CMYK", (0, 255, 255, 0), "JPEG"), ("1", 1, "PNG"),
])
def test_non_rgb_modes_are_supported(mode: str, color: object, format: str) -> None:
    result = ArtworkProcessor().process(picture((16, 16), color, mode, format=format))
    with decode(result) as image:
        assert image.mode == "RGB" and image.size == (160, 160)


def test_only_first_animation_frame_is_used() -> None:
    with Image.new("RGB", (16, 16), (220, 20, 20)) as first:
        with Image.new("RGB", (16, 16), (20, 20, 220)) as second:
            data = encode(first, format="GIF", save_all=True, append_images=[second], duration=100, loop=0)
    result = ArtworkProcessor().process(data)
    with decode(result) as image:
        near(image.getpixel((80, 80)), (220, 20, 20))


def test_smallest_input_upscales_only_to_fixed_output() -> None:
    result = ArtworkProcessor(128).process(picture((1, 1), (50, 75, 100)))
    with decode(result) as image:
        assert image.size == (128, 128)
        near(image.getpixel((64, 64)), (50, 75, 100))


@pytest.mark.parametrize("data", [None, b""])
def test_missing_artwork_has_no_placeholder_or_bytes(data: bytes | None) -> None:
    result = ArtworkProcessor().process(data)
    assert result.status == "missing"
    assert result.jpeg is None and result.width is None and result.height is None


@pytest.mark.parametrize("data", [b"fictional invalid image", b"\xff\xd8", b"\x89PNG\r\n\x1a\n", "wrong type", bytearray(b"abc")])
def test_invalid_artwork_falls_back_without_exception(data: object) -> None:
    result = ArtworkProcessor().process(data)  # type: ignore[arg-type]
    assert result.status == "invalid"
    assert result.jpeg is None and result.width is None and result.height is None


@pytest.mark.parametrize("format", ["PNG", "JPEG"])
def test_truncated_image_falls_back_without_exception(format: str) -> None:
    data = picture((64, 64), format=format)
    result = ArtworkProcessor().process(data[:len(data) // 2])
    assert result.status == "invalid" and result.jpeg is None


def test_oversized_input_is_rejected_before_decoder(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected(*args: object, **kwargs: object) -> None:
        raise AssertionError("Decoder must not run for oversized input")

    monkeypatch.setattr(Image, "open", unexpected)
    result = ArtworkProcessor(max_input_bytes=4).process(b"12345")
    assert result.status == "too_large" and result.jpeg is None


def test_input_byte_limit_boundary() -> None:
    data = picture()
    assert ArtworkProcessor(max_input_bytes=len(data)).process(data).status == "ok"
    assert ArtworkProcessor(max_input_bytes=len(data) - 1).process(data).status == "too_large"


def test_decoded_pixel_limit_is_checked_before_load(monkeypatch: pytest.MonkeyPatch) -> None:
    data = picture((11, 10))

    def unexpected(*args: object, **kwargs: object) -> None:
        raise AssertionError("Oversized image must not be decoded")

    monkeypatch.setattr(Image.Image, "load", unexpected)
    result = ArtworkProcessor(max_pixels=100).process(data)
    assert result.status == "too_large" and result.jpeg is None


def test_decoded_pixel_limit_boundary() -> None:
    data = picture((10, 10))
    assert ArtworkProcessor(max_pixels=100).process(data).status == "ok"
    assert ArtworkProcessor(max_pixels=99).process(data).status == "too_large"


@pytest.mark.parametrize("size", [(11, 10), (21, 10)])
def test_pillow_decompression_bomb_warnings_and_errors_are_too_large(
    monkeypatch: pytest.MonkeyPatch, size: tuple[int, int],
) -> None:
    data = picture(size)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    result = ArtworkProcessor().process(data)
    assert result.status == "too_large" and result.jpeg is None


def test_pillow_global_decoder_limits_are_not_modified() -> None:
    pixels, truncated = Image.MAX_IMAGE_PIXELS, ImageFile.LOAD_TRUNCATED_IMAGES
    ArtworkProcessor().process(picture())
    assert Image.MAX_IMAGE_PIXELS == pixels
    assert ImageFile.LOAD_TRUNCATED_IMAGES == truncated


def test_output_size_limit_is_enforced_and_exact_boundary_is_allowed() -> None:
    data = picture()
    normal = ArtworkProcessor().process(data)
    assert normal.jpeg is not None
    size = len(normal.jpeg)
    assert ArtworkProcessor(max_output_bytes=size).process(data).status == "ok"
    result = ArtworkProcessor(max_output_bytes=size - 1).process(data)
    assert result.status == "too_large" and result.jpeg is None
    assert result.width is None and result.height is None


def test_one_byte_output_budget_returns_fallback() -> None:
    result = ArtworkProcessor(max_output_bytes=1).process(picture())
    assert result.status == "too_large" and result.jpeg is None


def test_failures_do_not_leak_private_decoder_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise OSError("private artwork details")

    monkeypatch.setattr(Image, "open", broken)
    result = ArtworkProcessor().process(b"fiction")
    assert result.status == "invalid" and "private" not in result.detail


def test_result_is_frozen_and_artwork_bytes_are_not_in_repr() -> None:
    result = ArtworkResult("ok", b"fictional payload", 160, 160)
    assert "fictional payload" not in repr(result)
    with pytest.raises(FrozenInstanceError):
        result.status = "invalid"  # type: ignore[misc]


@pytest.mark.parametrize("options", [
    {"size": 0}, {"size": 129}, {"size": True}, {"fit": "stretch"},
    {"background": (0, 0)}, {"background": (0, 0, 256)}, {"background": (0, 0, True)},
    {"quality": 0}, {"quality": 96}, {"max_input_bytes": 0},
    {"max_input_bytes": MAX_INPUT_BYTES + 1}, {"max_pixels": MAX_DECODED_PIXELS + 1},
    {"max_pixels": 0}, {"max_output_bytes": 0}, {"max_output_bytes": MAX_OUTPUT_BYTES + 1},
])
def test_configuration_is_bounded(options: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ArtworkProcessor(**options)
