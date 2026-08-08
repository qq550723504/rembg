# rembg + BiRefNet FastAPI Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with review checkpoints.

**Goal:** Build a GPU-ready FastAPI service that accepts image uploads or image URLs and returns transparent PNG cutouts using rembg with the `birefnet-general` model.

**Architecture:** FastAPI calls a long-lived rembg session in-process. The API layer owns authentication, input limits, URL fetching, SSRF protection, and error mapping; the model layer owns session initialization and inference. Docker Compose exposes one NVIDIA GPU and persists the rembg model cache.

**Tech Stack:** Python 3.11, FastAPI, Pydantic Settings, Pillow, httpx, rembg GPU/ONNX Runtime, pytest, Docker Compose, NVIDIA Container Toolkit.

## Global Constraints

- Default model is `birefnet-general`.
- Successful responses are `image/png` with an alpha channel.
- API-key authentication uses the `X-API-Key` header on protected endpoints.
- Uploads default to 20 MiB and 25 megapixels maximum.
- URL fetching allows only HTTP/HTTPS and rejects loopback, private, link-local, and unspecified IP addresses.
- The service runs one Uvicorn worker per GPU to avoid duplicate model memory.
- The model cache is persisted at `/root/.u2net` in Docker.
- No user image is persisted after the request completes.

---

### Task 1: Create project scaffold and failing API contract tests

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `app/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_api.py`

**Interfaces:**
- Tests import `app.main.create_app` and construct an application with injected settings and a fake remover.
- The API contract is `GET /health`, `POST /v1/remove-background`, and `POST /v1/remove-background/url`.

- [ ] **Step 1: Write the failing tests**

  Add tests for:

  ```python
  def test_health_is_public(client):
      response = client.get("/health")
      assert response.status_code == 200
      assert response.json()["model"] == "birefnet-general"

  def test_upload_requires_api_key(client, png_bytes):
      response = client.post(
          "/v1/remove-background",
          files={"file": ("input.png", png_bytes, "image/png")},
      )
      assert response.status_code == 401

  def test_upload_returns_transparent_png(authenticated_client, png_bytes):
      response = authenticated_client.post(
          "/v1/remove-background",
          files={"file": ("input.png", png_bytes, "image/png")},
      )
      assert response.status_code == 200
      assert response.headers["content-type"] == "image/png"
      assert Image.open(BytesIO(response.content)).mode == "RGBA"

  def test_upload_too_large_returns_413(authenticated_client, png_bytes):
      oversized = png_bytes + b"x" * (20 * 1024 * 1024)
      response = authenticated_client.post(
          "/v1/remove-background",
          files={"file": ("input.png", oversized, "image/png")},
      )
      assert response.status_code == 413

  def test_url_endpoint_accepts_json(authenticated_client, fake_http_server):
      response = authenticated_client.post(
          "/v1/remove-background/url",
          json={"image_url": fake_http_server.url},
      )
      assert response.status_code == 200

  def test_url_endpoint_rejects_private_address(authenticated_client):
      response = authenticated_client.post(
          "/v1/remove-background/url",
          json={"image_url": "http://127.0.0.1/image.png"},
      )
      assert response.status_code == 400
  ```

  The fake remover must implement `remove(image_bytes: bytes) -> bytes` and return a deterministic RGBA PNG so tests exercise the real FastAPI path without requiring a GPU.

- [ ] **Step 2: Run tests and verify the failure is correct**

  Run:

  ```powershell
  python -m pytest tests/test_api.py -q
  ```

  Expected: collection fails because `app.main` and `create_app` do not exist yet. Fix only test setup errors; do not add production code before this expected failure.

- [ ] **Step 3: Add test dependencies and test fixtures only**

  Pin the test/runtime dependency ranges in `pyproject.toml`, configure pytest, and add fixtures for a small PNG, authenticated TestClient, and fake remover. Keep application imports lazy enough that tests do not initialize rembg.

