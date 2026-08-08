# rembg Model Switching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with review checkpoints.

**Goal:** 让 API 和 Web UI 支持按单次请求切换已允许的 rembg 模型，并对模型 session 做有限缓存。

**Architecture:** 新增一个不依赖 rembg 导入的模型注册模块，集中管理 allowlist、用途说明和默认模型解析。FastAPI 在文件 multipart 和 URL JSON 中接收可选 `model` 字段，并新增公开的 `/v1/models` 供 UI 加载；`RembgRemover` 使用有上限的 LRU session 缓存按模型懒加载推理会话。

**Tech Stack:** FastAPI/Pydantic、rembg session API、Python `OrderedDict`/threading、原生 HTML/JavaScript、pytest/TestClient、Docker Compose。

## Global Constraints

- 未传 `model` 时继续使用 `.env` 的 `MODEL_NAME`，旧客户端请求格式保持兼容。
- `GET /v1/models` 只返回 allowlist 和默认模型，不需要 API Key。
- 不暴露 `*_custom` 模型；普通请求不得通过任意字符串加载模型。
- `MODEL_SESSION_CACHE_SIZE` 默认 `2`，达到上限时淘汰最久未使用的 session。
- 文件接口使用 multipart 字段 `model`；URL 接口使用 JSON 字段 `model`。
- API Key、图片内容和模型选择不写入浏览器持久化存储。
- 现有成功响应仍为 `image/png`，认证和 SSRF 校验不变。

---

### Task 1: Add failing model registry and API contract tests

**Files:**
- Create: `tests/test_models.py`
- Modify: `tests/test_api.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: existing `client`, `authenticated_client`, `fake_remover`, `fake_fetcher` fixtures.
- Produces: tests defining `SUPPORTED_MODELS`, `resolve_model_name`, `/v1/models`, request-level model selection, invalid-model rejection, and the new cache-size setting.

- [ ] **Step 1: Extend fake remover and settings fixture for model-aware tests**

Change `FakeRemover` so it records `(data, model_name)` while still accepting the existing call shape:

```python
class FakeRemover:
    def __init__(self, output: bytes):
        self.output = output
        self.calls: list[tuple[bytes, str | None]] = []

    def remove(self, data: bytes, model_name: str | None = None) -> bytes:
        self.calls.append((data, model_name))
        return self.output
```

Add `model_session_cache_size=2` to the `settings` fixture.

- [ ] **Step 2: Write failing registry/config tests**

Create `tests/test_models.py`:

```python
import pytest

from app.models import SUPPORTED_MODELS, resolve_model_name


def test_resolve_model_name_uses_default_when_omitted():
    assert resolve_model_name(None, "birefnet-general") == "birefnet-general"


def test_resolve_model_name_accepts_supported_model():
    assert resolve_model_name("birefnet-portrait", "birefnet-general") == "birefnet-portrait"


def test_resolve_model_name_rejects_unknown_model():
    with pytest.raises(ValueError, match="Unsupported model"):
        resolve_model_name("made-up-model", "birefnet-general")


def test_supported_models_exclude_custom_entries():
    assert "u2net_custom" not in SUPPORTED_MODELS
    assert "birefnet-general" in SUPPORTED_MODELS
```

Add to `tests/test_config.py`:

```python
def test_settings_have_safe_model_cache_default():
    assert Settings(api_key="secret").model_session_cache_size == 2
```

- [ ] **Step 3: Write failing API model tests**

Append to `tests/test_api.py`:

```python
def test_models_endpoint_lists_default_and_supported_models(client):
    response = client.get("/v1/models")

    assert response.status_code == 200
    payload = response.json()
    assert payload["default_model"] == "birefnet-general"
    assert {item["name"] for item in payload["models"]} >= {"birefnet-general", "birefnet-portrait"}


def test_upload_passes_requested_model_to_remover(authenticated_client, fake_remover, png_bytes):
    response = authenticated_client.post(
        "/v1/remove-background",
        files={"file": ("input.png", png_bytes, "image/png")},
        data={"model": "birefnet-portrait"},
    )

    assert response.status_code == 200
    assert fake_remover.calls[-1][1] == "birefnet-portrait"


