#!/bin/sh
set -eu

if [ "${MODEL_CACHE_DIR:-}" = "/root/.u2net" ]; then
    export MODEL_CACHE_DIR=/var/lib/rembg
fi

if [ "${U2NET_HOME:-}" = "/root/.u2net" ]; then
    export U2NET_HOME=/var/lib/rembg
fi

exec "$@"
