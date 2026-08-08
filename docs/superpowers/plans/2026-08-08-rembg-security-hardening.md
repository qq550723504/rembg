# rembg Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the rembg API against URL SSRF, oversized requests, unbounded GPU work, and misleading readiness while preserving existing API success and authentication contracts.

**Architecture:** Keep the current single-process FastAPI and in-process model session design. Add configuration validation and health state at the application boundary, a focused URL policy inside `ImageFetcher`, a bounded asynchronous inference gate inside `RembgRemover`, and the mature `slowapi` limiter for per-API-key request frequency. Keep arbitrary URL fetching disabled unless an explicit host allowlist is configured.

**Tech Stack:** Python 3.11+, FastAPI, Starlette, Pydantic Settings, aiohttp, Pillow, rembg, slowapi, pytest, Docker Compose, GitHub Actions.

## Global Constraints

- Preserve `POST /v1/remove-background` and `POST /v1/remove-background/url` successful responses as `image/png`.
- Preserve the `X-API-Key` header and existing `401` behavior for protected endpoints.
- Preserve omitted `model` behavior: use `MODEL_NAME`.
- Keep `/health` public and backward-compatible; add `/livez` and `/readyz` without removing it.
- URL input is rejected when `URL_ALLOWED_HOSTS` is empty; redirects remain disabled.
- URL fetching must pin the validated DNS result through the HTTP connector while retaining TLS hostname verification.
- `MAX_REQUEST_BYTES` is enforced before multipart parsing by ASGI middleware; bounded file reads remain a second layer.
- API-key rate limiting applies only after successful authentication and shares one scope across both removal routes.
- The inference queue is process-local and bounded; distributed deployments must use a gateway/shared limiter later.
- Every production-code behavior change must have a failing test before implementation.

---

### Task 1: Validate configuration and normalize the model cache directory

**Files:**
- Modify: `app/config.py`
- Modify: `app/models.py`
- Modify: `app/remover.py`
- Modify: `app/main.py`
- Modify: `.env.example`
- Modify: `tests/test_config.py`
- Modify: `tests/test_remover.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- `Settings` produces `url_allowed_hosts: str`, `rate_limit_per_minute: int`, `max_pending_requests: int`, `max_request_bytes: int`, and existing limits.
- `resolve_model_name()` remains the single model allowlist function.
- `RembgRemover` sets `U2NET_HOME` from `settings.model_cache_dir` before importing rembg.
- `create_app(settings=...)` rejects an invalid default model with a `ValueError` during application construction.

- [ ] **Step 1: Write failing configuration tests**

  Add tests asserting default values, positive validation for `RATE_LIMIT_PER_MINUTE` and `MAX_PENDING_REQUESTS`, and rejection of zero/negative values.

- [ ] **Step 2: Run configuration tests and verify the expected failure**

  Run `python -m pytest tests/test_config.py -q`.
  Expected: failures because the new settings fields do not exist.

- [ ] **Step 3: Implement the new settings fields**

  Add:

  ```python
  url_allowed_hosts: str = ""
  rate_limit_per_minute: int = Field(default=30, ge=1)
  max_pending_requests: int = Field(default=4, ge=0)
  ```

  Add the same names and defaults to `.env.example`.

- [ ] **Step 4: Write failing tests for invalid default model and cache directory**

  Assert `create_app(settings=Settings(api_key="secret", model_name="unknown"), ...)` raises `ValueError`, and assert `_get_session()` sets `os.environ["U2NET_HOME"]` to the configured cache directory when the environment is initially unset.

- [ ] **Step 5: Run the focused tests and verify the expected failure**

  Run `python -m pytest tests/test_api.py tests/test_remover.py -q`.
  Expected: the invalid-model and cache-directory assertions fail before implementation.

- [ ] **Step 6: Implement startup validation and cache normalization**

  Validate `settings.model_name` with `resolve_model_name(None, settings.model_name)` in `create_app()` before constructing the remover. In `RembgRemover`, assign `os.environ["U2NET_HOME"] = self.settings.model_cache_dir` once before the first session load instead of using `setdefault`.

- [ ] **Step 7: Run the focused tests and commit**

  Run `python -m pytest tests/test_config.py tests/test_api.py tests/test_remover.py -q`.
  Commit with `git add app/config.py app/models.py app/remover.py app/main.py .env.example tests/test_config.py tests/test_remover.py tests/test_api.py && git -c user.name="wei xu" -c user.email="xuweixia@live.com" commit -m "fix: validate rembg runtime configuration"`.

### Task 2: Harden URL fetching and bound upload reads

**Files:**
- Modify: `app/url_fetcher.py`
- Modify: `app/main.py`
- Modify: `app/config.py`
- Modify: `.env.example`
- Modify: `tests/test_url_fetcher.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- `ImageFetcher.fetch(url: str) -> bytes` owns URL validation exactly once.
- `validate_public_url(url, allowed_hosts: str = "")` rejects empty allowlists, credentials, non-HTTP(S), private/reserved addresses, and hosts outside the configured allowlist.
- Upload handling reads at most `settings.max_upload_bytes + 1` bytes before returning `413`.