- [ ] **Step 4: Re-run the tests**

  Run the same command and confirm it still fails for the missing application behavior rather than dependency or fixture errors.

- [ ] **Step 5: Commit the contract tests**

  ```powershell
  git add pyproject.toml .gitignore app tests
  git -c user.name=Codex -c user.email=codex@localhost commit -m "test: define background removal api contract"
  ```

### Task 2: Implement configuration, authentication, validation, and model abstraction

**Files:**
- Create: `app/config.py`
- Create: `app/auth.py`
- Create: `app/image_io.py`
- Create: `app/remover.py`

**Interfaces:**
- `Settings` exposes `api_key`, `model_name`, `max_upload_bytes`, `max_image_pixels`, `url_fetch_timeout_seconds`, `gpu_max_concurrency`, and `model_cache_dir`.
- `require_api_key(settings, supplied_key)` raises an HTTP 401 error for missing or mismatched keys.
- `validate_image_bytes(data, settings) -> None` raises a typed 400/413 error for unsupported, oversized, or over-pixel images.
- `BackgroundRemover.remove(data: bytes) -> bytes` returns PNG bytes with RGBA mode.
- `RembgRemover` creates one lazy session with the configured model and calls `rembg.remove` under an asyncio semaphore.

- [ ] **Step 1: Write the failing unit tests**

  Add tests for exact API-key matching, byte-size limits, pixel limits using Pillow-generated images, rejection of malformed bytes, and a fake remover returning RGBA PNG bytes. Assert that no rembg import or session creation happens when the fake remover is injected.

- [ ] **Step 2: Run the focused tests and verify RED**

  ```powershell
  python -m pytest tests/test_config.py tests/test_image_io.py tests/test_remover.py -q
  ```

  Expected: failures because the modules and classes are absent.

- [ ] **Step 3: Implement the minimal modules**

  Use `pydantic-settings` for environment parsing. Use `secrets.compare_digest` for API keys. Read image metadata with Pillow under a bounded byte buffer; do not trust the filename or content type alone. Convert rembg output to RGBA PNG before returning it. Select `CUDAExecutionProvider` first and `CPUExecutionProvider` second when creating the rembg session.

- [ ] **Step 4: Run focused tests and verify GREEN**

  ```powershell
  python -m pytest tests/test_config.py tests/test_image_io.py tests/test_remover.py -q
  ```

- [ ] **Step 5: Commit the model boundary**

  ```powershell
  git add app/config.py app/auth.py app/image_io.py app/remover.py tests/test_config.py tests/test_image_io.py tests/test_remover.py
  git -c user.name=Codex -c user.email=codex@localhost commit -m "feat: add secure image validation and rembg adapter"
  ```

### Task 3: Implement FastAPI endpoints and URL fetch protection

**Files:**
- Create: `app/url_fetcher.py`
- Create: `app/main.py`
- Modify: `tests/test_api.py`
- Create: `tests/test_url_fetcher.py`

**Interfaces:**
- `create_app(settings: Settings | None = None, remover: BackgroundRemover | None = None, fetcher: ImageFetcher | None = None) -> FastAPI`.
- `ImageFetcher.fetch(url: str) -> bytes` validates the URL before making the request, follows no redirects by default, enforces timeout and content-length/body limits, and returns image bytes.
- Endpoint handlers call `validate_image_bytes`, then `remover.remove`, and return a `Response` with media type `image/png`.

- [ ] **Step 1: Write failing URL and endpoint tests**

  Add tests that verify missing files return 400, invalid API keys return 401, valid upload returns the fake remover output, URL requests use the injected fetcher, private IPv4/IPv6 and DNS-resolved private hosts are rejected, redirects are rejected, and non-image response bodies are rejected.

- [ ] **Step 2: Run tests and verify RED**

  ```powershell
  python -m pytest tests/test_api.py tests/test_url_fetcher.py -q
  ```

  Expected: failures because `app.main` and `app.url_fetcher` are absent.

