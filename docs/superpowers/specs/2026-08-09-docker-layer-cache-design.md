# Docker Layer Cache Optimization Design

## Goal

让应用源码变更能够复用 Python 依赖安装层，减少本地 Docker 重建时间，同时保持现有 CUDA 运行时、入口脚本和 Compose 行为不变。

## Scope

- 调整 `Dockerfile` 中 `COPY` 和 `RUN` 的顺序。
- 先仅复制 `pyproject.toml` 并安装项目依赖，形成稳定的依赖缓存层。
- 再复制 `app` 和 `docker-entrypoint.sh`，执行入口脚本权限设置。
- 不引入多阶段构建、远程 BuildKit cache 或 CI 镜像构建流程。
- 保留当前工作区已有的 `Dockerfile` 和 `docker-entrypoint.sh` 修改。

## Expected behavior

- 修改 `app` 源码时，依赖安装层保持命中。
- 修改 `pyproject.toml`、基础镜像或依赖安装命令时，依赖层按预期失效并重新安装。
- `docker compose config` 仍然成功。
- 镜像仍使用现有 CUDA 基础镜像和入口命令。

## Validation

- 检查 Dockerfile 指令顺序，确认 `pyproject.toml` 是依赖层唯一的项目输入。
- 运行 `docker compose config`。
- 使用普通 `docker compose build` 验证构建成功，并在源码变更后再次构建，确认依赖安装层可复用；若本机 GPU/镜像拉取条件不足，记录为环境限制。
