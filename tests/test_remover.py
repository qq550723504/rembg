import asyncio
import sys
from types import SimpleNamespace

from PIL import Image

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
