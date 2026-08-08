import pytest

from app.models import SUPPORTED_MODELS, resolve_model_name


def test_resolve_model_name_uses_default_when_omitted():
    assert resolve_model_name(None, "birefnet-general") == "birefnet-general"


def test_resolve_model_name_accepts_supported_model():
    assert resolve_model_name("birefnet-portrait", "birefnet-general") == "birefnet-portrait"


def test_resolve_model_name_rejects_unknown_model():
    with pytest.raises(ValueError, match="Unsupported model"):
        resolve_model_name("made-up-model", "birefnet-general")


def test_supported_models_exclude_custom_entries():
    assert "u2net_custom" not in SUPPORTED_MODELS
    assert "birefnet-general" in SUPPORTED_MODELS
