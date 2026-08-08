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

健康检查：

```powershell
curl http://localhost:8000/health
```

预期返回：

```json
{"status":"ok","model":"birefnet-general"}
```

首次请求会下载模型到 Docker Volume `rembg-model-cache`，后续重启会复用缓存。容器只启用一个 Uvicorn worker，避免同一张 GPU 重复加载模型。

## API 调用

### 上传文件

```powershell
curl.exe -X POST http://localhost:8000/v1/remove-background `
  -H "X-API-Key: change-me-to-a-long-random-secret" `
  -F "file=@.\sample.jpg" `
  -o .\result.png
```

### 图片 URL

```powershell
curl.exe -X POST http://localhost:8000/v1/remove-background/url `
  -H "X-API-Key: change-me-to-a-long-random-secret" `
  -H "Content-Type: application/json" `
  -d '{"image_url":"https://example.com/product.jpg"}' `
  -o .\result.png
```

URL 输入只允许 HTTP/HTTPS，并拒绝回环、私有、链路本地、保留地址和带用户凭据的 URL。服务不会跟随重定向，以降低 SSRF 风险。

## 配置

配置项见 `.env.example`。重点配置：

- `API_KEY`：必填；文件和 URL 接口都需要通过 `X-API-Key` 传入。
- `MODEL_NAME`：默认 `birefnet-general`。
- `MAX_UPLOAD_BYTES`：默认 20 MiB。
- `MAX_IMAGE_PIXELS`：默认 25MP。
- `GPU_MAX_CONCURRENCY`：默认 1。显存不足时不要直接提高这个值。

## 验证

本地单元测试不加载模型：

```powershell
python -m pytest -q
```

Compose 配置校验：

```powershell
docker compose config
```

真实 GPU 调用：

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
- `500`：模型推理失败。

## 许可证

本项目服务代码使用 MIT 兼容方式组织。`rembg` 代码和具体模型权重的许可证是分开的；商业部署前请确认所下载的 BiRefNet checkpoint、依赖和数据授权条件。
