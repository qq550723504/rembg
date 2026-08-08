import asyncio

import httpx
import pytest

from app.url_fetcher import ImageFetcher, UrlFetchError, validate_public_url


def make_fetcher(settings, response: httpx.Response):
    if not hasattr(settings, "url_allowed_hosts"):
        settings.url_allowed_hosts = "example.test"
    transport = httpx.MockTransport(lambda request: response)

    def factory(**kwargs):
        return httpx.AsyncClient(transport=transport, **kwargs)

    return ImageFetcher(settings, client_factory=factory)


def test_validate_public_url_rejects_allowlisted_loopback_and_private_addresses():
    with pytest.raises(UrlFetchError, match="private or reserved address"):
        validate_public_url("http://127.0.0.1/image.png", "127.0.0.1")
    with pytest.raises(UrlFetchError, match="private or reserved address"):
        validate_public_url("http://10.0.0.1/image.png", "10.0.0.1")


def test_validate_public_url_rejects_allowlisted_hostname_resolving_private_address(monkeypatch):
    monkeypatch.setattr("app.url_fetcher.resolve_host", lambda host: ["10.0.0.5"])

    with pytest.raises(UrlFetchError, match="private or reserved address"):
        validate_public_url("https://example.test/image.png", "example.test")


def test_validate_public_url_rejects_empty_allowlist(monkeypatch):
    monkeypatch.setattr("app.url_fetcher.resolve_host", lambda host: ["93.184.216.34"])

    with pytest.raises(UrlFetchError, match="configured allowlist"):
        validate_public_url("https://example.test/image.png", "")


def test_validate_public_url_allows_exact_configured_host(monkeypatch):
    monkeypatch.setattr("app.url_fetcher.resolve_host", lambda host: ["93.184.216.34"])

    validate_public_url("https://example.test/image.png", "example.test,cdn.example.test")


def test_validate_public_url_rejects_host_outside_allowlist(monkeypatch):
    monkeypatch.setattr("app.url_fetcher.resolve_host", lambda host: ["93.184.216.34"])

    with pytest.raises(UrlFetchError, match="configured allowlist"):
        validate_public_url("https://sub.example.test/image.png", "example.test")


def test_fetcher_client_disables_environment_proxy(settings):
    captured_kwargs = {}

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def factory(**kwargs):
        captured_kwargs.update(kwargs)
        return DummyClient()

    fetcher = ImageFetcher(settings, client_factory=factory)

    async def open_client():
        async with fetcher._client():
            return

    asyncio.run(open_client())

    assert captured_kwargs["trust_env"] is False


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

