from __future__ import annotations

import hashlib
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.config import Settings


class ScrapeError(RuntimeError):
    pass


@dataclass
class ScrapeResult:
    requested_url: str
    final_url: str
    status_code: int
    html: str
    content_hash: str


PRIVATE_NETS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def _is_private_ip(ip: str) -> bool:
    parsed = ipaddress.ip_address(ip)
    if parsed.is_private or parsed.is_loopback or parsed.is_link_local or parsed.is_multicast:
        return True
    return any(parsed in network for network in PRIVATE_NETS)


def _assert_public_hostname(hostname: str) -> None:
    try:
        addresses = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ScrapeError(f"Could not resolve hostname: {hostname}") from exc

    for entry in addresses:
        ip = entry[4][0]
        if _is_private_ip(ip):
            raise ScrapeError("Private or local addresses are blocked for scraping")


def validate_scrape_url(url: str, settings: Settings) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ScrapeError("Only HTTP/HTTPS URLs are allowed")

    if not parsed.hostname:
        raise ScrapeError("URL hostname is missing")

    if not settings.is_domain_allowed(parsed.hostname):
        raise ScrapeError(
            "Domain is not in SCRAPE_ALLOWLIST. Add it in env/config before ingestion."
        )

    _assert_public_hostname(parsed.hostname)


async def fetch_html(url: str, settings: Settings) -> ScrapeResult:
    validate_scrape_url(url, settings)

    timeout = httpx.Timeout(
        connect=settings.scrape_timeout_seconds,
        read=settings.scrape_timeout_seconds,
        write=10,
        pool=10,
    )

    headers = {
        "User-Agent": "ManuIDBot/1.0 (+procurement-intelligence)",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        response = await client.get(url)

    final_host = urlparse(str(response.url)).hostname
    if not final_host:
        raise ScrapeError("Could not resolve final redirected host")

    if not settings.is_domain_allowed(final_host):
        raise ScrapeError("Redirected host is not in SCRAPE_ALLOWLIST")

    _assert_public_hostname(final_host)

    if response.status_code >= 400:
        raise ScrapeError(f"Source returned HTTP {response.status_code}")

    content_type = response.headers.get("content-type", "").lower()
    if "html" not in content_type and "xml" not in content_type:
        raise ScrapeError(f"Unsupported content-type: {content_type or 'unknown'}")

    content = response.text
    if len(content.encode("utf-8")) > settings.scrape_max_html_bytes:
        raise ScrapeError("HTML payload exceeds SCRAPE_MAX_HTML_BYTES")

    return ScrapeResult(
        requested_url=url,
        final_url=str(response.url),
        status_code=response.status_code,
        html=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )
