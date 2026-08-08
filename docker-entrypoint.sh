#!/bin/sh
set -eu

if [ "${MODEL_CACHE_DIR:-}" = "/root/.u2net" ]; then
    export MODEL_CACHE_DIR=/var/lib/rembg
fi

if [ "${U2NET_HOME:-}" = "/root/.u2net" ]; then
    export U2NET_HOME=/var/lib/rembg
fi

if [ -z "${MODEL_CACHE_DIR:-}" ]; then
    export MODEL_CACHE_DIR=/var/lib/rembg
fi

mkdir -p /var/lib/rembg
if [ "${MODEL_CACHE_DIR}" = "/var/lib/rembg" ]; then
    chown -R appuser:appuser /var/lib/rembg
fi

exec runuser -u appuser -- "$@"
