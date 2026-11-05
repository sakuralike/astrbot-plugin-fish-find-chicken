from __future__ import annotations

import asyncio
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from astrbot_plugin_fish_find_chicken.browser_service import (
    BrowserService,
    BrowserUnavailable,
)


class BrowserServiceTests(IsolatedAsyncioTestCase):
    async def test_missing_playwright_is_reported_without_network(self):
        with patch(
            "astrbot_plugin_fish_find_chicken.browser_service.BrowserService._playwright",
            side_effect=BrowserUnavailable("missing"),
        ):
            with self.assertRaises(BrowserUnavailable):
                await BrowserService().search("lens", "image.png")
