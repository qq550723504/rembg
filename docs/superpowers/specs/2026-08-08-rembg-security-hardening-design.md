# rembg 安全与生产基础增强设计

## 目标

在保持现有文件上传、图片 URL、模型选择和透明 PNG 响应契约的前提下，降低公网部署时的 SSRF、资源耗尽和配置误用风险，并让健康检查能够区分进程存活与推理服务可用。

## 范围

本阶段包含：

- 图片 URL 的安全策略和下载行为收敛
- 上传请求的有界读取
- 使用成熟限流组件限制 API Key 的请求频率
- GPU 推理的最大排队长度和明确的超限错误
- 启动时模型配置校验
- `livez` / `readyz` 健康检查
- `MODEL_CACHE_DIR` 与 `U2NET_HOME` 的一致性
- 统一由 API 边界完成 RGBA PNG 归一化
- 单元测试、契约测试和 Docker/CI 校验入口

本阶段不包含：

- Redis、Celery、RabbitMQ 等分布式任务系统
- 批量任务、对象存储和 Webhook
- UI 重新设计
- 自动下载或遍历所有模型的真实 GPU 测试

## 设计决策

### 1. URL 下载安全

URL 输入默认采用拒绝优先策略：增加 `URL_ALLOWED_HOSTS` 配置。为空时 URL 接口返回明确的配置错误；配置后只允许精确主机名或其子域名规则中明确列出的主机。保留 HTTP/HTTPS、凭据拒绝、端口校验和公网地址校验。

HTTP 客户端不读取环境代理配置，下载过程继续禁止重定向，并把 URL 校验集中到 Fetcher 内部。为消除 DNS 校验与实际连接之间的 TOCTOU 窗口，Fetcher 使用成熟异步 HTTP 客户端的自定义 resolver：resolver 只解析一次目标主机，过滤非公网地址，并把通过校验的地址集合固定给连接器使用。TLS 仍使用原始主机名进行证书和 SNI 校验；不关闭证书验证，也不允许代理绕过地址策略。

该固定解析器只解决应用层 DNS 重绑定问题，不能替代生产网络出口控制。部署仍应通过容器出口网络策略禁止 RFC1918、链路本地、云元数据和其他内部网段。

### 2. 请求体和推理资源

上传接口使用 `UploadFile.read(max_upload_bytes + 1)`，超过图片文件限制立即返回 `413`，避免把整个上传文件一次性载入 Python 内存。应用层 ASGI middleware 在 multipart 解析前检查 `MAX_REQUEST_BYTES`：有 `Content-Length` 时立即拒绝，分块请求则在接收 body 时累计并在超过上限后停止转发。该值必须大于 `MAX_UPLOAD_BYTES` 以容纳 multipart 边界和字段开销；反向代理部署配置也应同步设置请求体大小上限。

推理层保留现有 GPU 并发信号量，并增加有限等待队列。队列满时返回 `429`，避免无限请求占用连接。API Key 限流使用成熟的 FastAPI/Starlette 限流组件；本阶段使用进程内存储，明确只适用于当前单进程部署。

### 3. 配置和健康检查

启动时使用同一套模型 allowlist 校验 `MODEL_NAME`，非法配置直接阻止服务启动。`MODEL_CACHE_DIR` 在启动时同步到 `U2NET_HOME`，且不再被 Dockerfile 中固定的环境变量静默覆盖。

保留公开的 `/health` 兼容行为，并新增：

- `GET /livez`：只表示进程和 HTTP 服务存活
- `GET /readyz`：表示配置有效、推理后端可用；未启用预热时允许模型保持懒加载，但必须报告 provider 状态

健康响应不泄露 API Key 或本地路径；推理失败仍使用已有错误响应格式。

### 4. 输出格式边界

`RembgRemover` 返回模型原始结果，API 路由统一负责 `ensure_rgba_png`。这样保留 FakeRemover 和未来其他推理后端的格式适配能力，同时避免真实请求重复解码和编码。

## 测试设计

新增或扩展测试覆盖：

- 空白 allowlist、允许主机、未允许主机、凭据、私网和重定向
- `trust_env=False` 传递给 HTTP 客户端
- 超过上传限制时只读取上限加一字节并返回 `413`
- 限流和推理队列达到上限时返回 `429`
- 非法默认模型在启动配置阶段失败
- `/livez` 和 `/readyz` 的状态及响应内容
- 自定义模型缓存目录同步到 `U2NET_HOME`
- 真实 remover 结果只经过一次 API 层 PNG 归一化

现有的 `python -m pytest -q`、`python -m compileall -q app scripts` 和 `docker compose config` 继续作为回归门槛。由于 CI 通常没有 NVIDIA GPU，真实模型调用保留为手动或自托管 GPU smoke test，不伪装成普通单元测试。

## 运行和兼容性约束

- 保持 `POST /v1/remove-background` 和 `POST /v1/remove-background/url` 的成功响应为 `image/png`。
- 保持 `X-API-Key` 认证字段和现有 API Key 错误码。
- 保持未传 `model` 时使用 `MODEL_NAME`。
- URL 接口在未配置允许主机时可能由原来的可用变为明确拒绝，这是有意的安全默认值。
- 限流为进程内状态；未来多副本部署必须迁移到网关或共享存储。