- [ ] **Step 3: Implement the endpoints and fetcher**

  Keep the file upload and URL input as separate endpoints so FastAPI can validate each request body unambiguously. Map typed validation/fetch errors to the status codes in the design. Ensure temporary bytes are held in memory only and that exceptions do not expose stack traces.

- [ ] **Step 4: Run all unit/API tests and verify GREEN**

  ```powershell
  python -m pytest -q
  ```

- [ ] **Step 5: Commit the service layer**

  ```powershell
  git add app/main.py app/url_fetcher.py tests/test_api.py tests/test_url_fetcher.py
  git -c user.name=Codex -c user.email=codex@localhost commit -m "feat: expose secure background removal endpoints"
  ```

### Task 4: Add CUDA Docker deployment and operational documentation

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `.dockerignore`
- Create: `README.md`

**Interfaces:**
- Container listens on port 8000.
- Compose passes through one NVIDIA GPU and mounts `rembg-model-cache` to `/root/.u2net`.
- Entrypoint runs `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1`.

- [ ] **Step 1: Add deployment smoke-test documentation**

  Document the expected commands before writing the files:

  ```powershell
  copy .env.example .env
  docker compose build
  docker compose up -d
  curl http://localhost:8000/health
  curl -X POST http://localhost:8000/v1/remove-background -H "X-API-Key: change-me" -F "file=@sample.jpg" -o result.png
  docker compose logs -f api
  ```

  State the prerequisites: Docker Desktop/Engine, NVIDIA Container Toolkit, and a host driver visible to `nvidia-smi`.

- [ ] **Step 2: Write deployment files**

  Use a CUDA/cuDNN runtime base, install Python 3.11 and `rembg[gpu,cli]`, set `PYTHONUNBUFFERED=1`, and define a Compose healthcheck. Do not use multiple Uvicorn workers. Keep `API_KEY` in `.env`, not in the image.

- [ ] **Step 3: Build and run static checks**

  ```powershell
  docker compose config
  python -m compileall app
  python -m pytest -q
  ```

- [ ] **Step 4: Commit deployment files**

  ```powershell
  git add Dockerfile docker-compose.yml .env.example .dockerignore README.md
  git -c user.name=Codex -c user.email=codex@localhost commit -m "chore: add gpu docker deployment"
  ```

### Task 5: Verify real GPU inference and final handoff

**Files:**
- Create: `scripts/gpu_smoke_test.py`
- Modify: `README.md`

**Interfaces:**
- `scripts/gpu_smoke_test.py` posts a local sample image to the running service and verifies the response is a valid RGBA PNG.

- [ ] **Step 1: Add the smoke test**

  The script must require `API_BASE_URL`, `API_KEY`, and an image path, send a multipart request, fail on non-200, and use Pillow to assert PNG/RGBA output.

- [ ] **Step 2: Run the container and smoke test**

  ```powershell
  docker compose up -d --build
  nvidia-smi
  python scripts/gpu_smoke_test.py --image .\sample.jpg
  docker compose logs api
  ```

  Confirm startup logs show the CUDA provider and the request returns a transparent PNG. If the environment cannot expose Docker GPU access, report that as a runtime prerequisite issue rather than claiming GPU validation passed.

- [ ] **Step 3: Run the final verification suite**

  ```powershell
  python -m pytest -q
  docker compose config
  git status --short
  ```

- [ ] **Step 4: Commit the smoke test and final documentation**

  ```powershell
  git add scripts/gpu_smoke_test.py README.md
  git -c user.name=Codex -c user.email=codex@localhost commit -m "test: add gpu inference smoke test"
  ```

## Self-review checklist

- The design requirements map to Tasks 1–5: API contract, security limits, model adapter, URL input, CUDA deployment, cache persistence, and GPU smoke test.
- No placeholder steps remain; every task identifies files, interfaces, tests, commands, and expected outcomes.
- The model name and endpoint paths are consistent across all tasks.
