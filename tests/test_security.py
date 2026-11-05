from __future__ import annotations

import io
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from PIL import Image

from astrbot_plugin_fish_find_chicken.security import (
    ImageLimits,
    SecurityError,
    prepare_image_bytes,
    validate_image_url,
)


class SecurityTests(TestCase):
    def test_prepare_image_bytes_validates_real_format(self):
        stream = io.BytesIO()
        Image.new("RGB", (4, 3), "red").save(stream, format="PNG")
        with tempfile.TemporaryDirectory() as directory:
            prepared = prepare_image_bytes(
                stream.getvalue(), directory, limits=ImageLimits(max_pixels=20)
            )
            self.assertEqual(prepared.format, "PNG")
            self.assertEqual((prepared.width, prepared.height), (4, 3))
            self.assertTrue(prepared.path.is_file())

    def test_prepare_image_bytes_rejects_oversized_image(self):
        with self.assertRaises(SecurityError):
            prepare_image_bytes(b"x" * 20, tempfile.mkdtemp(), limits=ImageLimits(max_bytes=10))

    def test_private_and_http_urls_are_rejected(self):
        with self.assertRaises(SecurityError):
            validate_image_url("http://127.0.0.1/image.png")
        with self.assertRaises(SecurityError):
            validate_image_url("file:///etc/passwd")
        with patch(
            "astrbot_plugin_fish_find_chicken.security.socket.getaddrinfo",
            return_value=[(None, None, None, None, ("127.0.0.1", 0))],
        ):
            with self.assertRaises(SecurityError):
                validate_image_url("https://example.test/image.png")
