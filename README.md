# 鱼鱼找鸡

独立 AstrBot 反向图片搜索插件。群员发送 `/鱼鱼找鸡` 并附带图片，或引用一条含图消息，插件会把图片发送到已启用的第三方搜索引擎，并返回公开候选账号、平台和来源链接。

## 使用

```text
/鱼鱼找鸡
```

图片可以直接附在当前消息中，也可以先引用一条有图片的消息，再发送命令。插件默认启用 `saucenao`、`tracemoe` 和 `iqdb`；Google Lens、Yandex、Bing、百度和 Google 等浏览器引擎可以在配置中启用，但需要 Playwright Chromium。

## 隐私

图片会发送到配置中启用的第三方反向搜索服务。不要使用包含人脸、私人聊天、证件或其他敏感内容的图片。插件默认只回复文字账号和来源链接，不转发第三方搜索图片。

## 配置

- `enabled`：插件总开关，默认关闭。
- `allowed_groups`：完整群范围白名单，空列表允许所有群。
- `command`：主命令，默认 `鱼鱼找鸡`；默认命令始终保留。
- `engines`：搜索引擎列表。
- `strict_consensus`：多个引擎结果不一致时过滤低可信候选。
- `cooldown_seconds`：单用户冷却，默认 30 秒。
- `timeout_seconds`：单次搜索超时，默认 45 秒。
- `max_image_bytes`：单图最大 10 MiB。
- `max_pixels`：默认最大 20,000,000 像素。
- `proxy`：外部搜索代理。
- `browser_enabled`：是否允许浏览器引擎。

## 浏览器引擎

安装 Python 依赖后，在服务器执行：

```bash
python -m playwright install chromium
```

浏览器不可用时，插件仍会使用 HTTP 引擎，不会因为浏览器缺失而让整个命令失败。

## 安全和数据

图片只在插件临时目录中处理，搜索完成、异常或取消后清理。插件不保存 Cookie、浏览器登录状态、API Key 或原始群图片。

目标 AstrBot 版本为 `>=4.29.3,<5`，支持 `aiocqhttp` 和 `qq_official`。
