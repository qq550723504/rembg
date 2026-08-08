def test_homepage_serves_ui(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="api-key"' in response.text
    assert 'id="file-input"' in response.text
    assert 'id="url-input"' in response.text
    assert 'id="remove-button"' in response.text


def test_static_assets_are_served(client):
    css = client.get("/static/styles.css")
    javascript = client.get("/static/app.js")

    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert "drop-zone" in css.text
    assert javascript.status_code == 200
    assert javascript.headers["content-type"].startswith("text/javascript")
    assert "/v1/remove-background" in javascript.text
    assert "/v1/remove-background/url" in javascript.text


def test_existing_api_contract_remains_available(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["model"] == "birefnet-general"
