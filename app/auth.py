import secrets

from fastapi import HTTPException, status


def require_api_key(settings, supplied_key: str | None) -> None:
    if not supplied_key or not secrets.compare_digest(supplied_key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
