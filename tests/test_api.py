import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from starlette.requests import Request

from app.config import Settings
from app.main import create_app
from app.remover import InferenceBusyError
from app.url_fetcher import validate_public_url


def make_authenticated_upload_client(
    fake_remover,
    max_upload_bytes: int,
    max_request_bytes: int | None = None,
    rate_limit_per_minute: int = 30,
):
    settings = SimpleNamespace(
        api_key="test-key",
        model_name="birefnet-general",
        max_upload_bytes=max_upload_bytes,
        max_request_bytes=max_request_bytes or max_upload_bytes,
        max_image_pixels=1_000_000,
        url_allowed_hosts="93.184.216.34",
        rate_limit_per_minute=rate_limit_per_minute,
        max_pending_requests=4,
        url_fetch_timeout_seconds=15.0,
        gpu_max_concurrency=1,
        model_cache_dir="/tmp/rembg-models",
        model_session_cache_size=2,
    )
    client = TestClient(create_app(settings=settings, remover=fake_remover))
    client.headers.update({"X-API-Key": "test-key"})
    return client


def make_request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "root_path": "",
            "app": None,
        }
    )


async def call_asgi_post(app, path: str, headers: list[tuple[bytes, bytes]], chunks: list[bytes]):
    sent_messages = []
    receive_calls = 0
    chunk_iter = iter(chunks)

    async def receive():
        nonlocal receive_calls
        receive_calls += 1
        try:
            body = next(chunk_iter)
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}
        return {
            "type": "http.request",
            "body": body,
            "more_body": True,
        }

    async def send(message):
        sent_messages.append(message)

    await app(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "root_path": "",
        },
        receive,
        send,
    )
    start = next(message for message in sent_messages if message["type"] == "http.response.start")
    return SimpleNamespace(status_code=start["status"], receive_calls=receive_calls)


def test_health_is_public(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["model"] == "birefnet-general"


def test_livez_is_public_and_does_not_require_model_readiness(client):
    response = client.get("/livez")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_available_fake_backend_without_exposing_paths(png_bytes):
    class ReadyRemover:
        def remove(self, data: bytes, model_name: str | None = None) -> bytes:
            return png_bytes

        def readiness(self) -> dict[str, object]:
            return {
                "available": True,
                "backend": "fake",
                "providers": ["CPUExecutionProvider"],
            }

    settings = SimpleNamespace(
        api_key="test-key",
        model_name="birefnet-general",
        max_upload_bytes=2048,
        max_request_bytes=2048,
        max_image_pixels=1_000_000,
        url_allowed_hosts="93.184.216.34",
        rate_limit_per_minute=30,
        max_pending_requests=4,
        url_fetch_timeout_seconds=15.0,
        gpu_max_concurrency=1,
        model_cache_dir="/tmp/rembg-models",
        model_session_cache_size=2,
    )
    client = TestClient(create_app(settings=settings, remover=ReadyRemover()))

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "model": "birefnet-general",
        "backend": "fake",
        "providers": ["CPUExecutionProvider"],
    }
    assert "cache" not in response.text.lower()
    assert "/tmp/" not in response.text


def test_readyz_returns_503_when_backend_is_unavailable(png_bytes):
    class NotReadyRemover:
        def remove(self, data: bytes, model_name: str | None = None) -> bytes:
            return png_bytes

        def readiness(self) -> dict[str, object]:
            return {
                "available": False,
                "backend": "fake",
                "providers": [],
                "reason": "model backend unavailable",
            }

    client = make_authenticated_upload_client(NotReadyRemover(), max_upload_bytes=2048)

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "model": "birefnet-general",
        "backend": "fake",
        "providers": [],
        "reason": "model backend unavailable",
    }


def test_readyz_returns_503_when_cache_directory_is_not_writable(png_bytes, tmp_path):
    class ReadyRemover:
        def remove(self, data: bytes, model_name: str | None = None) -> bytes:
            return png_bytes

        def readiness(self) -> dict[str, object]:
            return {
                "available": True,
                "backend": "fake",
                "providers": ["CPUExecutionProvider"],
            }

    cache_file = tmp_path / "not-a-cache-directory"
    cache_file.write_text("not a directory", encoding="utf-8")
    settings = SimpleNamespace(
        api_key="test-key",
        model_name="birefnet-general",
        max_upload_bytes=2048,
        max_request_bytes=4096,
        max_image_pixels=1_000_000,
        url_allowed_hosts="93.184.216.34",
        rate_limit_per_minute=30,
        max_pending_requests=4,
        url_fetch_timeout_seconds=15.0,
        gpu_max_concurrency=1,
        model_cache_dir=str(cache_file),
        model_session_cache_size=2,
    )
    client = TestClient(create_app(settings=settings, remover=ReadyRemover()))

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["reason"] == "model cache directory is not writable"
    assert str(cache_file) not in response.text