- [ ] **Step 1: Write failing URL-policy tests**

  Add tests for an empty allowlist, an allowed exact host, a disallowed host, and a client factory receiving `trust_env=False`. Keep the existing private-address and redirect tests.

- [ ] **Step 2: Run URL tests and verify the expected failure**

  Run `python -m pytest tests/test_url_fetcher.py -q`.
  Expected: new allowlist and `trust_env` assertions fail.

- [ ] **Step 3: Implement the explicit host policy and client setting**

  Parse comma-separated exact hostnames, compare normalized lowercase hostnames without implicit wildcard or subdomain inheritance, retain public-IP validation, remove the route-level duplicate `validate_public_url()` call, and pass `trust_env=False` to `httpx.AsyncClient`.

- [ ] **Step 4: Write a failing bounded-read API test**

  Add a fake upload object whose `read(size)` records `size` and returns `max_upload_bytes + 1` bytes. Assert the endpoint returns `413` and the requested read size is exactly `max_upload_bytes + 1`.

- [ ] **Step 5: Run the API test and verify the expected failure**

  Run `python -m pytest tests/test_api.py::test_upload_reads_only_configured_limit -q`.
  Expected: failure because the route currently calls `file.read()` without a size.

- [ ] **Step 6: Implement the bounded read and early content-length check**

  Add an optional `Content-Length` header parameter to the upload route. Reject a value over `settings.max_request_bytes` before reading. Keep `await file.read(settings.max_upload_bytes + 1)` as the authoritative image-file limit and map an oversized result to `413`. Add `MAX_REQUEST_BYTES` to `Settings` and `.env.example` with a default larger than `MAX_UPLOAD_BYTES` to allow multipart overhead.

- [ ] **Step 7: Run focused tests and commit**

  Run `python -m pytest tests/test_url_fetcher.py tests/test_api.py -q`.
  Commit with `git add app/url_fetcher.py app/main.py app/config.py .env.example tests/test_url_fetcher.py tests/test_api.py && git -c user.name="wei xu" -c user.email="xuweixia@live.com" commit -m "fix: harden image URL and upload limits"`.

### Task 3: Add mature API-key rate limiting and a bounded inference gate

**Files:**
- Modify: `pyproject.toml`
- Modify: `app/remover.py`
- Modify: `app/main.py`
- Modify: `.env.example`
- Modify: `tests/test_api.py`
- Modify: `tests/test_remover.py`

**Interfaces:**
- `RembgRemover.remove()` raises `InferenceBusyError` when active plus waiting requests reaches the configured capacity.
- `create_app()` registers a `slowapi` limiter keyed by `X-API-Key`, with `rate_limit_per_minute` applied to both removal endpoints.
- Busy inference maps to HTTP `429` with `Retry-After: 1`.

- [ ] **Step 1: Add the limiter dependency declaration**

  Add `slowapi>=0.1.9,<1` to the main project dependencies. Install the project test extras plus the new dependency in the isolated environment before running the new tests.

- [ ] **Step 2: Write failing tests for the inference gate**

  Add a test that configures `gpu_max_concurrency=1` and `max_pending_requests=0`, occupies the active slot, and asserts a second `remove()` raises `InferenceBusyError` without starting another thread.

- [ ] **Step 3: Run the gate test and verify the expected failure**

  Run `python -m pytest tests/test_remover.py::test_remover_rejects_when_inference_capacity_is_full -q`.
  Expected: failure because the remover currently waits on an unbounded blocking semaphore.

- [ ] **Step 4: Implement the bounded async admission gate**

  Track active and waiting counts under an `asyncio.Condition`. Admit immediately when an active slot is free, allow at most `max_pending_requests` waiters, decrement counts on cancellation, and release the next waiter in a `finally` block around `asyncio.to_thread`.

- [ ] **Step 5: Write failing API tests for `429` behavior**

  Add tests for a busy remover and a limiter configured to one request per minute. Assert the removal endpoints return `429`, include `Retry-After` for a busy inference, and continue returning `401` for missing keys.

- [ ] **Step 6: Implement `slowapi` registration and error mapping**

  Add the API-key key function, application limiter state, rate-limit exception handler, route decorators, and `InferenceBusyError` mapping. Keep `/health` and `/v1/models` outside the limiter.

- [ ] **Step 7: Run focused tests and commit**

  Run `python -m pytest tests/test_api.py tests/test_remover.py -q`.
  Commit with `git add pyproject.toml app/remover.py app/main.py .env.example tests/test_api.py tests/test_remover.py && git -c user.name="wei xu" -c user.email="xuweixia@live.com" commit -m "feat: bound rembg request admission"`.

### Task 4: Add liveness/readiness endpoints and remove duplicate PNG conversion

