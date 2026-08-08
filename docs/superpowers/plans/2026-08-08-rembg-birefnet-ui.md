# rembg BiRefNet Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with review checkpoints.

**Goal:** 为现有 rembg + BiRefNet FastAPI 服务增加一个同源、可直接使用的本地图片/图片 URL 抠图页面。

**Architecture:** FastAPI 返回 `app/static/index.html`，并通过 `StaticFiles` 提供 CSS/JavaScript。页面使用原生浏览器 API 调用现有的两个背景移除接口，不新增后端业务接口、不引入 Node 构建链；浏览器端负责预览、状态、错误显示和 PNG 下载。

**Tech Stack:** FastAPI `FileResponse`/`StaticFiles`、原生 HTML/CSS/JavaScript、pytest/TestClient、Docker Compose、in-app browser。

## Global Constraints

- UI 与 API 必须同源，访问入口为 `GET /`。
- 文件接口继续使用 `POST /v1/remove-background`、multipart 字段 `file`、请求头 `X-API-Key`。
- URL 接口继续使用 `POST /v1/remove-background/url`、JSON 字段 `image_url`、请求头 `X-API-Key`。
- API Key 不写入 localStorage、sessionStorage 或服务端持久化存储。
- URL 的公网地址校验和 SSRF 防护继续由后端负责。
- 页面不新增 React/Vite、Node 构建步骤或额外服务。
- 桌面端双列预览，窄屏单列；空闲、处理中、成功、失败状态必须可读且不只依赖颜色。

---

### Task 1: Add failing UI asset contract tests

**Files:**
- Create: `tests/test_ui.py`
- Test: `tests/test_ui.py`

