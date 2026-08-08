from io import BytesIO

import pytest
from PIL import Image

from app.image_io import (
    ImageInputError,
    ImageTooLargeError,
    ensure_rgba_png,
    validate_image_bytes,
)


def make_png(width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), "red")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_validate_image_bytes_accepts_valid_image(settings):
    validate_image_bytes(make_png(2, 2), settings)


def test_validate_image_bytes_rejects_malformed_bytes(settings):
    with pytest.raises(ImageInputError):
        validate_image_bytes(b"not an image", settings)


def test_validate_image_bytes_rejects_large_payload(settings):
    with pytest.raises(ImageTooLargeError):
        validate_image_bytes(b"x" * (settings.max_upload_bytes + 1), settings)


def test_validate_image_bytes_rejects_too_many_pixels(settings):
    settings.max_image_pixels = 3

    with pytest.raises(ImageTooLargeError):
        validate_image_bytes(make_png(2, 2), settings)


def test_ensure_rgba_png_returns_rgba_png(settings):
    result = ensure_rgba_png(make_png(2, 2))
    image = Image.open(BytesIO(result))

    assert image.format == "PNG"
    assert image.mode == "RGBA"
