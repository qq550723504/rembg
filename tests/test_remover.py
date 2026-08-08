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
