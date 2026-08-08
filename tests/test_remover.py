import asyncio
import sys
import threading
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

import app.remover as remover_module
from app.remover import RembgRemover


def test_rembg_remover_lazily_creates_one_session(monkeypatch, png_bytes, settings):
    calls = []

    def new_session(model_name, providers):
        calls.append((model_name, providers))
        return "session"

    def remove(data, session, force_return_bytes):
        assert data == b"input"
        assert session == "session"
        assert force_return_bytes is True
        return png_bytes

    monkeypatch.setitem(
        sys.modules,
        "rembg",
        SimpleNamespace(new_session=new_session, remove=remove),
    )

    remover = RembgRemover(settings)
    first = asyncio.run(remover.remove(b"input"))
    second = asyncio.run(remover.remove(b"input"))

    assert first == png_bytes
    assert second == png_bytes
    assert calls == [("birefnet-general", ["CUDAExecutionProvider", "CPUExecutionProvider"])]


def test_rembg_remover_sets_u2net_home_from_settings(monkeypatch, png_bytes, settings):
    def new_session(model_name, providers):
        return "session"

    def remove(data, session, force_return_bytes):
        return png_bytes

    monkeypatch.delenv("U2NET_HOME", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "rembg",
        SimpleNamespace(new_session=new_session, remove=remove),
    )

    remover = RembgRemover(settings)
    remover._get_session("birefnet-general")

    assert sys.modules["os"].environ["U2NET_HOME"] == settings.model_cache_dir


def test_rembg_remover_overrides_existing_u2net_home(monkeypatch, png_bytes, settings):
    def new_session(model_name, providers):
        return "session"

    def remove(data, session, force_return_bytes):
        return png_bytes

    monkeypatch.setenv("U2NET_HOME", "/tmp/old-cache")
    monkeypatch.setitem(
        sys.modules,
        "rembg",
        SimpleNamespace(new_session=new_session, remove=remove),
    )

    remover = RembgRemover(settings)
    remover._get_session("birefnet-general")

    assert sys.modules["os"].environ["U2NET_HOME"] == settings.model_cache_dir


def test_remove_sync_returns_raw_rembg_bytes_without_png_normalization(monkeypatch, settings):
    rgb_image = Image.new("RGB", (2, 2), (0, 0, 255))
    output = BytesIO()
    rgb_image.save(output, format="JPEG")
    raw_result = output.getvalue()

    def new_session(model_name, providers):
        return "session"

    def remove(data, session, force_return_bytes):
        return raw_result

    monkeypatch.setitem(
        sys.modules,
        "rembg",
        SimpleNamespace(new_session=new_session, remove=remove),
    )

    remover = RembgRemover(settings)

    result = remover._remove_sync(b"input", "birefnet-general")

    assert result == raw_result


def test_remover_rejects_when_inference_capacity_is_full(
    monkeypatch, png_bytes, settings
):
    settings.gpu_max_concurrency = 1
    settings.max_pending_requests = 0
    busy_error = getattr(remover_module, "InferenceBusyError", RuntimeError)
    entered = 0
    started = asyncio.Event()
    release = threading.Event()

    def new_session(model_name, providers):
        return "session"

    def remove(data, session, force_return_bytes):
        nonlocal entered
        entered += 1
        started_loop.call_soon_threadsafe(started.set)
        release.wait(timeout=1)
        return png_bytes

    async def exercise():
        nonlocal started_loop
        started_loop = asyncio.get_running_loop()

        monkeypatch.setitem(
            sys.modules,
            "rembg",
            SimpleNamespace(new_session=new_session, remove=remove),
        )

        remover = RembgRemover(settings)
        first = asyncio.create_task(remover.remove(b"first"))
        await asyncio.wait_for(started.wait(), timeout=1)

        with pytest.raises(busy_error):
            await asyncio.wait_for(remover.remove(b"second"), timeout=0.2)

        release.set()
        assert await asyncio.wait_for(first, timeout=1) == png_bytes

    started_loop = None

    asyncio.run(exercise())

    assert entered == 1


def test_remover_releases_waiting_capacity_when_waiter_is_cancelled(
    monkeypatch, png_bytes, settings
):
    settings.gpu_max_concurrency = 1
    settings.max_pending_requests = 1
    entered = 0
    started = asyncio.Event()
    release = threading.Event()

    def new_session(model_name, providers):
        return "session"

    def remove(data, session, force_return_bytes):
        nonlocal entered
        entered += 1
        started_loop.call_soon_threadsafe(started.set)
        release.wait(timeout=1)
        return png_bytes

    async def exercise():
        nonlocal started_loop
        started_loop = asyncio.get_running_loop()

        monkeypatch.setitem(
            sys.modules,
            "rembg",
            SimpleNamespace(new_session=new_session, remove=remove),
        )

        remover = RembgRemover(settings)
        first = asyncio.create_task(remover.remove(b"first"))
        await asyncio.wait_for(started.wait(), timeout=1)

        second = asyncio.create_task(remover.remove(b"second"))
        await asyncio.sleep(0.05)
        assert remover._waiting_requests == 1

        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        assert remover._waiting_requests == 0

        third = asyncio.create_task(remover.remove(b"third"))
        await asyncio.sleep(0.05)
        assert remover._waiting_requests == 1

        release.set()
        assert await asyncio.wait_for(first, timeout=1) == png_bytes
        assert await asyncio.wait_for(third, timeout=1) == png_bytes
        assert remover._waiting_requests == 0
        assert remover._active_requests == 0

    started_loop = None

    asyncio.run(exercise())

    assert entered == 2

