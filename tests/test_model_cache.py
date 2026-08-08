import sys
from types import SimpleNamespace

from app.remover import RembgRemover


def test_remover_caches_sessions_by_model_and_evicts_oldest(
    settings, png_bytes, monkeypatch
):
    created = []

    def fake_new_session(model_name, providers):
        created.append(model_name)
        return object()

    def fake_remove(data, session, force_return_bytes):
        return png_bytes

    monkeypatch.setitem(
        sys.modules,
        "rembg",
        SimpleNamespace(new_session=fake_new_session, remove=fake_remove),
    )
    settings.model_session_cache_size = 1
    remover = RembgRemover(settings)

    remover._remove_sync(png_bytes, "birefnet-general")
    remover._remove_sync(png_bytes, "birefnet-general")
    remover._remove_sync(png_bytes, "birefnet-portrait")
    remover._remove_sync(png_bytes, "birefnet-general")

    assert created == [
        "birefnet-general",
        "birefnet-portrait",
        "birefnet-general",
    ]
