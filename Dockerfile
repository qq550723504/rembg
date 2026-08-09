FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MODEL_CACHE_DIR=/var/lib/rembg \
    U2NET_HOME=/var/lib/rembg

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip curl util-linux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./

RUN python3 -m pip install --break-system-packages --no-build-isolation ".[gpu]"

COPY app ./app
COPY docker-entrypoint.sh /usr/local/bin/rembg-entrypoint.sh

RUN chmod +x /usr/local/bin/rembg-entrypoint.sh

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /var/lib/rembg \
    && chown -R appuser:appuser /app /var/lib/rembg \
    && chmod 755 /usr/local/bin/rembg-entrypoint.sh

USER root

ENTRYPOINT ["/usr/local/bin/rembg-entrypoint.sh"]

EXPOSE 8000

CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

