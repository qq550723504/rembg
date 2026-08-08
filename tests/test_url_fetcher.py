import asyncio
import socket
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp.abc import AbstractResolver

import app.url_fetcher as url_fetcher_module
from app.url_fetcher import (
    ImageFetcher,
    UrlFetchError,
    validate_public_url,
)


class DummyContent:
    def __init__(self, body: bytes):
        self.body = body

    async def iter_chunked(self, size: int):
        yield self.body


class DummyResponse:
    def __init__(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None):
        self.status = status
        self.headers = headers or {}
        self.content = DummyContent(body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class DummySession:
    def __init__(self, response: DummyResponse, captured_kwargs: dict):
        self.response = response
        self.captured_kwargs = captured_kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, url: str, *, allow_redirects: bool):
        self.captured_kwargs["allow_redirects"] = allow_redirects
        return self.response


def make_fetcher(settings, response: DummyResponse):
    if not hasattr(settings, "url_allowed_hosts"):
        settings.url_allowed_hosts = "example.test"
    captured_kwargs = {}

    def factory(**kwargs):
        captured_kwargs.update(kwargs)
        return DummySession(response, captured_kwargs)

    return ImageFetcher(
        settings,
        session_factory=factory,
        resolver_factory=lambda: url_fetcher_module.PinnedPublicResolver(
            resolve_host_func=lambda host: ["93.184.216.34"]
        ),
    )


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


def test_pinned_public_resolver_reuses_validated_address_after_dns_rebinding():
    resolutions = iter([["93.184.216.34"], ["10.0.0.5"]])

    PinnedPublicResolver = url_fetcher_module.PinnedPublicResolver
    resolver = PinnedPublicResolver(resolve_host_func=lambda host: next(resolutions))

    first = asyncio.run(resolver.resolve("example.test", 443, socket.AF_INET))
    second = asyncio.run(resolver.resolve("example.test", 443, socket.AF_INET))

    assert isinstance(resolver, AbstractResolver)
    assert [result["host"] for result in first] == ["93.184.216.34"]
    assert [result["host"] for result in second] == ["93.184.216.34"]


def test_fetcher_client_uses_aiohttp_connector_with_pinned_resolver(settings):
    PinnedPublicResolver = url_fetcher_module.PinnedPublicResolver
    fetcher = ImageFetcher(settings)

    async def open_client():
        async with fetcher._client("https://example.test/image.png") as session:
            return SimpleNamespace(
                connector=session.connector,
                trust_env=session.trust_env,
            )

    client_state = asyncio.run(open_client())

    assert isinstance(client_state.connector, aiohttp.TCPConnector)
    assert isinstance(client_state.connector._resolver, PinnedPublicResolver)
    assert client_state.trust_env is False
    assert client_state.connector._ssl is not False


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

    fetcher = ImageFetcher(settings, session_factory=factory)

    async def open_client():
        async with fetcher._client("https://example.test/image.png"):
            return

    asyncio.run(open_client())

    assert captured_kwargs["trust_env"] is False


def test_fetcher_rejects_redirects(settings, monkeypatch):
    monkeypatch.setattr("app.url_fetcher.resolve_host", lambda host: ["93.184.216.34"])
    fetcher = make_fetcher(
        settings,
        DummyResponse(302, headers={"location": "https://other.example/image.png"}),
    )

    with pytest.raises(UrlFetchError):
        asyncio.run(fetcher.fetch("https://example.test/image.png"))


def test_fetcher_rejects_non_image_bytes(settings, monkeypatch):
    monkeypatch.setattr("app.url_fetcher.resolve_host", lambda host: ["93.184.216.34"])
    fetcher = make_fetcher(
        settings,
        DummyResponse(200, body=b"not-an-image", headers={"content-type": "text/plain"}),
    )

    with pytest.raises(UrlFetchError):
        asyncio.run(fetcher.fetch("https://example.test/image.png"))

