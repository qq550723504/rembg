from io import BytesIO

from PIL import Image


def test_health_is_public(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["model"] == "birefnet-general"


def test_upload_requires_api_key(client, png_bytes):
    response = client.post(
        "/v1/remove-background",
        files={"file": ("input.png", png_bytes, "image/png")},
    )

    assert response.status_code == 401


def test_upload_returns_transparent_png(authenticated_client, png_bytes):
    response = authenticated_client.post(
        "/v1/remove-background",
        files={"file": ("input.png", png_bytes, "image/png")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert Image.open(BytesIO(response.content)).mode == "RGBA"


def test_upload_too_large_returns_413(authenticated_client, png_bytes):
    oversized = png_bytes + b"x" * 256
    response = authenticated_client.post(
        "/v1/remove-background",
        files={"file": ("input.png", oversized, "image/png")},
    )

    assert response.status_code == 413


def test_url_endpoint_accepts_json(authenticated_client, fake_fetcher):
    response = authenticated_client.post(
        "/v1/remove-background/url",
        json={"image_url": "https://93.184.216.34/input.png"},
    )

    assert response.status_code == 200
    assert fake_fetcher.urls == ["https://93.184.216.34/input.png"]


def test_url_endpoint_rejects_private_address(authenticated_client):
    response = authenticated_client.post(
        "/v1/remove-background/url",
        json={"image_url": "http://127.0.0.1/image.png"},
    )

    assert response.status_code == 400


def test_models_endpoint_lists_default_and_supported_models(client):
    response = client.get("/v1/models")

    assert response.status_code == 200
    payload = response.json()
    assert payload["default_model"] == "birefnet-general"
    assert {item["name"] for item in payload["models"]} >= {
        "birefnet-general",
        "birefnet-portrait",
    }


def test_upload_passes_requested_model_to_remover(
    authenticated_client, fake_remover, png_bytes
):
    response = authenticated_client.post(
        "/v1/remove-background",
        files={"file": ("input.png", png_bytes, "image/png")},
        data={"model": "birefnet-portrait"},
    )

    assert response.status_code == 200
    assert fake_remover.calls[-1][1] == "birefnet-portrait"


def test_url_passes_requested_model_to_remover(
    authenticated_client, fake_fetcher, fake_remover
):
    response = authenticated_client.post(
        "/v1/remove-background/url",
        json={"image_url": "https://93.184.216.34/input.png", "model": "isnet-anime"},
    )

    assert response.status_code == 200
    assert fake_fetcher.urls == ["https://93.184.216.34/input.png"]
    assert fake_remover.calls[-1][1] == "isnet-anime"


def test_unknown_model_is_rejected_before_upload_processing(
    authenticated_client, fake_remover, png_bytes
):
    response = authenticated_client.post(
        "/v1/remove-background",
        files={"file": ("input.png", png_bytes, "image/png")},
        data={"model": "made-up-model"},
    )

    assert response.status_code == 400
    assert "Unsupported model" in response.json()["detail"]
    assert fake_remover.calls == []
