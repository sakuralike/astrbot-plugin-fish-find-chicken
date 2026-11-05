from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any


class BrowserUnavailable(RuntimeError):
    pass


class BrowserSearchError(RuntimeError):
    pass


class BrowserService:
    """Optional Playwright adapter.

    Engine-specific result parsing remains in engines.py. This class only
    owns browser lifecycle and returns a small, sanitized page snapshot.
    """

    def __init__(self, *, executable: str = "", proxy: str = ""):
        self.executable = str(executable or "").strip()
        self.proxy = str(proxy or "").strip()

    async def _playwright(self):
        try:
            from playwright.async_api import async_playwright
        except Exception as error:
            raise BrowserUnavailable("Playwright 未安装") from error
        return async_playwright

    async def search(
        self,
        engine: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        *,
        timeout: float = 45,
        proxy: str = "",
    ) -> dict[str, Any]:
        async_playwright = await self._playwright()
        proxy_value = proxy or self.proxy
        proxy_config = {"server": proxy_value} if proxy_value else None
        extension = {
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "image/bmp": ".bmp",
        }.get(mime_type, ".jpg")
        try:
            with tempfile.TemporaryDirectory(prefix="fish-browser-") as directory:
                image_path = Path(directory) / f"image{extension}"
                image_path.write_bytes(image_bytes)
                async with async_playwright() as playwright:
                    browser_type = playwright.chromium
                    launch_kwargs: dict[str, Any] = {"headless": True}
                    if proxy_config:
                        launch_kwargs["proxy"] = proxy_config
                    if self.executable:
                        launch_kwargs["executable_path"] = self.executable
                    browser = await browser_type.launch(**launch_kwargs)
                    try:
                        context = await browser.new_context()
                        page = await context.new_page()
                        page.set_default_timeout(max(3_000, int(timeout * 1000)))
                        result = await self._search_page(engine, page, str(image_path))
                        await context.close()
                        return result
                    finally:
                        await browser.close()
        except BrowserUnavailable:
            raise
        except asyncio.TimeoutError as error:
            raise BrowserSearchError("浏览器搜索超时") from error
        except Exception as error:
            raise BrowserSearchError("浏览器搜索失败") from error

    async def _search_page(self, engine: str, page: Any, image_path: str) -> dict[str, Any]:
        engine = str(engine).lower().strip()
        upload_urls = {
            "lens": "https://lens.google.com/",
            "yandex": "https://yandex.com/images/",
            "bing": "https://www.bing.com/visualsearch",
            "baidu": "https://graph.baidu.com/",
            "google": "https://images.google.com/",
        }
        url = upload_urls.get(engine)
        if not url:
            raise BrowserSearchError("不支持的浏览器引擎")
        await page.goto(url, wait_until="domcontentloaded")
        selectors = {
            "lens": "input[type=file]",
            "yandex": "input[type=file]",
            "bing": "input[type=file]",
            "baidu": "input[type=file]",
            "google": "input[type=file]",
        }
        await page.locator(selectors[engine]).first.set_input_files(image_path)
        await page.wait_for_load_state("domcontentloaded")
        links = await page.locator("a[href]").evaluate_all(
            "(items) => items.slice(0, 50).map((a) => ({title: a.innerText || a.title || '', url: a.href}))"
        )
        return {"engine": engine, "links": links}
