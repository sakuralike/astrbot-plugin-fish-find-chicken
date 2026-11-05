from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from .security import ImageLimits, PreparedImage, SecurityError, download_image, prepare_image_bytes


class ImageInputError(ValueError):
    pass


def _is_image(component: object) -> bool:
    return type(component).__name__.lower() == "image" or hasattr(
        component, "convert_to_file_path"
    )


def _is_reply(component: object) -> bool:
    return type(component).__name__.lower() == "reply" or any(
        hasattr(component, key) for key in ("message_id", "reply_id")
    )


def find_images(messages: Iterable[object]) -> list[object]:
    return [item for item in messages if _is_image(item)]


def find_replies(messages: Iterable[object]) -> list[object]:
    return [item for item in messages if _is_reply(item)]


async def _component_path(component: object) -> str:
    for method_name in ("convert_to_file_path", "get_file"):
        method = getattr(component, method_name, None)
        if not callable(method):
            continue
        value = method()
        if inspect.isawaitable(value):
            value = await value
        if value:
            return str(value)
    for attr in ("file", "path", "url", "src", "image_url", "origin"):
        value = getattr(component, attr, None)
        if value:
            return str(value)
    return ""


def _reply_id(reply: object) -> str:
    for attr in ("message_id", "reply_id", "id"):
        value = getattr(reply, attr, None)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


async def _call_reply_fetcher(
    event: object, reply_id: str
) -> Iterable[object] | None:
    for name in ("get_reply_message", "get_message_by_id", "get_msg"):
        method = getattr(event, name, None)
        if not callable(method):
            continue
        result = method(reply_id)
        if inspect.isawaitable(result):
            result = await result
        if result is None:
            continue
        if isinstance(result, (list, tuple)):
            return result
        for attr in ("messages", "message", "chain", "get_messages"):
            value = getattr(result, attr, None)
            if callable(value):
                value = value()
            if inspect.isawaitable(value):
                value = await value
            if value is not None:
                return value
    return None


async def prepare_event_image(
    event: object,
    destination_dir: str | Path,
    *,
    limits: ImageLimits | None = None,
    reply_fetcher: Callable[[str], Awaitable[Iterable[object] | None]] | None = None,
    timeout: float = 20,
    proxy: str | None = None,
) -> PreparedImage:
    messages = []
    get_messages = getattr(event, "get_messages", None)
    if callable(get_messages):
        messages = list(get_messages() or [])
    images = find_images(messages)
    if len(images) > 1:
        raise ImageInputError("一次只能反查一张图片")
    component = images[0] if images else None
    if component is None:
        replies = find_replies(messages)
        if not replies:
            raise ImageInputError("请附上一张图片，或引用一条包含图片的消息")
        reply_images = find_images(getattr(replies[0], "chain", None) or [])
        if len(reply_images) == 1:
            component = reply_images[0]
        else:
            rid = _reply_id(replies[0])
            fetcher = reply_fetcher
            if fetcher is None:
                fetched = await _call_reply_fetcher(event, rid)
            else:
                fetched = await fetcher(rid)
            reply_images = find_images(fetched or [])
            if len(reply_images) != 1:
                raise ImageInputError("引用消息中没有唯一图片")
            component = reply_images[0]
    source = await _component_path(component)
    if not source:
        raise ImageInputError("图片消息无法读取")
    if source.startswith(("http://", "https://")):
        try:
            return await download_image(
                source,
                destination_dir,
                timeout=timeout,
                proxy=proxy,
                limits=limits,
            )
        except SecurityError as error:
            raise ImageInputError(str(error)) from error
    path = Path(source)
    if not path.is_file():
        raise ImageInputError("图片文件不存在")
    try:
        return prepare_image_bytes(
            path.read_bytes(),
            destination_dir,
            source_name=path.name,
            limits=limits,
        )
    except OSError as error:
        raise ImageInputError("图片文件无法读取") from error
