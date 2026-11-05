from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock

from astrbot_plugin_fish_find_chicken.engines import (
    search_engine,
    parse_saucenao,
    parse_tracemoe,
)


class EngineParserTests(unittest.TestCase):
    def test_parse_saucenao_links(self):
        html = (
            '<a href="https://x.com/demo_user/status/123">Demo User</a>'
            '<a href="https://saucenao.com/">ignored</a>'
        )
        result = parse_saucenao(html)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].account, "123")
        self.assertEqual(result[0].platform, "X/Twitter")

    def test_parse_tracemoe_json(self):
        payload = json.dumps(
            {
                "result": [
                    {
                        "filename": "episode-1.jpg",
                        "similarity": 0.91,
                        "video": "https://trace.moe/video.mp4",
                        "anilist": {"title": {"romaji": "Example"}},
                    }
                ]
            }
        )
        result = parse_tracemoe(payload)
        self.assertEqual(result[0].engine, "tracemoe")
        self.assertEqual(result[0].score, 0.91)

    def test_browser_engine_uses_injected_service(self):
        browser = type("Browser", (), {})()
        browser.search = AsyncMock(
            return_value=[{"url": "https://x.com/demo_user", "name": "Demo"}]
        )
        result = asyncio.run(
            search_engine(
                "lens",
                b"image",
                "image/png",
                browser=browser,
            )
        )
        self.assertEqual(result.engine, "lens")
        self.assertEqual(result.candidates[0].account, "demo_user")

    def test_browser_engine_without_service_is_skipped(self):
        result = asyncio.run(
            search_engine("lens", b"image", "image/png")
        )
        self.assertEqual(result.error, "browser_unavailable")

