"""외부 URL 다운로드. SSRF/크기/타임아웃 방어를 포함한다."""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {None, 80, 443}


class FetchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FetchResult:
    url: str
    content: bytes
    content_type: str

    @property
    def is_image(self) -> bool:
        return self.content_type.split(";")[0].strip().lower().startswith("image/")


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if addr.is_private or addr.is_loopback or addr.is_link_local:
        return False
    if addr.is_reserved or addr.is_multicast or addr.is_unspecified:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        return _is_public_ip(str(addr.ipv4_mapped))
    return True


def assert_safe_url(url: str) -> str:
    """SSRF 검사를 통과한 정규화 URL을 반환한다."""
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise FetchError(f"허용되지 않는 스킴입니다: {parts.scheme or '(없음)'}")
    if parts.username or parts.password:
        raise FetchError("URL에 인증 정보를 포함할 수 없습니다.")
    if not parts.hostname:
        raise FetchError("호스트가 없는 URL입니다.")
    try:
        port = parts.port
    except ValueError as exc:
        raise FetchError("포트 형식이 잘못되었습니다.") from exc
    # allow_private_network 는 로컬 개발/테스트 전용 스위치라 포트 제한도 함께 푼다.
    if not settings.allow_private_network:
        if port not in ALLOWED_PORTS:
            raise FetchError(f"허용되지 않는 포트입니다: {port}")
        try:
            infos = socket.getaddrinfo(parts.hostname, port or 443, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise FetchError(f"호스트를 찾을 수 없습니다: {parts.hostname}") from exc
        for info in infos:
            ip = info[4][0]
            if not _is_public_ip(ip):
                raise FetchError(f"내부 네트워크 주소로는 접근할 수 없습니다: {ip}")
    # ponytail: DNS rebinding(검사 후 재조회 시점의 IP 변경)까지는 막지 않는다.
    #           필요해지면 resolve된 IP로 직접 연결 + Host 헤더 고정으로 올린다.
    return urlunsplit(parts)


async def fetch(url: str, *, max_bytes: int | None = None) -> FetchResult:
    """리다이렉트를 직접 따라가며 매 홉마다 SSRF 검사를 수행한다."""
    max_bytes = max_bytes or settings.max_download_bytes
    current = assert_safe_url(url)
    headers = {"User-Agent": settings.user_agent, "Accept": "*/*"}

    async with httpx.AsyncClient(
        timeout=settings.http_timeout, follow_redirects=False, headers=headers
    ) as client:
        for _ in range(settings.max_redirects + 1):
            async with client.stream("GET", current) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise FetchError("리다이렉트 응답에 Location이 없습니다.")
                    current = assert_safe_url(str(response.url.join(location)))
                    continue

                if response.status_code >= 400:
                    raise FetchError(f"HTTP {response.status_code}: {current}")

                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise FetchError("응답이 허용 크기를 초과했습니다.")

                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise FetchError("응답이 허용 크기를 초과했습니다.")
                    chunks.append(chunk)

                return FetchResult(
                    url=str(response.url),
                    content=b"".join(chunks),
                    content_type=response.headers.get("content-type", ""),
                )

    raise FetchError("리다이렉트가 너무 많습니다.")
