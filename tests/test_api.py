from io import BytesIO
import asyncio
from types import SimpleNamespace

import pytest
from PIL import Image
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.url_fetcher import validate_public_url


def make_authenticated_upload_client(
    fake_remover,
    max_upload_bytes: int,
    max_request_bytes: int | None = None,
):
    settings = SimpleNamespace(
        api_key="test-key",
        model_name="birefnet-general",
        max_upload_bytes=max_upload_bytes,
        max_request_bytes=max_request_bytes or max_upload_bytes,
        max_image_pixels=1_000_000,
        url_allowed_hosts="93.184.216.34",
        url_fetch_timeout_seconds=15.0,
        gpu_max_concurrency=1,
        model_cache_dir="/tmp/rembg-models",
        model_session_cache_size=2,
    )
    client = TestClient(create_app(settings=settings, remover=fake_remover))
    client.headers.update({"X-API-Key": "test-key"})
    return client


def test_health_is_public(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["model"] == "birefnet-general"


def test_upload_requires_api_key(client, png_bytes):
    response = client.post(
        "/v1/remove-background",
        files={"file": ("input.png", png_bytes, "image/png")},
    )

    assert response.status_code == 401


def test_upload_returns_transparent_png(fake_remover, png_bytes):
    client = make_authenticated_upload_client(fake_remover, max_upload_bytes=2048)

    response = client.post(
        "/v1/remove-background",
        files={"file": ("input.png", png_bytes, "image/png")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert Image.open(BytesIO(response.content)).mode == "RGBA"


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
        asyncio.run(endpoint(file=file, model=None, api_key="test-key", content_length=None))

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
        max_image_pixels=1_000_000,
        url_allowed_hosts="example.test",
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
