# rembg Advanced Parameters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose rembg alpha-matting and mask post-processing parameters through both removal APIs and the existing Web UI without changing default behavior.

**Architecture:** Add a focused Pydantic `RemovalOptions` model for defaults, bounds, and allowlisted rembg kwargs. The API routes build options from typed form/JSON fields and pass only non-default values to the remover; `RembgRemover` forwards them to `rembg.remove` while retaining the existing cached session and RGBA-PNG response normalization. The UI adds a collapsed advanced-settings section and serializes the same five fields for file and URL requests.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, rembg, pytest, vanilla HTML/CSS/JavaScript.

## Global Constraints

- Supported fields are `alpha_matting`, `alpha_matting_foreground_threshold`, `alpha_matting_background_threshold`, `alpha_matting_erode_size`, and `post_process_mask`.
- Boolean defaults are `false`; threshold defaults are foreground `240`, background `10`, erode `10`.
- Integer fields accept only `0..255`.
- Do not expose `only_mask`, `bgcolor`, or SAM-specific point inputs in this feature.
- When all options are default, preserve the existing remover call shape `(data, model_name)`.
- Always keep route output normalized as an RGBA PNG.
- Do not add dependencies or environment variables.

---

### Task 1: Add the validated removal-options model

**Files:**
- Create: `app/removal_options.py`
- Create: `tests/test_removal_options.py`

**Interfaces:**
- Produces `RemovalOptions`, a Pydantic model with the five fields and exact defaults/bounds.
- Produces `RemovalOptions.to_kwargs() -> dict[str, bool | int]`, returning only non-default fields with their rembg keyword names.

- [ ] **Step 1: Write the failing tests**

```python
from pydantic import ValidationError
import pytest

from app.removal_options import RemovalOptions


def test_removal_options_use_rembg_defaults_and_omit_default_kwargs():
    options = RemovalOptions()

    assert options.model_dump() == {
        "alpha_matting": False,
        "alpha_matting_foreground_threshold": 240,
        "alpha_matting_background_threshold": 10,
        "alpha_matting_erode_size": 10,
        "post_process_mask": False,
    }
    assert options.to_kwargs() == {}


def test_removal_options_convert_non_defaults_to_allowlisted_kwargs():
    options = RemovalOptions(
        alpha_matting=True,
        alpha_matting_foreground_threshold=220,
        post_process_mask=True,
    )

    assert options.to_kwargs() == {
        "alpha_matting": True,
        "alpha_matting_foreground_threshold": 220,
        "post_process_mask": True,
    }


@pytest.mark.parametrize(
    "field",
    [
        "alpha_matting_foreground_threshold",
        "alpha_matting_background_threshold",
        "alpha_matting_erode_size",
    ],
)
def test_removal_options_reject_out_of_range_integers(field):
    with pytest.raises(ValidationError):
        RemovalOptions(**{field: 256})
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `python -m pytest tests/test_removal_options.py -q`

Expected: FAIL because `app.removal_options` does not exist.

- [ ] **Step 3: Implement the minimal model**

Create `RemovalOptions` with Pydantic `Field` bounds `ge=0, le=255`, the five exact defaults, and `to_kwargs()` implemented with `model_dump(exclude_defaults=True)`.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `python -m pytest tests/test_removal_options.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the task**

```powershell
git add app/removal_options.py tests/test_removal_options.py
git commit -m "feat: add validated rembg removal options"
```

### Task 2: Forward options through the rembg remover

**Files:**
- Modify: `app/remover.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_remover.py`

**Interfaces:**
- `BackgroundRemover.remove(data, model_name=None, **options) -> bytes` accepts validated optional rembg kwargs.
- `RembgRemover._remove_sync(data, model_name=None, **options) -> bytes` and `_remove_with_session(data, model_name, **options) -> bytes` pass options to rembg.

- [ ] **Step 1: Write the failing forwarding test**

Add a test whose fake `rembg.remove` records keyword arguments, call `RembgRemover.remove` with `alpha_matting=True` and `post_process_mask=True`, and assert the fake receives those two values plus `session` and `force_return_bytes=True`.

- [ ] **Step 2: Run the focused remover test and verify it fails**

Run: `python -m pytest tests/test_remover.py -k forwards -q`

Expected: FAIL because `RembgRemover.remove` does not accept or forward the new keywords.

- [ ] **Step 3: Implement minimal forwarding and preserve old calls**

Import no rembg-specific types into the public protocol. Add `**options` to the remover methods, pass it through the async/thread boundary, and merge it into the existing `remove_function` call. Keep the no-option path equivalent to the existing call.

