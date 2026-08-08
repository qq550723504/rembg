import asyncio
import os
import threading
from collections import OrderedDict
from typing import Protocol

from .image_io import ensure_rgba_png


class BackgroundRemover(Protocol):
    async def remove(self, data: bytes, model_name: str | None = None) -> bytes:
        ...


class RembgRemover:
    def __init__(self, settings):
        self.settings = settings
        self._sessions = OrderedDict()
        self._session_lock = threading.Lock()
        self._inference_slots = threading.BoundedSemaphore(
            settings.gpu_max_concurrency
        )

    async def remove(self, data: bytes, model_name: str | None = None) -> bytes:
        selected_model = model_name or self.settings.model_name
        return await asyncio.to_thread(self._remove_sync, data, selected_model)

    def _remove_sync(self, data: bytes, model_name: str | None = None) -> bytes:
        with self._inference_slots:
            selected_model = model_name or self.settings.model_name
            return ensure_rgba_png(self._remove_with_session(data, selected_model))

    def _get_session(self, model_name: str):
        with self._session_lock:
            cached = self._sessions.pop(model_name, None)
            if cached is not None:
                self._sessions[model_name] = cached
                return cached

            os.environ["U2NET_HOME"] = self.settings.model_cache_dir
            from rembg import new_session, remove

            session = new_session(
                model_name,
                providers=[
                    "CUDAExecutionProvider",
                    "CPUExecutionProvider",
                ],
            )
            self._sessions[model_name] = (session, remove)
            while len(self._sessions) > self.settings.model_session_cache_size:
                self._sessions.popitem(last=False)
            return self._sessions[model_name]

    def _remove_with_session(self, data: bytes, model_name: str) -> bytes:
        session, remove_function = self._get_session(model_name)
        return remove_function(
            data,
            session=session,
            force_return_bytes=True,
        )
