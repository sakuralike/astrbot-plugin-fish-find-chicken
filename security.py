from __future__ import annotations

import asyncio
import ipaddress
import mimetypes
import socket
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import aiohttp
from PIL import Image as PillowImage
from PIL import UnidentifiedImageError


class SecurityError(ValueError):
    pass


@dataclass(frozen=True)
class ImageLimits:
    max_bytes: int = 10 * 1024 * 1024
    max_pixels: int = 20_000_000
    allowed_formats: tuple[str, ...] = ("PNG", "JPEG", "WEBP", "GIF", "BMP")


@dataclass(frozen=True)
class PreparedImage:
    path: Path
    data: bytes
    mime_type: str
    format: str
    width: int
    height: int


def _blocked_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    )


def _resolve_public_host(hostname: str) -> None:
    if not hostname or hostname.lower() in {"localhost", "localhost.localdomain"}:
        raise SecurityError("禁止访问本机地址")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        }
    except OSError as error:
        raise SecurityError("图片地址无法解析") from error
    if not addresses or any(_blocked_ip(address) for address in addresses):
        raise SecurityError("禁止访问内网或本机地址")


def validate_image_url(url: str, *, allow_http: bool = False) -> str:
    value = str(url or "").strip()
    parsed = urlsplit(value)
    schemes = {"https"} | ({"http"} if allow_http else set())
    if parsed.scheme.lower() not in schemes or not parsed.hostname:
        raise SecurityError("只允许安全的图片地址")
    _resolve_public_host(parsed.hostname)
    return value


def _mime_for_format(image_format: str) -> str:
    return {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
        "GIF": "image/gif",
        "BMP": "image/bmp",
    }.get(image_format.upper(), "application/octet-stream")


def prepare_image_bytes(
    data: bytes,
    destination_dir: str | Path,
    *,
    source_name: str = "image",
    limits: ImageLimits | None = None,
) -> PreparedImage:
    limits = limits or ImageLimits()
    if not isinstance(data, bytes) or not data:
        raise SecurityError("图片为空")
    if len(data) > limits.max_bytes:
        raise SecurityError("图片超过大小限制")
    destination = Path(destination_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"{uuid.uuid4().hex}-{Path(source_name).name or 'image'}"
    path.write_bytes(data)
    try:
        with PillowImage.open(path) as image:
            image_format = str(image.format or "").upper()
            if image_format not in {item.upper() for item in limits.allowed_formats}:
                raise SecurityError("图片格式不受支持")
            width, height = int(image.width), int(image.height)
            if width <= 0 or height <= 0 or width * height > limits.max_pixels:
                raise SecurityError("图片像素超过限制")
            image.verify()
        with PillowImage.open(path) as image:
            image.load()
    except SecurityError:
        path.unlink(missing_ok=True)
        raise
    except (OSError, ValueError, SyntaxError, UnidentifiedImageError) as error:
        path.unlink(missing_ok=True)
        raise SecurityError("图片内容无法验证") from error
    return PreparedImage(
        path=path,
        data=data,
        mime_type=_mime_for_format(image_format),
        format=image_format,
        width=width,
        height=height,
    )


async def download_image(
    url: str,
    destination_dir: str | Path,
    *,
    timeout: float = 20,
    max_redirects: int = 3,
    proxy: str | None = None,
    limits: ImageLimits | None = None,
) -> PreparedImage:
    current = validate_image_url(url)
    timeout_value = aiohttp.ClientTimeout(total=max(3.0, float(timeout)))
    async with aiohttp.ClientSession(timeout=timeout_value, trust_env=False) as session:
        for _ in range(max(0, int(max_redirects)) + 1):
            async with session.get(
                current,
                allow_redirects=False,
                proxy=proxy or None,
                headers={"Accept": "image/*"},
            ) as response:
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location", "")
                    if not location:
                        raise SecurityError("图片跳转地址为空")
                    current = validate_image_url(urljoin(current, location))
                    continue
                if response.status < 200 or response.status >= 300:
                    raise SecurityError("图片下载失败")
                body = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    body.extend(chunk)
                    if len(body) > (limits or ImageLimits()).max_bytes:
                        raise SecurityError("图片超过大小限制")
                return prepare_image_bytes(
                    bytes(body),
                    destination_dir,
                    source_name=Path(urlsplit(current).path).name or "image",
                    limits=limits,
                )
        raise SecurityError("图片跳转次数过多")


async def resolve_hostname_addresses(hostname: str) -> set[str]:
    return await asyncio.to_thread(
        lambda: {
            item[4][0]
            for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        }
    )
