def test_homepage_serves_ui(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="api-key"' in response.text
    assert 'id="file-input"' in response.text
    assert 'id="url-input"' in response.text
    assert 'id="remove-button"' in response.text
    assert 'id="model-select"' in response.text


def test_homepage_includes_advanced_removal_controls(client):
    response = client.get("/")

    assert response.status_code == 200
    for control_id in (
        "alpha-matting",
        "alpha-matting-foreground-threshold",
        "alpha-matting-background-threshold",
        "alpha-matting-erode-size",
        "post-process-mask",
    ):
        assert f'id="{control_id}"' in response.text


def test_static_assets_are_served(client):
    css = client.get("/static/styles.css")
    javascript = client.get("/static/app.js")

    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert "drop-zone" in css.text
    assert "[hidden]" in css.text
    assert javascript.status_code == 200
    assert javascript.headers["content-type"].startswith("text/javascript")
    assert "/v1/remove-background" in javascript.text
    assert "/v1/remove-background/url" in javascript.text
    assert "/v1/models" in javascript.text
    assert '"model"' in javascript.text


def test_static_javascript_serializes_advanced_removal_options(client):
    response = client.get("/static/app.js")

    assert response.status_code == 200
    javascript = response.text
    for field in (
        "alpha_matting",
        "alpha_matting_foreground_threshold",
        "alpha_matting_background_threshold",
        "alpha_matting_erode_size",
        "post_process_mask",
    ):
        assert field in javascript
    assert "getRemovalOptions" in javascript
    assert 'body.append("alpha_matting"' in javascript


def test_static_javascript_rejects_empty_advanced_numeric_values(client):
    response = client.get("/static/app.js")

    assert response.status_code == 200
    javascript = response.text
    assert 'input.value.trim() === ""' in javascript
    assert "if (!removalOptions)" in javascript


def test_existing_api_contract_remains_available(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["model"] == "birefnet-general"


def test_homepage_includes_cancel_control_and_image_dialog(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="image-dialog"' in response.text
    assert 'role="dialog"' in response.text
    assert 'aria-modal="true"' in response.text
    assert 'id="dialog-close"' in response.text
    assert 'id="original-preview-trigger"' in response.text
    assert 'id="result-preview-trigger"' in response.text


def test_static_javascript_supports_abort_and_large_preview(client):
    response = client.get("/static/app.js")
    assert response.status_code == 200
    assert "AbortController" in response.text
    assert "signal: controller.signal" in response.text
    assert 'error.name === "AbortError"' in response.text
    assert "openPreview" in response.text
    assert 'event.key === "Escape"' in response.text
    assert "originalPreviewTrigger" in response.text
    assert "resultPreviewTrigger" in response.text


def test_static_javascript_keeps_image_dialog_keyboard_modal(client):
    response = client.get("/static/app.js")

    assert response.status_code == 200
    assert "previewOpener" in response.text
    assert 'event.key !== "Tab"' in response.text
    assert "opener.focus()" in response.text


def test_static_javascript_closes_dialog_before_revoking_displayed_result(client):
    response = client.get("/static/app.js")

    assert response.status_code == 200
    javascript = response.text
    clear_object_url = javascript[
        javascript.index("function clearObjectUrl") : javascript.index(
            "function setOriginalPreview"
        )
    ]
    open_preview = javascript[
        javascript.index("function openPreview") : javascript.index(
            "function closePreview"
        )
    ]
    close_preview = javascript[
        javascript.index("function closePreview") : javascript.index(
            "function setSource"
        )
    ]

    assert "if (dialogUrl === state[key]) closePreview();" in clear_object_url
    assert "dialogUrl = url;" in open_preview
    assert "dialogUrl = null;" in close_preview
