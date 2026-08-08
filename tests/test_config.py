import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_have_safe_defaults():
    settings = Settings(api_key="secret")

    assert settings.model_name == "birefnet-general"
    assert settings.max_upload_bytes == 20 * 1024 * 1024
    assert settings.max_image_pixels == 25_000_000
    assert settings.url_allowed_hosts == ""
    assert settings.rate_limit_per_minute == 30
    assert settings.max_pending_requests == 4
    assert settings.gpu_max_concurrency == 1


def test_settings_have_safe_model_cache_default():
    assert Settings(api_key="secret").model_session_cache_size == 2


def test_settings_require_api_key():
    with pytest.raises(ValidationError):
        Settings(api_key="")


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("rate_limit_per_minute", 0),
        ("rate_limit_per_minute", -1),
        ("max_pending_requests", -1),
    ],
)
def test_settings_reject_non_positive_runtime_limits(field_name, value):
    with pytest.raises(ValidationError):
        Settings(api_key="secret", **{field_name: value})
