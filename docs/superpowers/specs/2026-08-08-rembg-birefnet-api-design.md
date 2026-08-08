# rembg + BiRefNet FastAPI 服务设计

## 目标

交付一个可用 NVIDIA GPU 部署的背景移除 HTTP 服务。服务使用 `rembg` 作为推理封装，默认加载 `birefnet-general` 模型，由 FastAPI 提供统一、可鉴权的 API。

交付物包括 Dockerfile、Docker Compose 配置、环境变量示例、自动化测试和运行文档。

## 架构

```text
客户端
  |
  v
FastAPI 网关
  |-- API Key 鉴权
  |-- 文件/URL 输入校验
  |-- URL SSRF 防护
  |-- 大小、像素、超时限制
  v
rembg session(birefnet-general)
  |-- CUDAExecutionProvider
  |-- CPUExecutionProvider fallback
  v
透明 PNG
```

FastAPI 进程直接调用 `rembg` Python API，而不再额外代理一个 rembg HTTP 服务。这样可以复用长期存活的模型 session，减少网络跳转和重复初始化。默认只运行一个 Uvicorn worker，避免每个 worker 重复占用 GPU 显存。

## API

### `GET /health`

不要求 API Key，返回服务存活状态和当前模型名称。健康检查不触发图片推理。

### `POST /v1/remove-background`

使用 `multipart/form-data` 上传字段 `file`。需要 `X-API-Key` 请求头。成功时返回 `image/png`，图片保留原尺寸并带透明 alpha 通道。

### `POST /v1/remove-background/url`

使用 JSON：

```json
{"image_url":"https://example.com/input.jpg"}
```

需要 `X-API-Key`。服务只允许 HTTP/HTTPS，并拒绝 localhost、回环地址、私有网段、链路本地地址和无效端口，防止 SSRF。下载有连接/读取超时和响应大小限制，下载内容仍会执行图片格式和像素数校验。

## 配置

通过环境变量配置：

- `API_KEY`：必填的服务鉴权密钥。
- `MODEL_NAME`：默认 `birefnet-general`。
- `MAX_UPLOAD_BYTES`：默认 20 MiB。
- `MAX_IMAGE_PIXELS`：默认 25 megapixels。
- `URL_FETCH_TIMEOUT_SECONDS`：默认 15 秒。
- `GPU_MAX_CONCURRENCY`：默认 1，控制单 GPU 同时推理数。
- `MODEL_CACHE_DIR`：模型缓存目录，挂载 Docker volume 持久化。

## GPU 部署

Docker 镜像安装 CUDA 版 ONNX Runtime，并通过 Compose 的 NVIDIA GPU 配置暴露 GPU。容器启动时使用 CUDA provider；若 CUDA provider 不可用则回退 CPU，健康检查仍会暴露服务状态。生产环境应在启动日志中确认实际 provider，避免误以为正在使用 GPU。

模型缓存挂载到 `/root/.u2net`，容器重启后不重复下载模型。默认不启用多 worker；需要扩容时按 GPU 数量增加服务副本。

## 错误处理

- 缺少或错误 API Key：`401`。
- 缺少文件、无效 URL、格式不支持：`400`。
- 文件太大或像素数超限：`413`。
- URL 获取超时或非 2xx：`400`。
- 推理失败：`500`，不返回内部堆栈。

响应错误统一为：

```json
{"detail":"human-readable message"}
```

## 测试策略

先写测试并验证失败，再实现：

1. 健康检查不需要 API Key。
2. 保护接口缺少或错误 API Key 时返回 `401`。
3. 合法 PNG 上传返回 PNG，并包含 alpha 通道。
4. URL 接口可以处理合法图片 URL。
5. URL 接口拒绝本机和私有网络地址。
6. 超出大小限制的上传返回 `413`。
7. 模型初始化和推理通过依赖注入隔离，单元测试不需要真实 GPU；另提供可选 GPU smoke test 命令验证真实模型。

## 许可证注意事项

`rembg` 项目代码为 MIT，但模型权重有各自的授权条件。默认使用的 BiRefNet 代码仓库标为 MIT；实际商业部署前仍应确认下载的具体 checkpoint 和其依赖许可。不要未经授权把 BRIA RMBG 权重当作商业许可模型使用。