def test_url_passes_requested_model_to_remover(authenticated_client, fake_fetcher, fake_remover):
    response = authenticated_client.post(
        "/v1/remove-background/url",
        json={"image_url": "https://93.184.216.34/input.png", "model": "isnet-anime"},
    )

    assert response.status_code == 200
    assert fake_remover.calls[-1][1] == "isnet-anime"


def test_unknown_model_is_rejected_before_upload_processing(authenticated_client, fake_remover, png_bytes):
    response = authenticated_client.post(
        "/v1/remove-background",
        files={"file": ("input.png", png_bytes, "image/png")},
        data={"model": "made-up-model"},
    )

    assert response.status_code == 400
    assert "Unsupported model" in response.json()["detail"]
    assert fake_remover.calls == []
```

- [ ] **Step 4: Run the focused tests and confirm the expected failures**

```powershell
python -m pytest tests/test_models.py tests/test_api.py tests/test_config.py -q
```

Expected: import/route/config failures because the registry, endpoint, and setting do not exist yet.

- [ ] **Step 5: Commit the red tests**

```powershell
git add tests/test_models.py tests/test_api.py tests/test_config.py tests/conftest.py
git commit -m "test: define rembg model switching contract"
```

### Task 2: Implement the model registry and configuration

**Files:**
- Create: `app/models.py`
- Modify: `app/config.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: failing registry/config tests from Task 1.
- Produces: `SUPPORTED_MODELS`, `MODEL_DESCRIPTIONS`, `resolve_model_name(requested, default)`, `model_options(default)`, and `Settings.model_session_cache_size`.

- [ ] **Step 1: Implement the allowlist and resolver**

Create `app/models.py` with the exact public names:

```python
SUPPORTED_MODELS = (
    "birefnet-general", "birefnet-general-lite", "birefnet-portrait",
    "birefnet-dis", "birefnet-hrsod", "birefnet-cod", "birefnet-massive",
    "u2net", "u2netp", "u2net_human_seg", "u2net_cloth_seg",
    "isnet-general-use", "isnet-anime", "silueta", "sam", "bria-rmbg",
)

MODEL_DESCRIPTIONS = {
    "birefnet-general": "通用场景",
    "birefnet-general-lite": "轻量通用，显存占用更低",
    "birefnet-portrait": "人像",
    "birefnet-dis": "显著目标",
    "birefnet-hrsod": "高分辨率显著目标",
    "birefnet-cod": "隐蔽物体",
    "birefnet-massive": "复杂通用场景",
    "u2net": "通用 U²-Net",
    "u2netp": "轻量 U²-Net",
    "u2net_human_seg": "人体分割",
    "u2net_cloth_seg": "服装分割",
    "isnet-general-use": "通用 IS-Net",
    "isnet-anime": "动漫角色",
    "silueta": "轻量通用",
    "sam": "提示式分割",
    "bria-rmbg": "BRIA 背景移除",
}


def resolve_model_name(requested: str | None, default: str) -> str:
    name = (requested or default).strip()
    if name not in SUPPORTED_MODELS:
        raise ValueError(f"Unsupported model: {name}")
    return name


def model_options(default: str) -> list[dict[str, str | bool]]:
    return [{"name": name, "description": MODEL_DESCRIPTIONS[name], "is_default": name == default} for name in SUPPORTED_MODELS]
```

- [ ] **Step 2: Add cache-size setting and env example**

Add to `Settings`:

```python
model_session_cache_size: int = Field(default=2, ge=1)
```

Add to `.env.example`:

```env
MODEL_SESSION_CACHE_SIZE=2
```

- [ ] **Step 3: Run registry/config tests**

```powershell
python -m pytest tests/test_models.py tests/test_config.py -q
```

Expected: registry and setting tests pass.

- [ ] **Step 4: Commit the registry/config implementation**

```powershell
git add app/models.py app/config.py .env.example
git commit -m "feat: add rembg model registry"
```

### Task 3: Wire model selection into API endpoints

**Files:**
- Modify: `app/main.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: `resolve_model_name` and `model_options` from Task 2.
- Produces: `GET /v1/models`; optional `model` in file multipart and URL JSON; `remover.remove(data, model_name)` calls.

- [ ] **Step 1: Add request model field and route tests for the current behavior**

Extend `ImageUrlRequest`:

```python
model: str | None = Field(default=None)
```

Use `Form(default=None)` for the file endpoint’s `model` argument. The tests from Task 1 must remain red until the route and remover call are implemented.

- [ ] **Step 2: Implement model resolution and the models endpoint**

Inside `create_app`, add:

```python
@application.get("/v1/models")
async def models() -> dict[str, object]:
    return {"default_model": settings.model_name, "models": model_options(settings.model_name)}
