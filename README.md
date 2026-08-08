# rembg + BiRefNet FastAPI 服务

这是一个使用 NVIDIA GPU 运行 `rembg`/`birefnet-general` 的背景移除 API。服务默认返回带透明通道的 PNG，并同时支持文件上传和公网图片 URL。

## 运行要求

- Docker Engine 或 Docker Desktop
- NVIDIA 驱动和 NVIDIA Container Toolkit
- `nvidia-smi` 能在宿主机看到 GPU
- 可用磁盘空间用于 CUDA 镜像和模型缓存

当前 Dockerfile 使用 CUDA 12.6、cuDNN 和 Python 3.12 系统包。宿主机 NVIDIA 驱动需要支持该 CUDA 运行时。

## 启动

PowerShell：

```powershell
Copy-Item .env.example .env
# 编辑 .env，把 API_KEY 换成随机长密钥
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f api
```

服务保留 `/health` 兼容探活；容器 healthcheck 使用 `/readyz`，并额外提供轻量级 `/livez`：

```powershell
curl http://localhost:8000/health
curl http://localhost:8000/livez
curl http://localhost:8000/readyz
```

`/health` 预期返回：

```json
{"status":"ok","model":"birefnet-general"}
```

`/readyz` 会在模型后端不可用时返回 `503`，用于区分“进程活着”与“推理已就绪”。

## Web UI

启动容器后打开 `http://localhost:8000/`。在页面填写 `.env` 中的 `API_KEY`，选择模型，然后可以选择本地图片或输入公网图片 URL。处理成功后页面会显示透明 PNG，并提供下载按钮。

API Key 只在当前页面请求中使用，不会保存到浏览器。

容器默认以非 root 用户 `appuser` 运行，模型缓存目录默认是 `MODEL_CACHE_DIR=/var/lib/rembg`，并通过 Docker Volume `rembg-model-cache` 挂载到同一路径。首次使用某个模型会写入该目录，后续请求会复用缓存。容器只启用一个 Uvicorn worker，避免同一张 GPU 重复加载模型。

## API 调用

### 上传文件

```powershell
$apiKey = (Get-Content .env | Where-Object { $_ -like 'API_KEY=*' }).Substring(8)
curl.exe -X POST http://localhost:8000/v1/remove-background `
  -H "X-API-Key: $apiKey" `
  -F "model=birefnet-portrait" `
  -F "file=@.\sample.jpg" `
  -o .\result.png
```

### 图片 URL

```powershell
$apiKey = (Get-Content .env | Where-Object { $_ -like 'API_KEY=*' }).Substring(8)
curl.exe -X POST http://localhost:8000/v1/remove-background/url `
  -H "X-API-Key: $apiKey" `
  -H "Content-Type: application/json" `
  -d '{"image_url":"https://example.com/product.jpg","model":"birefnet-general-lite"}' `
  -o .\result.png
```

### 查询可用模型

```powershell
curl.exe http://localhost:8000/v1/models
```

请求中的 `model` 字段可省略，省略时使用 `.env` 中的 `MODEL_NAME`。未知模型会返回 `400`。

URL 输入只允许 HTTP/HTTPS，并拒绝回环、私有、链路本地、保留地址和带用户凭据的 URL。服务不会跟随重定向，以降低 SSRF 风险。

要启用 URL 接口，必须把 `URL_ALLOWED_HOSTS` 配置为逗号分隔的精确主机名白名单；空值表示禁用 URL 输入，而不是“允许所有外链”。

## 配置

配置项见 `.env.example`。重点配置：

- `API_KEY`：必填；文件和 URL 接口都需要通过 `X-API-Key` 传入。
- `MODEL_NAME`：默认 `birefnet-general`。
- `MAX_UPLOAD_BYTES`：默认 20 MiB，限制图片内容本身大小。
- `MAX_REQUEST_BYTES`：默认 25 MiB，限制整个 multipart / HTTP 请求体大小，避免外围封装开销绕过上传限制。
- `MAX_IMAGE_PIXELS`：默认 25MP。
- `URL_ALLOWED_HOSTS`：逗号分隔的精确主机名白名单；为空时禁用 URL 下载。
- `RATE_LIMIT_PER_MINUTE`：默认每个 `X-API-Key` 每分钟 30 次，作用范围是当前进程内的受保护去背景接口。
- `MAX_PENDING_REQUESTS`：默认 4，表示当前进程内允许等待 GPU 执行槽位的额外请求数。
- `GPU_MAX_CONCURRENCY`：默认 1。显存不足时不要直接提高这个值。
- `MODEL_SESSION_CACHE_SIZE`：默认 2，同时缓存的模型 session 数量；模型越大，显存占用越高。
- `MODEL_CACHE_DIR`：默认 `/var/lib/rembg`，Dockerfile 中也会把 `U2NET_HOME` 指向同一路径。

> `slowapi` 和推理并发控制都是 process-local 的：如果未来改成多 worker 或多副本部署，需要在入口网关或共享存储/共享限流组件层面补齐全局限制。

## 验证

自动化验证不要求 GPU；CI 只跑测试、编译检查、Ruff 和 `docker compose config`：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app scripts
.\.venv\Scripts\python.exe -m ruff check app tests scripts
docker compose config
```

下面的 GPU 烟测是单独的手工验证，不属于 CI：

```powershell
docker compose up -d --build
nvidia-smi
python scripts/gpu_smoke_test.py --image .\sample.jpg
docker compose logs api
```

启动日志应显示 ONNX Runtime 选择 CUDA provider；如果日志只显示 CPU provider，应检查 NVIDIA Container Toolkit、驱动版本和 CUDA/cuDNN 兼容性。

## 错误码

- `401`：API Key 缺失或错误。
- `400`：图片格式、URL 或请求参数无效。
- `413`：图片超过大小或像素限制。
- `429`：超过当前进程的限流或推理排队能力。
- `500`：模型推理失败。

## 许可证

本项目服务代码使用 MIT 兼容方式组织。`rembg` 代码和具体模型权重的许可证是分开的；商业部署前请确认所下载的 BiRefNet checkpoint、依赖和数据授权条件。

