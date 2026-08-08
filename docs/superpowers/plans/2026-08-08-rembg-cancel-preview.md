
# rembg 取消抠图与大图预览 Implementation Plan

> For agentic workers: use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

Goal: 为现有同源 Web UI 增加取消当前抠图请求，以及原图和抠图结果点击查看大图的能力。

Architecture: 复用现有同步 API 和 RembgRemover 的取消边界。前端为每次 fetch 创建 AbortController，取消时中止客户端请求；排队中的后端协程释放等待槽，已开始的线程推理安全完成但不再返回结果。图片预览使用现有 object URL 和无依赖的可访问弹层。

Tech Stack: FastAPI、现有 asyncio/线程取消处理、原生 HTML/CSS/JavaScript、pytest。

## Global Constraints

- 保持两个现有 POST 接口的路径、鉴权方式、请求体和 image/png 响应不变。
- 不硬中断正在运行的 ONNX Runtime/GPU 推理；活动 worker 完成后才释放推理槽。
- 不引入 React、Vite、第三方弹窗组件或任务数据库。
- 继续使用 state.originalUrl 和 state.resultUrl，并在替换或页面卸载时释放 object URL。
- 只暂存与本功能相关的文件，保留工作区已有部署修复改动。

---

### Task 1: Add failing UI contract tests

Files:
- Modify: tests/test_ui.py

Interfaces:
- Consumes: GET / HTML and /static/app.js.
- Produces: cancel control, preview dialog accessibility, abort handling, and preview event regression checks.

- [ ] Step 1: Write the failing tests.

Add tests that assert the homepage contains image-dialog, role=dialog, aria-modal=true, dialog-close, original-preview-trigger, and result-preview-trigger. Add a static asset test that asserts app.js contains AbortController, signal: controller.signal, the AbortError branch, openPreview, Escape handling, originalPreviewTrigger, and resultPreviewTrigger.

