# Model Capability Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans (recommended) to implement this plan task-by-task.

**Goal:** Expose model capability metadata and make advanced-option handling honest and extensible.

**Architecture:** Keep rembg's shared post-processing options as common capabilities for current models. Add typed model profiles with serializable parameter definitions at the API boundary, expose them through `/v1/models`, consume them in the existing vanilla JavaScript UI, and validate/map model-specific fields before invoking rembg.

**Tech Stack:** FastAPI, Pydantic, vanilla JavaScript, pytest, rembg.

## Global Constraints

- Preserve all existing model names and removal endpoints.
- Preserve the existing `image/png` response contract.
- Do not add frontend dependencies or model-specific inference implementations.
- Preserve current workspace changes in Docker and entrypoint files.
- Limit model-specific fields to parameters supported by the installed rembg version: `cloth_category`, `sam_prompt`, `sam_model`, and `sam_quant`.

---

### Task 1: Add model capability and option contracts

**Files:**
- Modify: `app/models.py`
- Modify: `app/removal_options.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_api.py`

- [ ] Add failing tests for model-specific parameter definitions, invalid-model rejection, and Alpha Matting option normalization.
- [ ] Run the focused tests and confirm they fail because capability fields and normalization do not exist.
- [ ] Implement typed model profiles, expose profiles from `model_options()`, validate model-specific fields, and omit Alpha Matting thresholds when Alpha Matting is disabled.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Wire model-specific API fields

**Files:**
- Modify: `app/main.py`
- Modify: `app/removal_options.py`
- Modify: `tests/test_api.py`

- [ ] Add failing upload and URL tests for cloth category and SAM parameters.
- [ ] Parse and validate SAM prompt JSON and map accepted values into `RemovalOptions.to_kwargs()`.
- [ ] Run the focused API tests and confirm they pass.

### Task 3: Make the UI consume capability metadata

**Files:**
- Modify: `app/static/app.js`
- Modify: `tests/test_ui.py`

- [ ] Add failing source-contract assertions for dynamic model-specific controls and request serialization.
- [ ] Implement capability-aware model rendering, dynamic controls, and model-specific request serialization.
- [ ] Run UI tests and confirm they pass.

### Task 4: Run regression verification

**Files:**
- No additional files.

- [ ] Run `python -m pytest -q`.
- [ ] Run `python -m compileall -q app scripts` and `python -m ruff check app tests scripts`.
- [ ] Run `docker compose config` and inspect the final diff.