```

At the start of each remove endpoint, resolve the requested model and convert `ValueError` to:

```python
raise HTTPException(status_code=400, detail=str(exc)) from exc
```

Then call `remover.remove(data, model_name)` after image validation. Preserve all existing auth, URL, image validation, and PNG response behavior.

- [ ] **Step 3: Run API tests and full tests**

```powershell
python -m pytest tests/test_api.py tests/test_models.py tests/test_config.py -q
python -m pytest -q
```

Expected: all tests pass; old requests without `model` still use `birefnet-general`.

- [ ] **Step 4: Commit API model selection**

```powershell
git add app/main.py tests/test_api.py
git commit -m "feat: expose per-request rembg model selection"
```

### Task 4: Add bounded model session caching

**Files:**
- Modify: `app/remover.py`
- Create: `tests/test_remover.py` additions or `tests/test_model_cache.py`

**Interfaces:**
- Consumes: `model_name` passed by API endpoints and `Settings.model_session_cache_size`.
- Produces: `RembgRemover.remove(data, model_name)` that lazily loads one session per model and evicts the least-recently-used session at the configured bound.

- [ ] **Step 1: Write failing cache behavior tests**

Add a focused fake-session test that injects a fake `rembg` module and asserts the same model loads once, a different model loads separately, and a cache size of `1` evicts the old model:

```python
def test_remover_caches_sessions_by_model_and_evicts_oldest(settings, png_bytes, monkeypatch):
    import sys
    from types import SimpleNamespace

    created = []

    def fake_new_session(model_name, providers):
        created.append(model_name)
        return object()

    def fake_remove(data, session, force_return_bytes):
        return png_bytes

    monkeypatch.setitem(sys.modules, "rembg", SimpleNamespace(new_session=fake_new_session, remove=fake_remove))
    settings.model_session_cache_size = 1
    remover = RembgRemover(settings)

    remover._remove_sync(png_bytes, "birefnet-general")
    remover._remove_sync(png_bytes, "birefnet-general")
    remover._remove_sync(png_bytes, "birefnet-portrait")
    remover._remove_sync(png_bytes, "birefnet-general")

    assert created == ["birefnet-general", "birefnet-portrait", "birefnet-general"]
