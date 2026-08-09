# Docker Layer Cache Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorder Dockerfile inputs so application-source changes reuse the Python dependency installation layer.

**Architecture:** Keep the existing single-stage CUDA image. Copy `pyproject.toml` first and install the package before copying application source and the entrypoint; therefore Docker's local BuildKit layer cache keys the expensive dependency step on dependency metadata rather than all source files.

**Tech Stack:** Dockerfile, Docker Compose, Docker BuildKit layer cache, Python package installation.

## Global Constraints

- Preserve the existing CUDA base image and runtime command.
- Preserve the existing uncommitted changes in `Dockerfile` and `docker-entrypoint.sh`.
- Do not add remote cache configuration or change CI responsibilities.
- Do not add application behavior or dependency changes.

---

### Task 1: Reorder Dockerfile layers

**Files:**
- Modify: `Dockerfile`

**Interfaces:**
- Consumes: `pyproject.toml` as the dependency metadata input.
- Produces: A build sequence where the dependency installation layer precedes application-source copies.

- [ ] **Step 1: Move application copies after dependency installation**

Keep `COPY pyproject.toml ./` before the dependency installation, move `COPY app ./app` and `COPY docker-entrypoint.sh /usr/local/bin/rembg-entrypoint.sh` after that installation, and retain the existing permission command after the entrypoint copy.

- [ ] **Step 2: Validate the Dockerfile structure**

Confirm that the dependency command still runs from `/app`, that the package metadata is present when it runs, and that the later user-creation layer still sees the copied application and executable entrypoint.

- [ ] **Step 3: Run Compose configuration validation**

Run `docker compose config` and expect exit code 0.

- [ ] **Step 4: Build the image and inspect cache reuse**

Run `docker compose build api` once, then make a temporary tracked-context source change only for the build check, rebuild, and confirm the dependency installation step is reported as `CACHED`; restore the temporary change without touching the pre-existing user edits.
