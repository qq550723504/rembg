# rembg + BiRefNet Web UI 设计规格

## 目标

为现有 FastAPI 抠图服务增加一个同源、无需额外前端构建链的简单 Web UI，方便在浏览器中上传本地图片或输入图片 URL，调用现有背景移除接口，并下载透明 PNG 结果。

## 用户流程

1. 用户打开 `GET /`，看到图片抠图工作台。
2. 用户填写 API Key；页面只在当前页面内使用，不写入 localStorage 或服务端。
3. 用户选择本地图片，或切换到 URL 输入方式。
4. 页面展示原图预览和文件名/来源，并启用“开始抠图”。
5. 点击后显示处理中状态，分别调用现有的 `POST /v1/remove-background` 或 `POST /v1/remove-background/url`。
6. 成功后在结果区域展示透明背景 PNG，提供下载按钮；失败时展示可读错误信息。

## 方案与范围

采用 FastAPI 同源静态页面：

- `app/static/index.html`：页面结构和无障碍标签。
- `app/static/styles.css`：响应式深色工作台样式，包含上传区域、预览卡片、结果卡片和状态提示。
- `app/static/app.js`：文件选择、拖放、URL 模式、预览、API 调用、下载和错误处理。
- FastAPI 在 `/` 返回页面，并在 `/static` 提供静态资源。

不引入 React/Vite、Node 构建链或新的后端 API；既有 `/health`、`/v1/remove-background` 和 `/v1/remove-background/url` 的请求格式与认证行为保持不变。

## 页面结构

- 顶部：产品名称“抠图工作台”、模型说明“rembg + BiRefNet”。
- 主操作卡：API Key 输入、来源切换（本地文件/图片 URL）、文件拖放区或 URL 输入框、开始按钮。
- 结果区：原图与抠图结果并排展示；结果成功后显示 PNG 下载按钮。
- 状态区：空闲、处理中、成功、失败四种状态，使用文本和颜色传达状态，不依赖颜色 alone。

## 交互与错误处理

- 仅接受浏览器可预览的常见图片类型；选择文件后立即本地预览，不上传直到点击开始。
- 文件方式使用 `FormData` 的 `file` 字段；URL 方式发送 JSON 的 `image_url` 字段。
- 两种方式均发送 `X-API-Key`。
- 读取服务端 JSON `detail` 作为错误提示；非 JSON 或网络错误使用通用提示。
- 开始请求期间锁定输入和按钮，避免重复提交；完成或失败后恢复。
- 新结果会释放旧的 object URL，页面关闭前不保留服务端结果。
- 不保存 API Key、图片内容或结果到浏览器持久化存储。

## 响应式与安全边界

- 桌面端采用双列预览，窄屏自动变为单列。
- 页面与 API 同源，避免额外 CORS 配置。
- UI 不绕过现有 API Key 校验，也不新增代理下载能力。
- URL 输入继续由后端执行公网 URL 校验和 SSRF 防护；前端只负责格式提示和提交。

## 验证标准

- 自动化测试确认 `/`、`/static/styles.css`、`/static/app.js` 可访问，并保留现有 API 测试全部通过。
- 浏览器验证：页面加载、切换输入模式、填写 API Key、选择测试图片、提交抠图、展示透明 PNG、下载结果。
- Docker Compose 重建后，浏览器访问 `http://localhost:8000/` 可用。
