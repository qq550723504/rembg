import asyncio
import ipaddress
import socket
from contextlib import asynccontextmanager
from typing import Callable
from urllib.parse import urlparse

import httpx

from .image_io import ImageInputError, ImageTooLargeError, validate_image_bytes


class UrlFetchError(ValueError):
    """The URL is unsafe or could not be fetched as an image."""


def _parse_allowed_hosts(allowed_hosts: str) -> set[str]:
    hosts = {host.strip().rstrip(".").lower() for host in allowed_hosts.split(",") if host.strip()}
    if not hosts:
        raise UrlFetchError("Image URL host is not in the configured allowlist")
    return hosts


def resolve_host(host: str) -> list[str]:
    try:
        results = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UrlFetchError("Unable to resolve image URL host") from exc
    return list({result[4][0] for result in results})


def _is_public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        or address.is_reserved
        or address.is_multicast
    )


def validate_public_url(url: str, allowed_hosts: str = "") -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UrlFetchError("Only HTTP and HTTPS image URLs are supported")
    if parsed.username or parsed.password:
        raise UrlFetchError("Image URLs must not contain credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise UrlFetchError("Image URL contains an invalid port") from exc
    if port is not None and not 1 <= port <= 65535:
        raise UrlFetchError("Image URL contains an invalid port")

    host = parsed.hostname.rstrip(".").lower()
    allowed_hostnames = _parse_allowed_hosts(allowed_hosts)
    if host not in allowed_hostnames:
        raise UrlFetchError("Image URL host is not in the configured allowlist")

    try:
        addresses = [_ for _ in [host] if ipaddress.ip_address(host)]
    except ValueError:
        addresses = resolve_host(host)

    if not addresses or not all(_is_public_ip(address) for address in addresses):
        raise UrlFetchError("Image URL host resolves to a private or reserved address")


class ImageFetcher:
    def __init__(self, settings, client_factory: Callable[..., httpx.AsyncClient] | None = None):
        self.settings = settings
        self.client_factory = client_factory or httpx.AsyncClient

    @asynccontextmanager
    async def _client(self):
        async with self.client_factory(
            follow_redirects=False,
            timeout=self.settings.url_fetch_timeout_seconds,
            trust_env=False,
        ) as client:
            yield client

    async def fetch(self, url: str) -> bytes:
        validate_public_url(url, self.settings.url_allowed_hosts)

        async with self._client() as client:
            try:
                async with client.stream("GET", url) as response:
                    if 300 <= response.status_code < 400:
                        raise UrlFetchError("Image URL redirects are not allowed")
                    if response.status_code < 200 or response.status_code >= 300:
                        raise UrlFetchError("Image URL returned an unsuccessful response")

                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > self.settings.max_upload_bytes:
                        raise ImageTooLargeError("Remote image exceeds the maximum upload size")

                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > self.settings.max_upload_bytes:
                            raise ImageTooLargeError(
                                "Remote image exceeds the maximum upload size"
                            )
                        chunks.append(chunk)
            except ImageTooLargeError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                if isinstance(exc, UrlFetchError):
                    raise
                raise UrlFetchError("Unable to fetch image URL") from exc

        data = b"".join(chunks)
        try:
            validate_image_bytes(data, self.settings)
        except (ImageInputError, ImageTooLargeError) as exc:
            raise UrlFetchError("URL did not return a supported image") from exc
        return data