- [ ] **Step 4: Update the fake remover contract and run remover tests**

Update `FakeRemover.remove` in `tests/conftest.py` to record `(data, model_name, options)` while retaining its existing output behavior. Run `python -m pytest tests/test_remover.py -q` and expect PASS.

- [ ] **Step 5: Commit the task**

```powershell
git add app/remover.py tests/conftest.py tests/test_remover.py
git commit -m "feat: forward rembg removal options"
```

### Task 3: Add validated parameters to both API routes

**Files:**
- Modify: `app/main.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- `ImageUrlRequest` includes the five `RemovalOptions` fields with the same defaults and bounds.
- The upload route accepts matching typed multipart form fields.
- Both routes pass `RemovalOptions(...).to_kwargs()` to the remover only when non-default options are selected.

- [ ] **Step 1: Write failing API contract tests**

Extend `FakeRemover` to record options. Add one upload test posting `alpha_matting=true`, foreground threshold `220`, erode size `8`, and `post_process_mask=true`; assert the response is `200` and the recorded options match. Add one URL test with background threshold `20`; assert the same. Add a test posting threshold `256` and assert `422` with no remover call.

- [ ] **Step 2: Run the new API tests and verify they fail**

Run: `python -m pytest tests/test_api.py -k "removal_options or alpha_matting or threshold" -q`

Expected: FAIL because the routes do not accept these fields and the fake remover does not receive options.

- [ ] **Step 3: Implement the API wiring**

Import `RemovalOptions` and declare typed `Form` parameters for upload requests. Add the same fields to `ImageUrlRequest`. Create one small helper in `app.main` that calls `remover.remove(data, model_name)` when `to_kwargs()` is empty and otherwise calls `remover.remove(data, model_name, **options)`. Use it in both processing closures.

- [ ] **Step 4: Run API tests and the full Python suite**

Run: `python -m pytest tests/test_api.py -q` and then `python -m pytest -q`.

Expected: new API tests and all existing API behavior pass. If the known `U2NET_HOME` baseline failure remains, record it separately rather than changing unrelated configuration behavior.

- [ ] **Step 5: Commit the task**

```powershell
git add app/main.py tests/conftest.py tests/test_api.py
git commit -m "feat: expose rembg options in API"
```

### Task 4: Add advanced controls to the Web UI

**Files:**
- Modify: `app/static/index.html`
- Modify: `app/static/styles.css`
- Modify: `app/static/app.js`
- Modify: `tests/test_ui.py`

**Interfaces:**
- The UI exposes IDs `alpha-matting`, `alpha-matting-foreground-threshold`, `alpha-matting-background-threshold`, `alpha-matting-erode-size`, and `post-process-mask`.
- Both request builders serialize the exact API field names and current control values.

- [ ] **Step 1: Write failing UI contract assertions**

Add assertions that the HTML contains the advanced-settings controls and that JavaScript contains each exact field name in both the multipart and JSON request construction paths.

- [ ] **Step 2: Run UI tests and verify they fail**

Run: `python -m pytest tests/test_ui.py -q`

Expected: FAIL because the controls and serialization code are absent.

- [ ] **Step 3: Implement the controls and serialization**

Add a collapsed `<details>` section with the two checkboxes and three bounded numeric inputs using the spec defaults. Add small CSS rules matching the existing dark form controls. Add a `getRemovalOptions()` helper in `app.js`; append its values to `FormData` and include them in the URL JSON body. Include the new inputs in busy-state disabling.

- [ ] **Step 4: Run UI tests and full static checks**

Run: `python -m pytest tests/test_ui.py -q`; then inspect the rendered HTML structure and run `python -m compileall -q app scripts`.

Expected: PASS with no JavaScript field-name omissions.

- [ ] **Step 5: Commit the task**

```powershell
git add app/static/index.html app/static/styles.css app/static/app.js tests/test_ui.py
git commit -m "feat: add advanced rembg controls"
```

### Task 5: Document and verify the feature

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document API examples and UI behavior**

Add optional parameter examples to the upload and URL requests, list defaults/ranges, and explain that default values preserve the existing behavior.

- [ ] **Step 2: Run the complete verification suite**

Run:

```powershell
python -m pytest -q
python -m compileall -q app scripts
python -m ruff check app tests scripts
docker compose config
```

Expected: all feature tests pass; the only allowed pre-existing exception is the environment-dependent `U2NET_HOME` default test failure observed at baseline.

- [ ] **Step 3: Review the diff and commit documentation**

Run `git diff --check` and `git diff --stat`, confirm no unrelated files changed, then commit:

```powershell
git add README.md
git commit -m "docs: document rembg advanced parameters"
```
