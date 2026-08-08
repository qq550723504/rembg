import asyncio

import httpx
import pytest

from app.url_fetcher import ImageFetcher, UrlFetchError, validate_public_url


def make_fetcher(settings, response: httpx.Response):
    transport = httpx.MockTransport(lambda request: response)

    def factory(**kwargs):
        return httpx.AsyncClient(transport=transport, **kwargs)

    return ImageFetcher(settings, client_factory=factory)


def test_validate_public_url_rejects_loopback_and_private_addresses():
    with pytest.raises(UrlFetchError):
        validate_public_url("http://127.0.0.1/image.png")
    with pytest.raises(UrlFetchError):
        validate_public_url("http://10.0.0.1/image.png")


def test_fetcher_rejects_redirects(settings, monkeypatch):
    monkeypatch.setattr("app.url_fetcher.resolve_host", lambda host: ["93.184.216.34"])
    fetcher = make_fetcher(
        settings,
        httpx.Response(302, headers={"location": "https://other.example/image.png"}),
    )

    with pytest.raises(UrlFetchError):
        asyncio.run(fetcher.fetch("https://example.test/image.png"))


def test_fetcher_rejects_non_image_bytes(settings, monkeypatch):
    monkeypatch.setattr("app.url_fetcher.resolve_host", lambda host: ["93.184.216.34"])
    fetcher = make_fetcher(
        settings,
        httpx.Response(200, content=b"not-an-image", headers={"content-type": "text/plain"}),
    )

    with pytest.raises(UrlFetchError):
        asyncio.run(fetcher.fetch("https://example.test/image.png"))
