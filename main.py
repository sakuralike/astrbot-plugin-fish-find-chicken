from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .browser_service import BrowserService
from .engines import BROWSER_ENGINES, HTTP_ENGINES, search_engine
from .image_input import ImageInputError, prepare_event_image
from .result_parser import format_results
from .security import ImageLimits, SecurityError


PLUGIN_ID = "astrbot_plugin_fish_find_chicken"
DEFAULT_COMMAND = "鱼鱼找鸡"
PRIVACY_NOTICE = "图片将发送到已启用的第三方反向搜索服务，仅返回公开搜索结果。"
NO_IMAGE_TEXT = "请附上一张图片，或引用一条包含图片的消息后再发送 /鱼鱼找鸡。"


def _as_bool(value: Any, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item).strip().lower() for item in value if str(item).strip()]


def _command(value: Any) -> str:
    value = str(value or DEFAULT_COMMAND).strip().lstrip("/")
    if not value or any(char.isspace() for char in value):
        return DEFAULT_COMMAND
    return value


def parse_command(text: str, command: str = DEFAULT_COMMAND) -> bool:
    raw = str(text or "").replace("\u3000", " ").strip()
    names = {DEFAULT_COMMAND.lower(), _command(command).lower()}
    if not raw:
        return False
    parts = raw.lstrip("/").split(None, 1)
    first = parts[0].lower()
    if first not in names:
        return False
    if len(parts) == 1:
        return True
    return parts[1].strip().lower() in {"[图片]", "[image]"}


def _message_id(event: AstrMessageEvent) -> str:
    message = getattr(event, "message_obj", None)
    return str(
        getattr(message, "message_id", None)
        or getattr(message, "id", None)
        or getattr(event, "unified_msg_origin", "")
    ).strip()


def _actor_key(event: AstrMessageEvent) -> str:
    return "|".join(
        [
            str(event.get_platform_id() or ""),
            str(event.get_self_id() or ""),
            str(event.get_group_id() or ""),
            str(event.get_sender_id() or ""),
        ]
    )


class FishCommandFilter(filter.CustomFilter):
    plugin: Any = None

    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
        plugin = type(self).plugin
        if plugin is None:
            return False
        if plugin._scope(event) is None:
            return False
        return parse_command(
            getattr(event, "message_str", "") or event.get_message_str(),
            plugin.command,
        )


class FishFindChickenPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.config = config
        self.enabled = _as_bool(config.get("enabled", False))
        self.command = _command(config.get("command", DEFAULT_COMMAND))
        self.allowed_groups = set(_as_list(config.get("allowed_groups", [])))
        self.cooldowns: dict[str, float] = {}
        self.active: set[str] = set()
        self.completed: dict[str, float] = {}
        self.temp_dir = (
            Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_ID / "tmp"
        )
        FishCommandFilter.plugin = self
        self._configure_command()

    def _configure_command(self) -> None:
        try:
            from astrbot.core.star.star_handler import star_handlers_registry

            handler = star_handlers_registry.get_handler_by_full_name(
                f"{__name__}_reverse_search"
            )
        except Exception:
            return
        if handler is None:
            return
        for event_filter in handler.event_filters:
            if hasattr(event_filter, "command_name"):
                aliases = set(getattr(event_filter, "alias", set()))
                event_filter.command_name = self.command
                event_filter.alias = aliases | {DEFAULT_COMMAND}
                event_filter._cmpl_cmd_names = None
                break

    def _scope(self, event: AstrMessageEvent) -> str | None:
        if not self.enabled:
            return None
        group_id = str(event.get_group_id() or "").strip()
        if not group_id:
            return None
        platform_id = str(event.get_platform_id() or "").strip()
        bot_id = str(event.get_self_id() or "").strip()
        candidates = {
            group_id,
            f"{platform_id}|{group_id}" if platform_id else "",
            f"{platform_id}|{bot_id}|{group_id}"
            if platform_id and bot_id
            else "",
        }
        if platform_id:
            candidates.add(f"{platform_id}|qq_official|{group_id}")
        if bot_id:
            candidates.add(f"{bot_id}|qq_official|{group_id}")
        candidates.discard("")
        if self.allowed_groups and "*" not in self.allowed_groups and not candidates.intersection(
            self.allowed_groups
        ):
            return None
        return f"{platform_id}|{bot_id}|{group_id}"

    async def _send_text(self, event: AstrMessageEvent, text: str) -> None:
        await event.send(MessageChain([Plain(str(text))]).use_markdown(False))

    def _stop_event(self, event: AstrMessageEvent) -> None:
        try:
            event.should_call_llm(False)
        except Exception:
            pass
        try:
            event.stop_event()
        except Exception:
            pass

    def _cooldown(self, key: str, seconds: int) -> bool:
        now = time.monotonic()
        self.cooldowns = {name: deadline for name, deadline in self.cooldowns.items() if deadline > now}
        if self.cooldowns.get(key, 0) > now:
            return True
        self.cooldowns[key] = now + max(0, int(seconds))
        return False

    async def _search_all(
        self,
        engines: list[str],
        image_bytes: bytes,
        mime_type: str,
        *,
        timeout: float,
        proxy: str,
        browser: BrowserService | None,
    ):
        http_engines = [engine for engine in engines if engine in HTTP_ENGINES]
        browser_engines = [engine for engine in engines if engine in BROWSER_ENGINES]
        results = []
        if http_engines:
            results.extend(
                await asyncio.gather(
                    *(
                        search_engine(
                            engine,
                            image_bytes,
                            mime_type,
                            timeout=timeout,
                            proxy=proxy,
                        )
                        for engine in http_engines
                    )
                )
            )
        for engine in browser_engines:
            results.append(
                await search_engine(
                    engine,
                    image_bytes,
                    mime_type,
                    timeout=timeout,
                    proxy=proxy,
                    browser=browser,
                )
            )
        return results

    @filter.on_astrbot_loaded()
    async def on_loaded(self) -> None:
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    @filter.custom_filter(FishCommandFilter, priority=100)
    async def reverse_search(self, event: AstrMessageEvent) -> None:
        if self._scope(event) is None:
            return
        self._stop_event(event)
        if not parse_command(
            getattr(event, "message_str", ""),
            self.command,
        ):
            return
        actor = _actor_key(event)
        message_key = hashlib.sha256(
            f"{actor}|{_message_id(event)}".encode("utf-8")
        ).hexdigest()
        if message_key in self.completed:
            await self._send_text(event, "这条图片反查指令已经处理过了。")
            return
        if self._cooldown(
            f"user:{actor}",
            int(self.config.get("cooldown_seconds", 30) or 30),
        ):
            await self._send_text(event, "反查操作过于频繁，请稍后再试。")
            return
        if self.active:
            await self._send_text(event, "当前已有图片反查任务，请稍后再试。")
            return
        self.active.add(message_key)
        prepared = None
        try:
            if _as_bool(self.config.get("privacy_notice", True), True):
                await self._send_text(event, PRIVACY_NOTICE)
            limits = ImageLimits(
                max_bytes=int(
                    self.config.get("max_image_bytes", 10 * 1024 * 1024)
                    or 10 * 1024 * 1024
                ),
                max_pixels=int(
                    self.config.get("max_pixels", 20_000_000) or 20_000_000
                ),
            )
            prepared = await prepare_event_image(
                event,
                self.temp_dir,
                limits=limits,
                timeout=float(self.config.get("timeout_seconds", 45) or 45),
                proxy=str(self.config.get("proxy", "") or ""),
            )
            engines = [
                engine
                for engine in _as_list(
                    self.config.get("engines", ["saucenao", "tracemoe", "iqdb"])
                )
                if engine in HTTP_ENGINES or engine in BROWSER_ENGINES
            ]
            if not engines:
                await self._send_text(event, "没有配置可用的反向搜索引擎。")
                return
            browser = None
            if (
                _as_bool(self.config.get("browser_enabled", True), True)
                and any(engine in BROWSER_ENGINES for engine in engines)
            ):
                browser = BrowserService(proxy=str(self.config.get("proxy", "") or ""))
            results = await asyncio.wait_for(
                self._search_all(
                    engines,
                    prepared.data,
                    prepared.mime_type,
                    timeout=float(
                        self.config.get("browser_timeout_seconds", 45) or 45
                    ),
                    proxy=str(self.config.get("proxy", "") or ""),
                    browser=browser,
                ),
                timeout=max(
                    5.0,
                    float(self.config.get("timeout_seconds", 45) or 45),
                ),
            )
            text = format_results(
                results,
                max_accounts=int(self.config.get("max_accounts", 3) or 3),
                strict_consensus=_as_bool(
                    self.config.get("strict_consensus", True), True
                ),
            )
            await self._send_text(event, text)
            self.completed[message_key] = time.monotonic() + 3600
        except asyncio.TimeoutError:
            await self._send_text(event, "反向图片搜索超时，请稍后再试。")
        except (ImageInputError, SecurityError) as error:
            await self._send_text(event, str(error))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("鱼鱼找鸡处理失败")
            await self._send_text(event, "反向图片搜索暂时不可用，请稍后再试。")
        finally:
            self.active.discard(message_key)
            if prepared is not None:
                try:
                    prepared.path.unlink(missing_ok=True)
                except OSError:
                    pass
