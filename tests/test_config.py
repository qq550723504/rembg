from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_settings_have_safe_defaults():
    settings = Settings(api_key="secret")

    assert settings.model_name == "birefnet-general"
    assert settings.max_upload_bytes == 20 * 1024 * 1024
    assert settings.max_request_bytes == 25 * 1024 * 1024
    assert settings.max_image_pixels == 25_000_000
    assert settings.url_allowed_hosts == ""
    assert settings.rate_limit_per_minute == 30
    assert settings.max_pending_requests == 4
    assert settings.gpu_max_concurrency == 1
    assert settings.model_cache_dir == "/var/lib/rembg"


def test_settings_have_safe_model_cache_default():
    assert Settings(api_key="secret").model_session_cache_size == 2


def test_readme_documents_runtime_contracts():
    readme = read_repo_file("README.md")

    assert "URL_ALLOWED_HOSTS" in readme
    assert "/livez" in readme
    assert "/readyz" in readme
    assert "process-local" in readme
    assert "MODEL_CACHE_DIR=/var/lib/rembg" in readme


def test_cache_path_contract_is_consistent_across_readme_env_and_compose():
    readme = read_repo_file("README.md")
    env_example = read_repo_file(".env.example")
    compose_file = read_repo_file("docker-compose.yml")
    dockerfile = read_repo_file("Dockerfile")

    assert "MODEL_CACHE_DIR=/var/lib/rembg" in readme
    assert "MODEL_CACHE_DIR=/var/lib/rembg" in env_example
    assert "/var/lib/rembg" in compose_file
    assert "U2NET_HOME=/var/lib/rembg" in dockerfile


def test_dockerfile_declares_non_root_runtime_and_cache_ownership_contract():
    dockerfile = read_repo_file("Dockerfile")

    assert "useradd --create-home --shell /usr/sbin/nologin appuser" in dockerfile
    assert "mkdir -p /var/lib/rembg" in dockerfile
    assert "chown -R appuser:appuser /app /var/lib/rembg" in dockerfile
    assert "\nUSER appuser\n" in dockerfile


def test_gitignore_ignores_generated_egg_info_artifacts():
    gitignore = read_repo_file(".gitignore")

    assert "*.egg-info/" in gitignore


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

