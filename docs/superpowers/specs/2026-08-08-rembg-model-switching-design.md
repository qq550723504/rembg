# rembg 模型动态切换设计规格

## 目标

让现有 API 和 Web UI 支持按单次请求选择 rembg 模型，同时保留 `.env` 中的默认模型和旧客户端兼容性。

## 用户与 API 流程

1. 前端加载 `GET /v1/models`，取得允许使用的模型列表和默认模型。
2. 用户在前端选择模型后提交本地文件或图片 URL。
3. 文件接口在 multipart 表单中接收可选 `model` 字段；URL 接口在 JSON 中接收可选 `model` 字段。
4. 未传 `model` 时使用 `Settings.model_name`；传入未知模型时返回 `400`，不触发模型加载或图片处理。
5. 服务按模型名称懒加载 rembg session，并在进程内缓存有限数量的 session；后续使用同一模型时复用 session。

## 支持范围

当前 rembg 版本提供的内置模型作为安全 allowlist：

```text
birefnet-general
birefnet-general-lite
birefnet-portrait
birefnet-dis
birefnet-hrsod
birefnet-cod
birefnet-massive
u2net
u2netp
u2net_human_seg
u2net_cloth_seg
isnet-general-use
isnet-anime
silueta
sam
bria-rmbg
```

不在 UI 或普通请求参数中暴露 `*_custom` 模型，因为它们需要额外的自定义模型路径或参数。allowlist 放在应用代码中，避免任意用户输入被当作模型标识加载。

## 后端设计

- 新增 `app/models.py`，集中保存内置模型 allowlist、默认模型解析和模型列表响应结构。
- `GET /v1/models` 无需 API Key；它只返回模型名称和默认值，不暴露密钥或文件信息。
- `POST /v1/remove-background` 增加 `model: str | None = Form(default=None)`。
- `POST /v1/remove-background/url` 的请求体增加 `model: str | None = None`。
- `RembgRemover` 将单 session 改为按模型名缓存的 session map，使用同一把锁保证懒加载安全；保留 CUDA 优先、CPU fallback 和并发信号量。
- 新增 `MODEL_SESSION_CACHE_SIZE` 配置，默认 `2`；达到上限时淘汰最久未使用的 session，降低多模型切换导致显存持续增长的风险。
- 健康检查继续报告默认模型，不因某个可选模型尚未加载而失败。

## 前端设计

- 输入区域增加模型下拉框 `id="model-select"`，显示模型名和简短用途说明。
- 页面加载时请求 `/v1/models` 并选中默认模型；加载失败时使用内置的 `birefnet-general` fallback，同时提示模型列表加载失败。
- 文件请求把选择值追加到 `FormData` 的 `model` 字段；URL 请求把选择值放到 JSON 的 `model` 字段。
- 切换模型只影响下一次请求，不持久化到 localStorage；API Key 仍只在当前页面使用。
- 处理期间模型选择器与其他输入一起禁用，防止请求参数在处理中改变。

## 错误处理与兼容性

- 未传模型：继续按 `.env` 默认模型处理。
- 未知模型：返回明确的 `400` 错误和允许模型列表摘要。
- 模型下载、初始化或推理失败：继续走现有的 `500 Background removal failed` 错误路径并记录服务端日志。
- 现有 `/health`、文件接口、URL 接口的认证方式和成功响应格式不变。

## 验证标准

- 自动化测试覆盖模型列表、默认模型、合法模型透传、非法模型拒绝、文件/URL 两种请求格式，以及旧请求不带模型时的兼容性。
- UI 静态测试确认模型选择器和请求端点存在。
- 浏览器验证模型下拉框加载、选择模型、提交请求以及成功展示结果。
- Docker 重建后健康检查、全量 pytest、GPU smoke test 通过；至少验证默认模型真实推理，模型切换 API 合同使用 fake remover 覆盖。
