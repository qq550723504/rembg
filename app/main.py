import asyncio
import inspect
import json
import logging
import secrets
import tempfile
from pathlib import Path
from typing import Annotated, Any

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
from .removal_options import RemovalOptions
from .remover import (
    BackgroundRemover,
    InferenceBusyError,
    ReadinessAwareRemover,
    RembgRemover,
)
from .request_limits import RequestBodyLimitMiddleware
from .url_fetcher import ImageFetcher, UrlFetchError

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"
UPLOAD_FILE = File(default=None)
UPLOAD_MODEL = Form(default=None)
API_KEY_HEADER = Header(default=None, alias="X-API-Key")
CONTENT_LENGTH_HEADER = Header(default=None, alias="Content-Length")


class ImageUrlRequest(BaseModel):
    image_url: str = Field(min_length=1)
    model: str | None = Field(default=None)
    alpha_matting: bool = False
    alpha_matting_foreground_threshold: int = Field(default=240, ge=0, le=255)
    alpha_matting_background_threshold: int = Field(default=10, ge=0, le=255)
    alpha_matting_erode_size: int = Field(default=10, ge=0, le=255)
    post_process_mask: bool = False
    cloth_category: str | None = None
    sam_prompt: list[dict[str, Any]] | None = None
    sam_model: str | None = None
    sam_quant: bool = False

    def removal_options(self) -> RemovalOptions:
        return RemovalOptions(
            alpha_matting=self.alpha_matting,
            alpha_matting_foreground_threshold=self.alpha_matting_foreground_threshold,
            alpha_matting_background_threshold=self.alpha_matting_background_threshold,
            alpha_matting_erode_size=self.alpha_matting_erode_size,
            post_process_mask=self.post_process_mask,
            cloth_category=self.cloth_category,
            sam_prompt=self.sam_prompt,
            sam_model=self.sam_model,
            sam_quant=self.sam_quant,
        )


def _parse_sam_prompt(value: str | None) -> list[dict[str, Any]] | None:
    if value is None or not value.strip():
        return None
    try:
        prompt = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="sam_prompt must be valid JSON") from exc
    if not isinstance(prompt, list):
        raise HTTPException(status_code=422, detail="sam_prompt must be a JSON array")
    return prompt


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _remove_with_options(
    remover: BackgroundRemover,
    data: bytes,
    model_name: str,
    options: RemovalOptions,
) -> bytes:
    kwargs = options.to_kwargs()
    if kwargs:
        return await _maybe_await(remover.remove(data, model_name, **kwargs))
    return await _maybe_await(remover.remove(data, model_name))


async def _wait_for_disconnect(request: Request) -> None:
    while True:
        message = await request.receive()
        if message["type"] == "http.disconnect":
            return


async def _await_or_cancel_on_disconnect(request: Request, operation: Any) -> Any | None:
    operation_task = asyncio.ensure_future(operation)
    disconnect_task = asyncio.create_task(_wait_for_disconnect(request))
    try:
        done, _ = await asyncio.wait(
            {operation_task, disconnect_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if operation_task in done:
            return await operation_task

        operation_task.cancel()
        await asyncio.gather(operation_task, return_exceptions=True)
        return None
    finally:
        disconnect_task.cancel()
        await asyncio.gather(disconnect_task, return_exceptions=True)
        if not operation_task.done():
            operation_task.cancel()
            await asyncio.gather(operation_task, return_exceptions=True)


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


def _has_valid_api_key(settings: Settings, request: Request) -> bool:
    supplied_key = request.headers.get("X-API-Key")
    return bool(supplied_key) and secrets.compare_digest(supplied_key, settings.api_key)


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
    if not _cache_directory_writable(settings.model_cache_dir):
        payload["status"] = "unavailable"
        payload["reason"] = "model cache directory is not writable"
        return 503, payload
    return (200 if readiness["available"] else 503, payload)


def _cache_directory_writable(cache_dir: str) -> bool:
    try:
        path = Path(cache_dir)
        path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            return False
        with tempfile.TemporaryFile(dir=path):
            return True
    except OSError:
        return False


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
    application.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=getattr(settings, "max_request_bytes", settings.max_upload_bytes),
        api_key=settings.api_key,
        protected_paths=("/v1/remove-background", "/v1/remove-background/url"),
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

    limit_removal_route = limiter.shared_limit(
        rate_limit,
        scope="remove-background",
        exempt_when=lambda request: not _has_valid_api_key(settings, request),
    )

    @application.post("/v1/remove-background")
    @limit_removal_route
    async def remove_background(
        request: Request,
        file: UploadFile | None = UPLOAD_FILE,
        model: str | None = UPLOAD_MODEL,
        alpha_matting: Annotated[bool, Form()] = False,
        alpha_matting_foreground_threshold: Annotated[int, Form(ge=0, le=255)] = 240,
        alpha_matting_background_threshold: Annotated[int, Form(ge=0, le=255)] = 10,
        alpha_matting_erode_size: Annotated[int, Form(ge=0, le=255)] = 10,
        post_process_mask: Annotated[bool, Form()] = False,
        cloth_category: Annotated[str | None, Form()] = None,
        sam_prompt: Annotated[str | None, Form()] = None,
        sam_model: Annotated[str | None, Form()] = None,
        sam_quant: Annotated[bool, Form()] = False,
        api_key: str | None = API_KEY_HEADER,
        content_length: str | None = CONTENT_LENGTH_HEADER,
    ) -> Response:
        require_api_key(settings, api_key)
        try:
            model_name = resolve_model_name(model, settings.model_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if file is None:
            raise HTTPException(status_code=400, detail="file is required")
        removal_options = RemovalOptions(
            alpha_matting=alpha_matting,
            alpha_matting_foreground_threshold=alpha_matting_foreground_threshold,
            alpha_matting_background_threshold=alpha_matting_background_threshold,
            alpha_matting_erode_size=alpha_matting_erode_size,
            post_process_mask=post_process_mask,
            cloth_category=cloth_category,
            sam_prompt=_parse_sam_prompt(sam_prompt),
            sam_model=sam_model,
            sam_quant=sam_quant,
        )
        try:
            removal_options.validate_for_model(model_name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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
            async def process_upload() -> bytes:
                result = await _remove_with_options(
                    remover, data, model_name, removal_options
                )
                return await asyncio.to_thread(ensure_rgba_png, result)

            normalized = await _await_or_cancel_on_disconnect(
                request,
                process_upload(),
            )
            if normalized is None:
                return Response(status_code=204)
            return Response(content=normalized, media_type="image/png")
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
    @limit_removal_route
    async def remove_background_from_url(
        request: Request,
        payload: ImageUrlRequest,
        api_key: str | None = API_KEY_HEADER,
    ) -> Response:
        require_api_key(settings, api_key)
        try:
            model_name = resolve_model_name(payload.model, settings.model_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            removal_options = payload.removal_options()
            removal_options.validate_for_model(model_name)

            async def process_url() -> bytes:
                data = await _maybe_await(fetcher.fetch(payload.image_url))
                validate_image_bytes(data, settings)
                result = await _remove_with_options(
                    remover, data, model_name, removal_options
                )
                return await asyncio.to_thread(ensure_rgba_png, result)

            normalized = await _await_or_cancel_on_disconnect(
                request,
                process_url(),
            )
            if normalized is None:
                return Response(status_code=204)
            return Response(content=normalized, media_type="image/png")
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

