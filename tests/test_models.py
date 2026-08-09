import pytest

from app.models import SUPPORTED_MODELS, model_options, resolve_model_name


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


def test_model_options_expose_capabilities_for_every_model():
    options = model_options("birefnet-general-lite")

    assert len(options) == len(SUPPORTED_MODELS)
    assert all(
        set(option["capabilities"]) == {
            "category",
            "supports_alpha_matting",
            "supports_post_process_mask",
            "experimental",
        }
        for option in options
    )

    sam = next(option for option in options if option["name"] == "sam")
    assert sam["capabilities"]["experimental"] is True

    lite = next(
        option for option in options if option["name"] == "birefnet-general-lite"
    )
    assert lite["capabilities"]["supports_alpha_matting"] is True
    assert lite["capabilities"]["supports_post_process_mask"] is True
