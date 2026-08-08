import asyncio
import importlib
import os
import threading
from collections import OrderedDict
from typing import NotRequired, Protocol, TypedDict, runtime_checkable


class BackgroundRemover(Protocol):
    async def remove(self, data: bytes, model_name: str | None = None) -> bytes:
        ...


class ReadinessStatus(TypedDict):
    available: bool
    backend: str
    providers: list[str]
    reason: NotRequired[str]


@runtime_checkable
class ReadinessAwareRemover(Protocol):
    def readiness(self) -> ReadinessStatus:
        ...


class InferenceBusyError(RuntimeError):
    pass


class RembgRemover:
    _execution_providers = [
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    ]

    def __init__(self, settings):
        self.settings = settings
        self._gpu_max_concurrency = getattr(settings, "gpu_max_concurrency", 1)
        self._max_pending_requests = getattr(settings, "max_pending_requests", 4)
        self._sessions = OrderedDict()
        self._session_lock = threading.Lock()
        self._inference_condition = asyncio.Condition()
        self._active_requests = 0
        self._waiting_requests = 0

    async def remove(self, data: bytes, model_name: str | None = None) -> bytes:
        selected_model = model_name or self.settings.model_name
        await self._acquire_inference_slot()
        try:
            return await asyncio.to_thread(self._remove_sync, data, selected_model)
        finally:
            await self._release_inference_slot()

    def _remove_sync(self, data: bytes, model_name: str | None = None) -> bytes:
        selected_model = model_name or self.settings.model_name
        return self._remove_with_session(data, selected_model)

    def readiness(self) -> ReadinessStatus:
        try:
            onnxruntime = importlib.import_module("onnxruntime")
        except ImportError:
            return {
                "available": False,
                "backend": "rembg",
                "providers": [],
                "reason": "onnxruntime is not installed",
            }

        available_providers = list(onnxruntime.get_available_providers())
        configured_providers = [
            provider
            for provider in self._execution_providers
            if provider in available_providers
        ]
        if not configured_providers:
            return {
                "available": False,
                "backend": "rembg",
                "providers": available_providers,
                "reason": "no configured execution provider is available",
            }

        return {
            "available": True,
            "backend": "rembg",
            "providers": available_providers,
        }

    async def _acquire_inference_slot(self) -> None:
        async with self._inference_condition:
            if self._active_requests < self._gpu_max_concurrency:
                self._active_requests += 1
                return

            if self._waiting_requests >= self._max_pending_requests:
                raise InferenceBusyError("Inference capacity is full")

            self._waiting_requests += 1
            try:
                while self._active_requests >= self._gpu_max_concurrency:
                    await self._inference_condition.wait()
            except asyncio.CancelledError:
                self._waiting_requests -= 1
                self._inference_condition.notify(1)
                raise

            self._waiting_requests -= 1
            self._active_requests += 1

    async def _release_inference_slot(self) -> None:
        async with self._inference_condition:
            self._active_requests -= 1
            self._inference_condition.notify(1)

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
                providers=self._execution_providers,
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