**Files:**
- Modify: `app/main.py`
- Modify: `app/remover.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_remover.py`
- Modify: `docker-compose.yml`

**Interfaces:**
- `GET /livez` returns `{"status": "ok"}` without loading a model.
- `GET /readyz` returns provider/configuration status and HTTP `200` when the configured backend is available, otherwise `503`.
- `RembgRemover._remove_sync()` returns the raw rembg result; `main.py` remains the single RGBA PNG normalization boundary.

- [ ] **Step 1: Write failing health and normalization tests**

  Add tests for public `/livez`, `/readyz` success with a fake remover exposing readiness, `/readyz` failure with an unavailable fake remover, and a remover result that is normalized only by the route.

- [ ] **Step 2: Run the tests and verify the expected failure**

  Run `python -m pytest tests/test_api.py tests/test_remover.py -q`.
  Expected: failures because the endpoints and readiness contract do not exist and the remover currently normalizes output.

- [ ] **Step 3: Implement readiness and raw-result behavior**

  Add a small readiness protocol/helper with a safe default for injected fakes. Report the configured model and available ONNX providers without exposing paths. Move `ensure_rgba_png` responsibility out of `_remove_sync()` while preserving route response bytes.

- [ ] **Step 4: Update the Compose healthcheck and run focused tests**

  Change the Compose healthcheck to `/readyz`, run `python -m pytest tests/test_api.py tests/test_remover.py -q`, and verify all focused tests pass.

- [ ] **Step 5: Commit the health and output changes**

  Commit with `git add app/main.py app/remover.py tests/test_api.py tests/test_remover.py docker-compose.yml && git -c user.name="wei xu" -c user.email="xuweixia@live.com" commit -m "feat: expose rembg readiness state"`.

### Task 5: Add CI contract checks, documentation, and final verification

**Files:**
- Create: `.github/workflows/test.yml`
- Modify: `README.md`
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `pyproject.toml`
- Modify: `tests/test_config.py`

**Interfaces:**
- CI runs Python tests, compile checks, Ruff, and Compose configuration validation without requiring a GPU.
- README documents URL allowlist, process-local limiter scope, readiness endpoints, and the separate manual GPU smoke test.
- Docker runtime runs as a non-root user and uses a configurable cache directory.

- [ ] **Step 1: Write failing CI/documentation contract checks**

  Extend configuration tests for the new environment variables and add a source-level test asserting README mentions `URL_ALLOWED_HOSTS`, `/readyz`, and the process-local limiter limitation.

- [ ] **Step 2: Run the new checks and verify the expected failure**

  Run `python -m pytest tests/test_config.py -q`.
  Expected: failure because the documentation/configuration contracts are not present.

- [ ] **Step 3: Implement CI and container hardening**

  Add a GitHub Actions workflow using Python 3.12, install the project with test dependencies, run pytest, compileall, Ruff, and `docker compose config`. Add a non-root `appuser` after dependency installation, create and chown the cache directory, and preserve port 8000 behavior.

- [ ] **Step 4: Update README and environment examples**

  Document the new defaults, URL allowlist requirement, `livez`/`readyz`, rate-limit scope, Docker non-root behavior, and the manual GPU smoke-test command.

- [ ] **Step 5: Run the complete verification suite**

  Run:

  ```powershell
  python -m pytest -q
  python -m compileall -q app scripts
  python -m ruff check app tests scripts
  docker compose config
  git diff --check
  git status --short --branch
  ```

  Expected: all tests and checks pass, Compose renders successfully, and only intentional branch changes remain.

- [ ] **Step 6: Commit the CI and deployment documentation**

  Commit with `git add .github/workflows/test.yml README.md Dockerfile docker-compose.yml pyproject.toml tests/test_config.py && git -c user.name="wei xu" -c user.email="xuweixia@live.com" commit -m "chore: verify rembg production safeguards"`.

---

### Final review fix wave: close security and contract findings

The independent whole-branch review found four important issues: invalid credentials could be rate-limited before returning `401`, the documented limiter scope was not shared across removal routes, request-size enforcement happened after multipart parsing, and DNS validation was vulnerable to a resolve/connect TOCTOU window. The user approved expanding the URL work to a fixed-address resolver.

- Add RED/GREEN regression tests for repeated invalid keys and for one valid key consuming the same limit across upload and URL routes.
- Run authentication before applying the limiter, while retaining the limiter for valid API keys only.
- Add pure ASGI request-body limiting before FastAPI multipart parsing, including `Content-Length` and chunked/no-header paths.
- Replace hostname-only outbound connection behavior with an aiohttp resolver/connector that filters and pins validated public addresses while preserving TLS verification and disabling redirects/environment proxy behavior.
- Add validation that `MAX_REQUEST_BYTES` is greater than `MAX_UPLOAD_BYTES`, readiness coverage for cache-directory writability, and a pinned Ruff version in CI where compatible.
- Run the complete supported-runtime verification suite and perform exactly one scoped re-review of this fix wave.