def test_upload_requires_api_key(client, png_bytes):
    response = client.post(
        "/v1/remove-background",
        files={"file": ("input.png", png_bytes, "image/png")},
    )

    assert response.status_code == 401


def test_upload_requires_api_key_before_rate_limiting(fake_remover, png_bytes):
    settings = SimpleNamespace(
        api_key="test-key",
        model_name="birefnet-general",
        max_upload_bytes=2048,
        max_request_bytes=2048,
        max_image_pixels=1_000_000,
        url_allowed_hosts="93.184.216.34",
        rate_limit_per_minute=1,
        max_pending_requests=4,
        url_fetch_timeout_seconds=15.0,
        gpu_max_concurrency=1,
        model_cache_dir="/tmp/rembg-models",
        model_session_cache_size=2,
    )
    client = TestClient(create_app(settings=settings, remover=fake_remover))

    response = client.post(
        "/v1/remove-background",
        files={"file": ("input.png", png_bytes, "image/png")},
    )

    assert response.status_code == 401


def test_upload_keeps_invalid_api_key_unauthorized_after_retries(fake_remover, png_bytes):
    settings = SimpleNamespace(
        api_key="test-key",
        model_name="birefnet-general",
        max_upload_bytes=2048,
        max_request_bytes=2048,
        max_image_pixels=1_000_000,
        url_allowed_hosts="93.184.216.34",
        rate_limit_per_minute=1,
        max_pending_requests=4,
        url_fetch_timeout_seconds=15.0,
        gpu_max_concurrency=1,
        model_cache_dir="/tmp/rembg-models",
        model_session_cache_size=2,
    )
    client = TestClient(create_app(settings=settings, remover=fake_remover))

    responses = [
        client.post(
            "/v1/remove-background",
            headers={"X-API-Key": "wrong-key"},
            files={"file": ("input.png", png_bytes, "image/png")},
        )
        for _ in range(3)
    ]

    assert [response.status_code for response in responses] == [401, 401, 401]
    assert fake_remover.calls == []


