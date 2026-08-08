import asyncio
import os
import threading
from typing import Protocol

from .image_io import ensure_rgba_png


class BackgroundRemover(Protocol):
    async def remove(self, data: bytes) -> bytes:
        ...


class RembgRemover:
    def __init__(self, settings):
        self.settings = settings
        self._session = None
        self._session_lock = threading.Lock()
        self._inference_slots = threading.BoundedSemaphore(
            settings.gpu_max_concurrency
        )

    async def remove(self, data: bytes) -> bytes:
        return await asyncio.to_thread(self._remove_sync, data)

    def _remove_sync(self, data: bytes) -> bytes:
        with self._inference_slots:
            return ensure_rgba_png(self._remove_with_session(data))

    def _remove_with_session(self, data: bytes) -> bytes:
        if self._session is None:
            with self._session_lock:
                if self._session is None:
                    os.environ.setdefault("U2NET_HOME", self.settings.model_cache_dir)
                    from rembg import new_session, remove

                    self._session = new_session(
                        self.settings.model_name,
                        providers=[
                            "CUDAExecutionProvider",
                            "CPUExecutionProvider",
                        ],
                    )
                    self._remove_function = remove

        return self._remove_function(
            data,
            session=self._session,
            force_return_bytes=True,
        )