```

Adapt the existing private helper signature only as needed to test real cache behavior; do not mock the public endpoint.

- [ ] **Step 2: Run the cache test and confirm it fails**

```powershell
python -m pytest tests/test_model_cache.py -q
```

Expected: failure because the remover currently has a single `_session` and does not accept a model name.

- [ ] **Step 3: Implement bounded LRU cache**

Use `OrderedDict[str, tuple[object, callable]]`, a session lock, and these rules:

```python
def _get_session(self, model_name):
    with self._session_lock:
        cached = self._sessions.pop(model_name, None)
        if cached is not None:
            self._sessions[model_name] = cached
            return cached
        session = new_session(model_name, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
        self._sessions[model_name] = (session, remove)
        while len(self._sessions) > self.settings.model_session_cache_size:
            self._sessions.popitem(last=False)
        return self._sessions[model_name]
```

`remove()` must call `_remove_sync(data, model_name)` through `asyncio.to_thread`; inference semaphore behavior remains unchanged. Keep a local reference to the selected session/function before invoking inference so eviction cannot invalidate an in-flight call.

- [ ] **Step 4: Run cache and full tests**

```powershell
python -m pytest tests/test_model_cache.py tests/test_remover.py -q
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit session caching**

```powershell
git add app/remover.py tests/test_model_cache.py
git commit -m "feat: cache rembg sessions by model"
```

### Task 5: Add the frontend model selector

**Files:**
- Modify: `app/static/index.html`
- Modify: `app/static/app.js`
- Modify: `app/static/styles.css`
- Modify: `tests/test_ui.py`

**Interfaces:**
- Consumes: `/v1/models` response `{default_model, models[]}` and endpoint `model` fields from Task 3.
- Produces: enabled `#model-select` whose selected value is sent on both request paths.

- [ ] **Step 1: Add failing static UI assertions**

Extend `test_static_assets_are_served`:

```python
assert 'id="model-select"' in client.get("/").text
assert "/v1/models" in javascript.text
assert '"model"' in javascript.text
```

Run `python -m pytest tests/test_ui.py -q` and confirm failure before editing UI files.

- [ ] **Step 2: Add the model selector markup and styles**

In `index.html`, add a labeled `<select id="model-select" required>` near the API Key field. In `styles.css`, style it consistently with `.text-input` and add `.model-hint` for the selected model description.

- [ ] **Step 3: Implement model list loading and request payloads**

In `app.js`, add:

```javascript
const modelSelect = document.querySelector("#model-select");
const modelHint = document.querySelector("#model-hint");
const fallbackModels = [{ name: "birefnet-general", description: "通用场景", is_default: true }];

function renderModels(payload) { /* create option elements, select payload.default_model, update #model-hint */ }

async function loadModels() {
  try {
    const response = await fetch("/v1/models");
    if (!response.ok) throw new Error("模型列表加载失败");
    renderModels(await response.json());
  } catch (_) {
    renderModels({ default_model: "birefnet-general", models: fallbackModels });
    setStatus("模型列表加载失败，已使用默认模型。", "error");
  }
}
```

Call `loadModels()` once after DOM references are ready. In the file branch append `body.append("model", modelSelect.value)`; in the URL branch send `{ image_url: imageUrl, model: modelSelect.value }`. Include `modelSelect` in `setBusy()` so it is disabled during processing.

- [ ] **Step 4: Run UI and full tests**

```powershell
python -m pytest tests/test_ui.py -q
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit frontend model selection**

```powershell
git add app/static/index.html app/static/app.js app/static/styles.css tests/test_ui.py
git commit -m "feat: add frontend rembg model selector"
```

### Task 6: Document, rebuild, and verify model switching

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: completed API/UI model selection.
- Produces: documented `.env` setting, API payload examples, healthy Docker deployment, and test evidence.

- [ ] **Step 1: Document the selector and API parameter**

Add a section describing the UI model selector, `MODEL_SESSION_CACHE_SIZE`, and these examples:

```powershell
$apiKey = (Get-Content .env | Where-Object { $_ -like 'API_KEY=*' }).Substring(8)
curl.exe -X POST http://localhost:8000/v1/remove-background `
  -H "X-API-Key: $apiKey" `
  -F "model=birefnet-portrait" `
  -F "file=@.\sample.jpg" `
  -o .\portrait-result.png
```

```powershell
$apiKey = (Get-Content .env | Where-Object { $_ -like 'API_KEY=*' }).Substring(8)
curl.exe -X POST http://localhost:8000/v1/remove-background/url `
  -H "X-API-Key: $apiKey" `
  -H "Content-Type: application/json" `
  -d '{"image_url":"https://example.com/product.jpg","model":"birefnet-general-lite"}' `
  -o .\result.png
```

- [ ] **Step 2: Run documentation and automated checks**

```powershell
git diff --check
python -m pytest -q
docker compose config
```

- [ ] **Step 3: Rebuild and restart Docker**

```powershell
docker compose build
docker compose up -d
```

Poll `docker compose ps` until the API is healthy.

- [ ] **Step 4: Verify model discovery and API contract**

```powershell
curl.exe -sS http://127.0.0.1:8000/v1/models
```

Expected: HTTP 200 with `default_model` and the allowlisted model names. Use the test API Key and a fake/test contract for invalid model rejection; do not download every model just to validate names.

- [ ] **Step 5: Verify the browser path**

In the open local browser, confirm the selector is populated, switch between `birefnet-general` and `birefnet-general-lite`, select the desired value, upload the sample image, and confirm the success result. Verify the selected model is disabled during processing and the result panel still works.

- [ ] **Step 6: Run the real GPU smoke test and final checks**

```powershell
$apiKey = (Get-Content .env | Where-Object { $_ -like 'API_KEY=*' }).Substring(8)
python scripts/gpu_smoke_test.py --base-url http://127.0.0.1:8000 --image C:\Users\Henry\Documents\Codex\2026-08-08\bang-2\work\rembg-sample.jpg --api-key $apiKey
python -m pytest -q
git diff --check
git status --short
```

Expected: GPU smoke test reports `GPU smoke test passed`, pytest is green, and only intentional tracked changes are present; do not push because no remote is configured.
