from io import BytesIO

from PIL import Image, UnidentifiedImageError


class ImageInputError(ValueError):
    """The request does not contain a supported image."""


class ImageTooLargeError(ValueError):
    """The request exceeds a configured byte or pixel limit."""


_SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP"}


def validate_image_bytes(data: bytes, settings) -> None:
    if len(data) > settings.max_upload_bytes:
        raise ImageTooLargeError("Image exceeds the maximum upload size")

    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
        with Image.open(BytesIO(data)) as image:
            if image.format not in _SUPPORTED_FORMATS:
                raise ImageInputError("Only JPEG, PNG, and WebP images are supported")
            if image.width * image.height > settings.max_image_pixels:
                raise ImageTooLargeError("Image exceeds the maximum pixel count")
    except ImageTooLargeError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageInputError("Invalid or unsupported image") from exc


def ensure_rgba_png(data: bytes) -> bytes:
    try:
        with Image.open(BytesIO(data)) as image:
            rgba = image.convert("RGBA")
            output = BytesIO()
            rgba.save(output, format="PNG")
            return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageInputError("Background remover returned invalid image data") from exc
