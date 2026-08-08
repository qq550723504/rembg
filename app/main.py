import inspect
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from .auth import require_api_key
from .config import Settings
from .image_io import (
    ImageInputError,
    ImageTooLargeError,
    ensure_rgba_png,
    validate_image_bytes,
)
from .models import model_options, resolve_model_name
from .remover import BackgroundRemover, RembgRemover
from .url_fetcher import ImageFetcher, UrlFetchError, validate_public_url

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


class ImageUrlRequest(BaseModel):
    image_url: str = Field(min_length=1)
    model: str | None = Field(default=None)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _load_default_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        raise RuntimeError("API_KEY must be configured before starting the service") from exc


def _image_error(error: Exception) -> HTTPException:
    if isinstance(error, ImageTooLargeError):
        return HTTPException(status_code=413, detail=str(error))
    if isinstance(error, (ImageInputError, UrlFetchError)):
        return HTTPException(status_code=400, detail=str(error))
    return HTTPException(status_code=500, detail="Background removal failed")


def create_app(
    settings: Settings | None = None,
    remover: BackgroundRemover | None = None,
    fetcher: ImageFetcher | None = None,
) -> FastAPI:
    settings = settings or _load_default_settings()
    resolve_model_name(None, settings.model_name)
    remover = remover or RembgRemover(settings)
    fetcher = fetcher or ImageFetcher(settings)

    application = FastAPI(
        title="rembg BiRefNet API",
        version="0.1.0",
    )
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @application.get("/", include_in_schema=False)
    async def homepage() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "model": settings.model_name}

    @application.get("/v1/models")
    async def models() -> dict[str, object]:
        return {
            "default_model": settings.model_name,
            "models": model_options(settings.model_name),
        }

    @application.post("/v1/remove-background")
    async def remove_background(
        file: UploadFile | None = File(default=None),
        model: str | None = Form(default=None),
        api_key: str | None = Header(default=None, alias="X-API-Key"),
    ) -> Response:
        require_api_key(settings, api_key)
        try:
            model_name = resolve_model_name(model, settings.model_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if file is None:
            raise HTTPException(status_code=400, detail="file is required")

        try:
            data = await file.read()
            validate_image_bytes(data, settings)
            result = await _maybe_await(remover.remove(data, model_name))
            return Response(content=ensure_rgba_png(result), media_type="image/png")
        except HTTPException:
            raise
        except Exception as exc:
            if isinstance(exc, (ImageInputError, ImageTooLargeError)):
                raise _image_error(exc) from exc
            logger.exception("Background removal failed")
            raise _image_error(exc) from exc

    @application.post("/v1/remove-background/url")
    async def remove_background_from_url(
        request: ImageUrlRequest,
        api_key: str | None = Header(default=None, alias="X-API-Key"),
    ) -> Response:
        require_api_key(settings, api_key)
        try:
            model_name = resolve_model_name(request.model, settings.model_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            validate_public_url(request.image_url)
            data = await _maybe_await(fetcher.fetch(request.image_url))
            validate_image_bytes(data, settings)
            result = await _maybe_await(remover.remove(data, model_name))
            return Response(content=ensure_rgba_png(result), media_type="image/png")
        except HTTPException:
            raise
        except Exception as exc:
            if isinstance(exc, (ImageInputError, ImageTooLargeError, UrlFetchError)):
                raise _image_error(exc) from exc
            logger.exception("Background removal from URL failed")
            raise _image_error(exc) from exc

    return application


app = create_app()
