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


def test_remover_caches_sam_sessions_by_model_options(settings, png_bytes, monkeypatch):
    created = []

    def fake_new_session(model_name, providers, **options):
        created.append((model_name, options))
        return object()

    def fake_remove(data, session, force_return_bytes, **options):
        return png_bytes

    monkeypatch.setitem(
        sys.modules,
        "rembg",
        SimpleNamespace(new_session=fake_new_session, remove=fake_remove),
    )
    settings.model_session_cache_size = 4
    remover = RembgRemover(settings)

    remover._remove_sync(
        png_bytes,
        "sam",
        sam_model="sam_vit_b_01ec64",
        sam_quant=False,
    )
    remover._remove_sync(
        png_bytes,
        "sam",
        sam_model="sam_vit_b_01ec64",
        sam_quant=False,
    )
    remover._remove_sync(
        png_bytes,
        "sam",
        sam_model="sam_vit_l_0b3195",
        sam_quant=True,
    )

    assert created == [
        ("sam", {"sam_model": "sam_vit_b_01ec64"}),
        ("sam", {"sam_model": "sam_vit_l_0b3195", "sam_quant": True}),
    ]
