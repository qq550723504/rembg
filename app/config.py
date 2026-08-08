from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: str = Field(min_length=1)
    model_name: str = "birefnet-general"
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    max_image_pixels: int = Field(default=25_000_000, ge=1)
    url_allowed_hosts: str = ""
    rate_limit_per_minute: int = Field(default=30, ge=1)
    max_pending_requests: int = Field(default=4, ge=0)
    url_fetch_timeout_seconds: float = Field(default=15.0, gt=0)
    gpu_max_concurrency: int = Field(default=1, ge=1)
    model_session_cache_size: int = Field(default=2, ge=1)
    model_cache_dir: str = "/root/.u2net"
