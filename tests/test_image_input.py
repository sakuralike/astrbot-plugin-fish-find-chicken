from __future__ import annotations

import asyncio
import tempfile
import types
from pathlib import Path
from unittest import TestCase

from PIL import Image as PillowImage

from astrbot_plugin_fish_find_chicken.image_input import (
    ImageInputError,
    prepare_event_image,
)


class Image:
    def __init__(self, path):
        self.path = str(path)

    async def convert_to_file_path(self):
        return self.path


class Reply:
    def __init__(self, message_id, chain=None):
        self.message_id = message_id
        self.chain = chain or []


class ImageInputTests(TestCase):
    def test_current_message_image_is_prepared(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            PillowImage.new("RGB", (3, 2), "red").save(source)
            event = types.SimpleNamespace(get_messages=lambda: [Image(source)])
            prepared = asyncio.run(prepare_event_image(event, Path(directory) / "tmp"))
            self.assertEqual(prepared.format, "PNG")
            self.assertTrue(prepared.path.is_file())

    def test_reply_message_image_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.jpg"
            PillowImage.new("RGB", (3, 2), "blue").save(source)
            event = types.SimpleNamespace(get_messages=lambda: [Reply("m1")])

            async def fetch(reply_id):
                self.assertEqual(reply_id, "m1")
                return [Image(source)]

            prepared = asyncio.run(
                prepare_event_image(event, Path(directory) / "tmp", reply_fetcher=fetch)
            )
            self.assertEqual(prepared.format, "JPEG")

    def test_reply_chain_image_is_used_without_fetcher(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            PillowImage.new("RGB", (3, 2), "green").save(source)
            event = types.SimpleNamespace(
                get_messages=lambda: [Reply("m1", chain=[Image(source)])]
            )
            prepared = asyncio.run(
                prepare_event_image(event, Path(directory) / "tmp")
            )
            self.assertEqual(prepared.format, "PNG")

    def test_missing_image_is_rejected(self):
        event = types.SimpleNamespace(get_messages=lambda: [])
        with self.assertRaises(ImageInputError):
            asyncio.run(prepare_event_image(event, tempfile.mkdtemp()))
