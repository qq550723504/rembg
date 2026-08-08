import inspect
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .auth import require_api_key
from .config import Settings
from .image_io import (
    ImageInputError,
    ImageTooLargeError,
    ensure_rgba_png,
    validate_image_bytes,
)
from .models import model_options, resolve_model_name
from .remover import (
    BackgroundRemover,
    InferenceBusyError,
    ReadinessAwareRemover,
    RembgRemover,
)
from .url_fetcher import ImageFetcher, UrlFetchError

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


def _api_key_rate_limit_key(request: Request) -> str:
    return request.headers.get("X-API-Key", "")


def _skip_rate_limit_when_api_key_missing(request: Request) -> bool:
    return not bool(request.headers.get("X-API-Key"))


def _readiness_payload(
    settings: Settings,
    remover: BackgroundRemover,
) -> tuple[int, dict[str, object]]:
    if isinstance(remover, ReadinessAwareRemover):
        readiness = remover.readiness()
    else:
        readiness = {
            "available": True,
            "backend": type(remover).__name__,
            "providers": [],
        }

    payload: dict[str, object] = {
        "status": "ok" if readiness["available"] else "unavailable",
        "model": settings.model_name,
        "backend": readiness["backend"],
        "providers": readiness["providers"],
    }
    if "reason" in readiness:
        payload["reason"] = readiness["reason"]
    return (200 if readiness["available"] else 503, payload)


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
    limiter = Limiter(key_func=_api_key_rate_limit_key)
    rate_limit = f"{getattr(settings, 'rate_limit_per_minute', 30)}/minute"
    application.state.limiter = limiter
    application.add_exception_handler(
        RateLimitExceeded,
        _rate_limit_exceeded_handler,
    )
    application.add_exception_handler(
        InferenceBusyError,
        lambda request, exc: Response(
            content=str(exc),
            status_code=429,
            headers={"Retry-After": "1"},
        ),
    )
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @application.get("/", include_in_schema=False)
    async def homepage() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "model": settings.model_name}

    @application.get("/livez")
    async def livez() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/readyz")
    async def readyz() -> JSONResponse:
        status_code, payload = _readiness_payload(settings, remover)
        return JSONResponse(content=payload, status_code=status_code)

    @application.get("/v1/models")
    async def models() -> dict[str, object]:
        return {
            "default_model": settings.model_name,
            "models": model_options(settings.model_name),
        }

    @application.post("/v1/remove-background")
    @limiter.limit(rate_limit, exempt_when=_skip_rate_limit_when_api_key_missing)
    async def remove_background(
        request: Request,
        file: UploadFile | None = File(default=None),
        model: str | None = Form(default=None),
        api_key: str | None = Header(default=None, alias="X-API-Key"),
        content_length: str | None = Header(default=None, alias="Content-Length"),
    ) -> Response:
        require_api_key(settings, api_key)
        try:
            model_name = resolve_model_name(model, settings.model_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if file is None:
            raise HTTPException(status_code=400, detail="file is required")

        try:
            if content_length and content_length.isdigit():
                max_request_bytes = getattr(settings, "max_request_bytes", settings.max_upload_bytes)
                if int(content_length) > max_request_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail="Request exceeds the maximum allowed size",
                    )

            data = await file.read(settings.max_upload_bytes + 1)
            validate_image_bytes(data, settings)
            result = await _maybe_await(remover.remove(data, model_name))
            return Response(content=ensure_rgba_png(result), media_type="image/png")
        except InferenceBusyError:
            raise
        except HTTPException:
            raise
        except Exception as exc:
            if isinstance(exc, (ImageInputError, ImageTooLargeError)):
                raise _image_error(exc) from exc
            logger.exception("Background removal failed")
            raise _image_error(exc) from exc

    @application.post("/v1/remove-background/url")
    @limiter.limit(rate_limit, exempt_when=_skip_rate_limit_when_api_key_missing)
    async def remove_background_from_url(
        request: Request,
        payload: ImageUrlRequest,
        api_key: str | None = Header(default=None, alias="X-API-Key"),
    ) -> Response:
        require_api_key(settings, api_key)
        try:
            model_name = resolve_model_name(payload.model, settings.model_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            data = await _maybe_await(fetcher.fetch(payload.image_url))
            validate_image_bytes(data, settings)
            result = await _maybe_await(remover.remove(data, model_name))
            return Response(content=ensure_rgba_png(result), media_type="image/png")
        except InferenceBusyError:
            raise
        except HTTPException:
            raise
        except Exception as exc:
            if isinstance(exc, (ImageInputError, ImageTooLargeError, UrlFetchError)):
                raise _image_error(exc) from exc
            logger.exception("Background removal from URL failed")
            raise _image_error(exc) from exc

    return application


app = create_app()
