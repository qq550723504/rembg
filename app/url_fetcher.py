import ipaddress
import socket
from collections.abc import Callable
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import aiohttp
from aiohttp.abc import AbstractResolver

from .image_io import ImageInputError, ImageTooLargeError, validate_image_bytes


class UrlFetchError(ValueError):
    """The URL is unsafe or could not be fetched as an image."""


def _parse_allowed_hosts(allowed_hosts: str) -> set[str]:
    hosts = {
        host.strip().rstrip(".").lower()
        for host in allowed_hosts.split(",")
        if host.strip()
    }
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


def _validated_url_parts(
    url: str,
    allowed_hosts: str,
    *,
    resolve_dns: bool,
) -> tuple[str, int | None]:
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

    if resolve_dns:
        try:
            addresses = [_ for _ in [host] if ipaddress.ip_address(host)]
        except ValueError:
            addresses = resolve_host(host)

        if not addresses or not all(_is_public_ip(address) for address in addresses):
            raise UrlFetchError("Image URL host resolves to a private or reserved address")
    return host, port


def validate_public_url(url: str, allowed_hosts: str = "") -> None:
    _validated_url_parts(url, allowed_hosts, resolve_dns=True)


class PinnedPublicResolver(AbstractResolver):
    def __init__(
        self,
        resolve_host_func: Callable[[str], list[str]] = resolve_host,
    ):
        self.resolve_host_func = resolve_host_func
        self._address_cache: dict[str, list[str]] = {}

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[dict[str, object]]:
        addresses = self._address_cache.get(host)
        if addresses is None:
            addresses = self._resolve_public_addresses(host)
            self._address_cache[host] = addresses

        return [
            {
                "hostname": host,
                "host": address,
                "port": port,
                "family": socket.AF_INET6 if ipaddress.ip_address(address).version == 6 else socket.AF_INET,
                "proto": 0,
                "flags": 0,
            }
            for address in addresses
        ]

    async def close(self) -> None:
        return None

    def _resolve_public_addresses(self, host: str) -> list[str]:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            addresses = self.resolve_host_func(host)
        else:
            addresses = [host]
        if not addresses or not all(_is_public_ip(address) for address in addresses):
            raise UrlFetchError("Image URL host resolves to a private or reserved address")
        return addresses


class ImageFetcher:
    def __init__(
        self,
        settings,
        session_factory: Callable[..., aiohttp.ClientSession] | None = None,
        resolver_factory: Callable[[], AbstractResolver] | None = None,
    ):
        self.settings = settings
        self.session_factory = session_factory or aiohttp.ClientSession
        self.resolver_factory = resolver_factory or PinnedPublicResolver

    @asynccontextmanager
    async def _client(self, url: str | None = None):
        connector = aiohttp.TCPConnector(
            resolver=self.resolver_factory(),
        )
        timeout = aiohttp.ClientTimeout(total=self.settings.url_fetch_timeout_seconds)
        async with self.session_factory(
            connector=connector,
            timeout=timeout,
            trust_env=False,
        ) as client:
            yield client

    async def fetch(self, url: str) -> bytes:
        _validated_url_parts(url, self.settings.url_allowed_hosts, resolve_dns=False)

        async with self._client(url) as client:
            try:
                async with client.get(url, allow_redirects=False) as response:
                    if 300 <= response.status < 400:
                        raise UrlFetchError("Image URL redirects are not allowed")
                    if response.status < 200 or response.status >= 300:
                        raise UrlFetchError("Image URL returned an unsuccessful response")

                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > self.settings.max_upload_bytes:
                        raise ImageTooLargeError("Remote image exceeds the maximum upload size")

                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        total += len(chunk)
                        if total > self.settings.max_upload_bytes:
                            raise ImageTooLargeError(
                                "Remote image exceeds the maximum upload size"
                            )
                        chunks.append(chunk)
            except ImageTooLargeError:
                raise
            except (aiohttp.ClientError, TimeoutError, OSError, ValueError) as exc:
                if isinstance(exc, UrlFetchError):
                    raise
                raise UrlFetchError("Unable to fetch image URL") from exc

        data = b"".join(chunks)
        try:
            validate_image_bytes(data, self.settings)
        except (ImageInputError, ImageTooLargeError) as exc:
            raise UrlFetchError("URL did not return a supported image") from exc
        return data

