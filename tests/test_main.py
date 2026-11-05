from __future__ import annotations

import importlib
import sys
import types
from unittest import TestCase
from unittest.mock import patch


def load_main():
    def decorator(*args, **kwargs):
        return lambda function: function

    modules = {
        "astrbot": types.ModuleType("astrbot"),
        "astrbot.api": types.ModuleType("astrbot.api"),
        "astrbot.api.event": types.ModuleType("astrbot.api.event"),
        "astrbot.api.message_components": types.ModuleType(
            "astrbot.api.message_components"
        ),
        "astrbot.api.star": types.ModuleType("astrbot.api.star"),
        "astrbot.core": types.ModuleType("astrbot.core"),
        "astrbot.core.utils": types.ModuleType("astrbot.core.utils"),
        "astrbot.core.utils.astrbot_path": types.ModuleType(
            "astrbot.core.utils.astrbot_path"
        ),
    }
    modules["astrbot.api"].AstrBotConfig = dict
    modules["astrbot.api"].logger = types.SimpleNamespace(
        exception=lambda *args, **kwargs: None
    )
    modules["astrbot.api.event"].AstrMessageEvent = object
    modules["astrbot.api.event"].MessageChain = list
    modules["astrbot.api.event"].filter = types.SimpleNamespace(
        command=decorator,
        on_astrbot_loaded=decorator,
    )
    modules["astrbot.api.message_components"].Plain = str
    modules["astrbot.api.star"].Context = object
    modules["astrbot.api.star"].Star = object
    modules["astrbot.core.utils.astrbot_path"].get_astrbot_data_path = lambda: "."
    with patch.dict(sys.modules, modules):
        return importlib.import_module("astrbot_plugin_fish_find_chicken.main")


class MainTests(TestCase):
    def test_command_parser_accepts_default_and_custom_names(self):
        module = load_main()
        self.assertTrue(module.parse_command("/鱼鱼找鸡"))
        self.assertTrue(module.parse_command("/鱼鱼找鸡 [图片]"))
        self.assertTrue(module.parse_command("鱼鱼找鸡"))
        self.assertTrue(module.parse_command("/反查图片", "反查图片"))
        self.assertFalse(module.parse_command("/其他"))

    def test_qq_official_scope_accepts_platform_type_alias(self):
        module = load_main()
        plugin = object.__new__(module.FishFindChickenPlugin)
        plugin.enabled = True
        plugin.allowed_groups = {"default_1905349550|qq_official|group-1"}
        event = types.SimpleNamespace(
            get_group_id=lambda: "group-1",
            get_platform_id=lambda: "default_1905349550",
            get_self_id=lambda: "qq_official",
            get_platform_name=lambda: "qq_official",
        )
        self.assertEqual(plugin._scope(event), "default_1905349550|qq_official|group-1")