**Interfaces:**
- Consumes: existing `client` fixture from `tests/conftest.py`.
- Produces: executable checks for `/`, `/static/styles.css`, `/static/app.js`, required form controls, and preserved API routes.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ui.py`:

```python
def test_homepage_serves_ui(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="api-key"' in response.text
    assert 'id="file-input"' in response.text
    assert 'id="url-input"' in response.text
    assert 'id="remove-button"' in response.text


def test_static_assets_are_served(client):
    css = client.get("/static/styles.css")
    javascript = client.get("/static/app.js")

    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert "drop-zone" in css.text
    assert javascript.status_code == 200
    assert javascript.headers["content-type"].startswith("text/javascript")
    assert "/v1/remove-background" in javascript.text
    assert "/v1/remove-background/url" in javascript.text


def test_existing_api_contract_remains_available(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["model"] == "birefnet-general"
```

- [ ] **Step 2: Run the focused tests and verify the expected failure**

Run:

```powershell
python -m pytest tests/test_ui.py -q
```

Expected: the homepage test fails with `404` because `/` and static assets are not yet mounted.

- [ ] **Step 3: Commit the red tests**

```powershell
git add tests/test_ui.py
git commit -m "test: define web ui asset contract"
```

### Task 2: Mount the FastAPI static UI

**Files:**
- Modify: `app/main.py`
- Create: `app/static/index.html`
- Create: `app/static/styles.css`
- Create: `app/static/app.js`

**Interfaces:**
- Consumes: `tests/test_ui.py` contract and existing API routes.
- Produces: `GET /` HTML, `/static/styles.css`, `/static/app.js`; browser elements with IDs `api-key`, `file-input`, `url-input`, `remove-button`, `drop-zone`, `original-preview`, `result-preview`, `download-button`, `status-message`.

- [ ] **Step 1: Add the minimal route and asset files**

In `app/main.py`, import `Path`, `FileResponse`, and `StaticFiles`, define a module-level `STATIC_DIR = Path(__file__).parent / "static"`, then inside `create_app` mount:

```python
application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@application.get("/", include_in_schema=False)
async def homepage() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
```

Create `index.html` with a semantic page containing:

- API Key password input `id="api-key"`.
- Two radio controls that switch between `file-panel` and `url-panel`.
- A drag-and-drop `<label id="drop-zone">` containing `input id="file-input" type="file" accept="image/*"`.
- URL input `id="url-input" type="url"`.
- Button `id="remove-button" type="submit"`.
- Status output `id="status-message" aria-live="polite"`.
- Two preview images with `id="original-preview"` and `id="result-preview"`.
- Hidden result panel with `id="result-panel"` and download link/button `id="download-button"`.
- `<link rel="stylesheet" href="/static/styles.css">` and `<script src="/static/app.js" defer></script>`.

Create `styles.css` with a responsive dark layout: the form card is centered with a max width, `.preview-grid` uses two columns above `760px` and one column below, `.drop-zone` has a visible focus/drag-over state, and status classes use both text and `aria-live`.

Create `app.js` with these concrete behaviors:

```javascript
const state = { source: "file", file: null, originalUrl: null, resultUrl: null };

function setStatus(message, kind = "idle") { /* update #status-message text and class */ }
function clearObjectUrl(key) { /* URL.revokeObjectURL for state[key], then null */ }
function setOriginalPreview(blobOrFile) { /* replace state.originalUrl and #original-preview.src */ }
async function parseError(response) { /* read JSON detail, else return status-based message */ }
async function removeBackground(event) {
  /* validate API key and selected source, disable form controls, fetch the correct endpoint,
     create a PNG blob URL, show #result-panel and restore controls in finally */
}
```

The file branch must append `state.file` to `FormData("file")`; the URL branch must send `JSON.stringify({ image_url: url })` with `Content-Type: application/json`. Both send `X-API-Key`. On success, set `download-button.href` to the result object URL and `download="removed-background.png"`.

- [ ] **Step 2: Run the focused tests and verify they pass**

Run:

```powershell
python -m pytest tests/test_ui.py -q
```

Expected: 3 passed.

- [ ] **Step 3: Run all automated tests**

```powershell
python -m pytest -q
```

Expected: all existing API, image, URL, remover, configuration, and UI tests pass.

- [ ] **Step 4: Commit the UI implementation**

```powershell
git add app/main.py app/static/index.html app/static/styles.css app/static/app.js
git commit -m "feat: add rembg web ui"
```

### Task 3: Document the browser entry point

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: the `/` route from Task 2.
- Produces: user-facing startup and UI usage instructions consistent with Docker Compose.

- [ ] **Step 1: Add a Web UI section**

Add after the startup/health instructions:

```markdown
## Web UI

启动容器后打开 `http://localhost:8000/`。在页面填写 `.env` 中的 `API_KEY`，然后可以选择本地图片或输入公网图片 URL。处理成功后页面会显示透明 PNG，并提供下载按钮。

API Key 只在当前页面请求中使用，不会保存到浏览器。
```

- [ ] **Step 2: Check documentation formatting**

```powershell
git diff --check
```

Expected: no output.

- [ ] **Step 3: Commit documentation**

```powershell
git add README.md
git commit -m "docs: document rembg web ui"
```

### Task 4: Rebuild and verify the visible browser flow

**Files:**
- Modify: none unless verification exposes a defect; any defect must first get a regression test.

**Interfaces:**
- Consumes: Docker Compose service and the local test image `C:\Users\Henry\Documents\Codex\2026-08-08\bang-2\work\rembg-sample.jpg`.
- Produces: evidence that the UI works through the actual browser and GPU-backed API.

- [ ] **Step 1: Rebuild and restart the service**

```powershell
docker compose build
docker compose up -d
docker compose ps
```

Expected: the `api` service is healthy and publishes `0.0.0.0:8000->8000/tcp`.

- [ ] **Step 2: Verify HTTP assets**

```powershell
curl.exe -I http://localhost:8000/
curl.exe -I http://localhost:8000/static/styles.css
curl.exe -I http://localhost:8000/static/app.js
```

Expected: all return HTTP 200.

- [ ] **Step 3: Verify the actual browser path**

Use the already-open in-app browser tab at `http://localhost:8000/` to confirm the page title and controls, switch to URL mode and back, fill the API Key, choose `rembg-sample.jpg`, click “开始抠图”, and wait for the success status. Confirm `#result-preview` has a PNG object URL and `#download-button` is visible with a download filename.

- [ ] **Step 4: Run the GPU smoke test and final test suite**

```powershell
python scripts/gpu_smoke_test.py --image C:\Users\Henry\Documents\Codex\2026-08-08\bang-2\work\rembg-sample.jpg --api-key change-me-to-a-long-random-secret
python -m pytest -q
```

Expected: GPU smoke test reports `GPU smoke test passed` and pytest passes.

- [ ] **Step 5: Review final diff and status**

```powershell
git diff --check
git status --short
git log --oneline -5
```

Expected: no whitespace errors; only intentional commits/files are present; no remote push or PR is attempted because this repository has no configured remote.