~~~python
def test_homepage_includes_cancel_control_and_image_dialog(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="image-dialog"' in response.text
    assert 'role="dialog"' in response.text
    assert 'aria-modal="true"' in response.text
    assert 'id="dialog-close"' in response.text
    assert 'id="original-preview-trigger"' in response.text
    assert 'id="result-preview-trigger"' in response.text


def test_static_javascript_supports_abort_and_large_preview(client):
    response = client.get("/static/app.js")
    assert response.status_code == 200
    assert "AbortController" in response.text
    assert "signal: controller.signal" in response.text
    assert 'error.name === "AbortError"' in response.text
    assert "openPreview" in response.text
    assert 'event.key === "Escape"' in response.text
    assert "originalPreviewTrigger" in response.text
    assert "resultPreviewTrigger" in response.text
~~~

- [ ] Step 2: Run the new tests and verify the expected failure.

Run from the project test image:

~~~powershell
$repoPath = (Get-Location).Path
docker run --rm --entrypoint /bin/bash -v "$repoPath:/workspace" -w /workspace rembg-birefnet-api-api -lc 'python3 -m pip install --break-system-packages ".[test]" && python3 -m pytest tests/test_ui.py -q'
~~~

Expected: the existing UI tests pass and the two new tests fail because the cancel and dialog markup/JavaScript do not exist.

### Task 2: Implement cancellable request state

Files:
- Modify: app/static/app.js
- Test: tests/test_ui.py

Interfaces:
- Consumes: form submit events and the existing two removal endpoints.
- Produces: state.requestController, a submit button that toggles between 开始抠图 and 取消抠图, and an AbortError-specific status path.

- [ ] Step 1: Add request controller state and button-label reference.

Add requestController: null to state and const buttonLabel = removeButton.querySelector(".button-label").

- [ ] Step 2: Update setBusy without disabling the action button.

Keep model and input controls disabled while busy, but leave removeButton clickable. Set the button label and aria-label to 取消抠图 while busy and 开始抠图 otherwise; toggle is-loading and a separate is-cancel class.

- [ ] Step 3: Abort the active request.

At the start of removeBackground, if state.requestController exists, call abort(), clear it, set status to 已取消本次抠图。, restore the non-busy state, and return. Otherwise create an AbortController, save it in state, and pass controller.signal to both fetch calls. In catch, treat error.name === "AbortError" as a normal user cancellation; keep existing error handling for other failures. In finally, clear the controller only when it is still the current controller and call setBusy(false).

- [ ] Step 4: Run tests.

Run the focused tests from Task 1. Expected: the cancel assertions pass; preview assertions remain failing until Task 3.

### Task 3: Add accessible image triggers and preview dialog

Files:
- Modify: app/static/index.html
- Modify: app/static/styles.css
- Modify: app/static/app.js
- Test: tests/test_ui.py

Interfaces:
- Consumes: state.originalUrl, state.resultUrl, and the existing preview images.
- Produces: openPreview(url, altText), closePreview(), keyboard/overlay dismissal, and preserved download behavior.

- [ ] Step 1: Add preview trigger markup.

Wrap original-preview and result-preview in type=button elements with IDs original-preview-trigger and result-preview-trigger, keeping the existing image IDs. Add an image-dialog after the form with role=dialog, aria-modal=true, a labelled heading, dialog-close button, dialog-image, and dialog-error.

- [ ] Step 2: Add focused styles.

Add preview-trigger styles with full-frame layout, no button chrome, and zoom cursor. Add fixed image-dialog, backdrop, panel, heading, and dialog-image styles. Keep the image within 92vw and 90vh and support the existing mobile breakpoint. Add dialog-open body behavior to prevent page scrolling while open.

- [ ] Step 3: Wire preview lifecycle.

Add DOM references for both triggers, dialog, close button, dialog image, and error message. Make setOriginalPreview show/hide the original trigger and result success show/hide the result trigger. Implement openPreview(url, altText) to set the dialog image, clear the error, show the dialog, lock body scrolling, and focus the close button. Implement closePreview() to hide the dialog, unlock scrolling, and clear the dialog image source without revoking the thumbnail object URL. Bind trigger clicks, close button, backdrop click, Escape, and image error.

- [ ] Step 4: Run the UI suite.

Expected: all tests in tests/test_ui.py pass.

### Task 4: Regression and local browser verification

Files:
- Test: tests/test_remover.py
- Test: tests/test_api.py
- Test: tests/test_ui.py

Interfaces:
- Consumes: the existing cancellation-aware inference gate and updated UI assets.
- Produces: evidence that queued cancellation releases capacity, active cancellation preserves the worker boundary, API responses remain unchanged, and browser interactions work.

- [ ] Step 1: Run cancellation regression tests.

~~~powershell
$repoPath = (Get-Location).Path
docker run --rm --entrypoint /bin/bash -v "$repoPath:/workspace" -w /workspace rembg-birefnet-api-api -lc 'python3 -m pip install --break-system-packages ".[test]" && python3 -m pytest tests/test_remover.py::test_remover_releases_waiting_capacity_when_waiter_is_cancelled tests/test_remover.py::test_remover_keeps_inference_slot_until_cancelled_worker_finishes -q'
~~~

Expected: 2 passed.

- [ ] Step 2: Run the full suite.

~~~powershell
$repoPath = (Get-Location).Path
docker run --rm --entrypoint /bin/bash -v "$repoPath:/workspace" -w /workspace rembg-birefnet-api-api -lc 'python3 -m pip install --break-system-packages ".[test]" && python3 -m pytest -q'
~~~

Expected: all tests pass with zero failures.

- [ ] Step 3: Rebuild the local service.

Run docker compose -p rembg-birefnet-api up -d --build. Expected: rembg-birefnet-api-api-1 remains healthy on port 8000 and continues using rembg-birefnet-api_rembg-model-cache.

- [ ] Step 4: Verify the browser workflow.

Open http://localhost:8000/. Select an image and click 开始抠图; confirm the button changes to 取消抠图. Click cancel and confirm the request ends, status reports cancellation, and the form can be used again. Complete one request, click both preview images, close with the close button, backdrop, and Escape, and confirm the download link still works.

- [ ] Step 5: Review the final diff.

Run git diff --check, git status --short --branch, and a scoped diff of app/static/app.js, app/static/index.html, app/static/styles.css, tests/test_ui.py, tests/test_remover.py, and tests/test_api.py. Keep docker-entrypoint.sh and .gitattributes separate from the feature commit.
