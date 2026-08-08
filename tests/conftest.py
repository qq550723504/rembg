import os
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image
from fastapi.testclient import TestClient

os.environ.setdefault("API_KEY", "test-key")


class FakeRemover:
    def __init__(self, output: bytes):
        self.output = output
        self.calls: list[bytes] = []

    def remove(self, data: bytes) -> bytes:
        self.calls.append(data)
        return self.output


class FakeFetcher:
    def __init__(self, output: bytes):
        self.output = output
        self.urls: list[str] = []

    def fetch(self, url: str) -> bytes:
        self.urls.append(url)
        return self.output


def make_png(width: int = 2, height: int = 2) -> bytes:
    image = Image.new("RGBA", (width, height), (255, 0, 0, 180))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def png_bytes() -> bytes:
    return make_png()


@pytest.fixture
def settings():
    return SimpleNamespace(
        api_key="test-key",
        model_name="birefnet-general",
        max_upload_bytes=128,
        max_image_pixels=1_000_000,
        url_fetch_timeout_seconds=15.0,
        gpu_max_concurrency=1,
        model_cache_dir="/tmp/rembg-models",
    )


@pytest.fixture
def fake_remover(png_bytes):
    return FakeRemover(png_bytes)


@pytest.fixture
def fake_fetcher(png_bytes):
    return FakeFetcher(png_bytes)


@pytest.fixture
def client(settings, fake_remover, fake_fetcher):
    from app.main import create_app

    return TestClient(
        create_app(settings=settings, remover=fake_remover, fetcher=fake_fetcher)
    )


@pytest.fixture
def authenticated_client(client):
    client.headers.update({"X-API-Key": "test-key"})
    return client