def test_upload_returns_transparent_png(fake_remover, png_bytes):
    client = make_authenticated_upload_client(fake_remover, max_upload_bytes=2048)

    response = client.post(
        "/v1/remove-background",
        files={"file": ("input.png", png_bytes, "image/png")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert Image.open(BytesIO(response.content)).mode == "RGBA"


def test_upload_route_is_the_single_png_normalization_boundary(png_bytes):
    rgb_image = Image.new("RGB", (2, 2), (0, 255, 0))
    output = BytesIO()
    rgb_image.save(output, format="JPEG")

    class RawResultRemover:
        def remove(self, data: bytes, model_name: str | None = None) -> bytes:
            return output.getvalue()

    client = make_authenticated_upload_client(RawResultRemover(), max_upload_bytes=2048)

    response = client.post(
        "/v1/remove-background",
        files={"file": ("input.png", png_bytes, "image/png")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    rendered = Image.open(BytesIO(response.content))
    assert rendered.format == "PNG"
    assert rendered.mode == "RGBA"


def test_upload_returns_429_when_inference_is_busy(png_bytes):
    class BusyRemover:
        async def remove(self, data: bytes, model_name: str | None = None) -> bytes:
            raise InferenceBusyError("Inference capacity is full")

    client = make_authenticated_upload_client(BusyRemover(), max_upload_bytes=2048)

    response = client.post(
        "/v1/remove-background",
        files={"file": ("input.png", png_bytes, "image/png")},
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "1"


def test_url_returns_429_when_inference_is_busy(png_bytes):
    class BusyRemover:
        async def remove(self, data: bytes, model_name: str | None = None) -> bytes:
            raise InferenceBusyError("Inference capacity is full")

    settings = SimpleNamespace(
        api_key="test-key",
        model_name="birefnet-general",
        max_upload_bytes=2048,
        max_request_bytes=2048,
        max_image_pixels=1_000_000,
        url_allowed_hosts="93.184.216.34",
        rate_limit_per_minute=30,
        max_pending_requests=4,
        url_fetch_timeout_seconds=15.0,
        gpu_max_concurrency=1,
        model_cache_dir="/tmp/rembg-models",
        model_session_cache_size=2,
    )
    client = TestClient(
        create_app(
            settings=settings,
            remover=BusyRemover(),
            fetcher=SimpleNamespace(fetch=lambda url: png_bytes),
        )
    )
    client.headers.update({"X-API-Key": "test-key"})

    response = client.post(
        "/v1/remove-background/url",
        json={"image_url": "https://93.184.216.34/input.png"},
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "1"


def test_upload_too_large_returns_413(authenticated_client, png_bytes):
    oversized = png_bytes + b"x" * 256
    response = authenticated_client.post(
        "/v1/remove-background",
        files={"file": ("input.png", oversized, "image/png")},
    )

    assert response.status_code == 413


def test_upload_reads_only_configured_limit(settings, fake_remover):
    app = create_app(settings=settings, remover=fake_remover)
    endpoint = next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == "/v1/remove-background"
        and "POST" in getattr(route, "methods", set())
    )

    class FakeUpload:
        def __init__(self, payload: bytes):
            self.payload = payload
            self.read_sizes: list[int | None] = []

        async def read(self, size: int | None = None) -> bytes:
            self.read_sizes.append(size)
            return self.payload

    file = FakeUpload(b"x" * (settings.max_upload_bytes + 1))

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            endpoint(
                request=make_request("/v1/remove-background"),
                file=file,
                model=None,
                api_key="test-key",
                content_length=None,
            )
        )

    assert excinfo.value.status_code == 413
    assert file.read_sizes == [settings.max_upload_bytes + 1]


def test_upload_rejects_oversized_content_length_before_read(settings, fake_remover):
    settings.max_request_bytes = settings.max_upload_bytes + 1
    app = create_app(settings=settings, remover=fake_remover)
    endpoint = next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == "/v1/remove-background"
        and "POST" in getattr(route, "methods", set())
    )

    class FakeUpload:
        def __init__(self):
            self.read_calls = 0

        async def read(self, size: int | None = None) -> bytes:
            self.read_calls += 1
            return b""

    file = FakeUpload()

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            endpoint(
                request=make_request("/v1/remove-background"),
                file=file,
                model=None,
                api_key="test-key",
                content_length=str(settings.max_request_bytes + 1),
            )
        )

    assert excinfo.value.status_code == 413
    assert file.read_calls == 0


def test_upload_route_rejects_oversized_request_content_length(fake_remover, png_bytes):
    settings = SimpleNamespace(
        api_key="test-key",
        model_name="birefnet-general",
        max_upload_bytes=1024,
        max_request_bytes=1024,
        max_image_pixels=1_000_000,
        url_allowed_hosts="93.184.216.34",
        rate_limit_per_minute=30,
        max_pending_requests=4,
        url_fetch_timeout_seconds=15.0,
        gpu_max_concurrency=1,
        model_cache_dir="/tmp/rembg-models",
        model_session_cache_size=2,
    )
    client = TestClient(create_app(settings=settings, remover=fake_remover))
    client.headers.update({"X-API-Key": "test-key"})

    response = client.post(
        "/v1/remove-background",
        headers={"Content-Length": str(settings.max_upload_bytes + 1)},
        files={"file": ("input.png", png_bytes, "image/png")},
    )

    assert response.status_code == 413
    assert fake_remover.calls == []


def test_upload_route_allows_valid_file_when_request_framing_exceeds_image_limit(
    fake_remover, png_bytes
):
    max_upload_bytes = len(png_bytes)
    max_request_bytes = 2048
    client = make_authenticated_upload_client(
        fake_remover,
        max_upload_bytes=max_upload_bytes,
        max_request_bytes=max_request_bytes,
    )

    response = client.post(
        "/v1/remove-background",
        headers={"Content-Length": str(max_upload_bytes + 1)},
        files={"file": ("input.png", png_bytes, "image/png")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_asgi_request_limit_rejects_oversized_content_length_before_body_read(
    fake_remover,
):
    settings = SimpleNamespace(
        api_key="test-key",
        model_name="birefnet-general",
        max_upload_bytes=32,
        max_request_bytes=64,
        max_image_pixels=1_000_000,
        url_allowed_hosts="93.184.216.34",
        rate_limit_per_minute=30,
        max_pending_requests=4,
        url_fetch_timeout_seconds=15.0,
        gpu_max_concurrency=1,
        model_cache_dir="/tmp/rembg-models",
        model_session_cache_size=2,
    )
    app = create_app(settings=settings, remover=fake_remover)

    response = asyncio.run(
        call_asgi_post(
            app,
            "/v1/remove-background",
            headers=[
                (b"x-api-key", b"test-key"),
                (b"content-length", b"65"),
                (b"content-type", b"application/octet-stream"),
            ],
            chunks=[],
        )
    )

    assert response.status_code == 413
    assert response.receive_calls == 0
    assert fake_remover.calls == []


def test_asgi_protected_upload_rejects_invalid_api_key_before_request_limit(
    fake_remover,
):
    settings = SimpleNamespace(
        api_key="test-key",
        model_name="birefnet-general",
        max_upload_bytes=32,
        max_request_bytes=64,
        max_image_pixels=1_000_000,
        url_allowed_hosts="93.184.216.34",
        rate_limit_per_minute=30,
        max_pending_requests=4,
        url_fetch_timeout_seconds=15.0,
        gpu_max_concurrency=1,
        model_cache_dir="/tmp/rembg-models",
        model_session_cache_size=2,
    )
    app = create_app(settings=settings, remover=fake_remover)

    response = asyncio.run(
        call_asgi_post(
            app,
            "/v1/remove-background",
            headers=[
                (b"x-api-key", b"wrong-key"),
                (b"content-length", b"65"),
                (b"content-type", b"application/octet-stream"),
            ],
            chunks=[],
        )
    )

    assert response.status_code == 401
    assert response.receive_calls == 0
    assert fake_remover.calls == []


def test_asgi_request_limit_rejects_chunked_body_without_content_length(
    fake_remover,
):
    settings = SimpleNamespace(
        api_key="test-key",
        model_name="birefnet-general",
        max_upload_bytes=32,
        max_request_bytes=64,
        max_image_pixels=1_000_000,
        url_allowed_hosts="93.184.216.34",
        rate_limit_per_minute=30,
        max_pending_requests=4,
        url_fetch_timeout_seconds=15.0,
        gpu_max_concurrency=1,
        model_cache_dir="/tmp/rembg-models",
        model_session_cache_size=2,
    )
    app = create_app(settings=settings, remover=fake_remover)

    response = asyncio.run(
        call_asgi_post(
            app,
            "/v1/remove-background",
            headers=[
                (b"x-api-key", b"test-key"),
                (b"content-type", b"multipart/form-data; boundary=test-boundary"),
            ],
            chunks=[
                b"--test-boundary\r\n",
                b'Content-Disposition: form-data; name="file"; filename="input.png"\r\n',
            ],
        )
    )

    assert response.status_code == 413
    assert fake_remover.calls == []


def test_rate_limiter_rejects_second_upload_request(fake_remover, png_bytes):
    client = make_authenticated_upload_client(
        fake_remover,
        max_upload_bytes=2048,
        rate_limit_per_minute=1,
    )

    first = client.post(
        "/v1/remove-background",
        files={"file": ("input.png", png_bytes, "image/png")},
    )
    second = client.post(
        "/v1/remove-background",
        files={"file": ("input.png", png_bytes, "image/png")},
    )

    assert first.status_code == 200
    assert second.status_code == 429


def test_rate_limiter_rejects_second_url_request(fake_remover, png_bytes):
    settings = SimpleNamespace(
        api_key="test-key",
        model_name="birefnet-general",
        max_upload_bytes=2048,
        max_request_bytes=2048,
        max_image_pixels=1_000_000,
        url_allowed_hosts="93.184.216.34",
        rate_limit_per_minute=1,
        max_pending_requests=4,
        url_fetch_timeout_seconds=15.0,
        gpu_max_concurrency=1,
        model_cache_dir="/tmp/rembg-models",
        model_session_cache_size=2,
    )
    client = TestClient(
        create_app(
            settings=settings,
            remover=fake_remover,
            fetcher=SimpleNamespace(fetch=lambda url: png_bytes),
        )
    )
    client.headers.update({"X-API-Key": "test-key"})

    first = client.post(
        "/v1/remove-background/url",
        json={"image_url": "https://93.184.216.34/input.png"},
    )
    second = client.post(
        "/v1/remove-background/url",
        json={"image_url": "https://93.184.216.34/input.png"},
    )

    assert first.status_code == 200
    assert second.status_code == 429


def test_rate_limiter_shares_valid_api_key_limit_across_removal_routes(
    fake_remover, png_bytes
):
    settings = SimpleNamespace(
        api_key="test-key",
        model_name="birefnet-general",
        max_upload_bytes=2048,
        max_request_bytes=2048,
        max_image_pixels=1_000_000,
        url_allowed_hosts="93.184.216.34",
        rate_limit_per_minute=1,
        max_pending_requests=4,
        url_fetch_timeout_seconds=15.0,
        gpu_max_concurrency=1,
        model_cache_dir="/tmp/rembg-models",
        model_session_cache_size=2,
    )
    client = TestClient(
        create_app(
            settings=settings,
            remover=fake_remover,
            fetcher=SimpleNamespace(fetch=lambda url: png_bytes),
        )
    )
    client.headers.update({"X-API-Key": "test-key"})

    upload = client.post(
        "/v1/remove-background",
        files={"file": ("input.png", png_bytes, "image/png")},
    )
    url = client.post(
        "/v1/remove-background/url",
        json={"image_url": "https://93.184.216.34/input.png"},
    )

    assert upload.status_code == 200
    assert url.status_code == 429


def test_url_endpoint_accepts_json(authenticated_client, fake_fetcher):
    response = authenticated_client.post(
        "/v1/remove-background/url",
        json={"image_url": "https://93.184.216.34/input.png"},
    )

    assert response.status_code == 200
    assert fake_fetcher.urls == ["https://93.184.216.34/input.png"]


def test_url_endpoint_rejects_private_address(fake_remover, png_bytes):
    settings = SimpleNamespace(
        api_key="test-key",
        model_name="birefnet-general",
        max_upload_bytes=128,
        max_request_bytes=128,
        max_image_pixels=1_000_000,
        url_allowed_hosts="example.test",
        rate_limit_per_minute=30,
        max_pending_requests=4,
        url_fetch_timeout_seconds=15.0,
        gpu_max_concurrency=1,
        model_cache_dir="/tmp/rembg-models",
        model_session_cache_size=2,
    )

    class ValidatingFetcher:
        def fetch(self, url: str) -> bytes:
            validate_public_url(url, settings.url_allowed_hosts)
            return png_bytes

    client = TestClient(
        create_app(settings=settings, remover=fake_remover, fetcher=ValidatingFetcher())
    )
    client.headers.update({"X-API-Key": "test-key"})

    response = client.post(
        "/v1/remove-background/url",
        json={"image_url": "http://127.0.0.1/image.png"},
    )

    assert response.status_code == 400


def test_models_endpoint_lists_default_and_supported_models(client):
    response = client.get("/v1/models")

    assert response.status_code == 200
    payload = response.json()
    assert payload["default_model"] == "birefnet-general"
    assert {item["name"] for item in payload["models"]} >= {
        "birefnet-general",
        "birefnet-portrait",
    }


def test_upload_passes_requested_model_to_remover(
    fake_remover, png_bytes
):
    client = make_authenticated_upload_client(fake_remover, max_upload_bytes=2048)

    response = client.post(
        "/v1/remove-background",
        files={"file": ("input.png", png_bytes, "image/png")},
        data={"model": "birefnet-portrait"},
    )

    assert response.status_code == 200
    assert fake_remover.calls[-1][1] == "birefnet-portrait"


def test_url_passes_requested_model_to_remover(
    authenticated_client, fake_fetcher, fake_remover
):
    response = authenticated_client.post(
        "/v1/remove-background/url",
        json={"image_url": "https://93.184.216.34/input.png", "model": "isnet-anime"},
    )

    assert response.status_code == 200
    assert fake_fetcher.urls == ["https://93.184.216.34/input.png"]
    assert fake_remover.calls[-1][1] == "isnet-anime"


def test_unknown_model_is_rejected_before_upload_processing(
    authenticated_client, fake_remover, png_bytes
):
    response = authenticated_client.post(
        "/v1/remove-background",
        files={"file": ("input.png", png_bytes, "image/png")},
        data={"model": "made-up-model"},
    )

    assert response.status_code == 400
    assert "Unsupported model" in response.json()["detail"]
    assert fake_remover.calls == []


def test_create_app_rejects_invalid_default_model():
    with pytest.raises(ValueError, match="Unsupported model: unknown"):
        create_app(settings=Settings(api_key="secret", model_name="unknown"))

