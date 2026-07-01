"""Tests for the static reviewer UI served by the app."""


def test_root_redirects_to_ui(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (307, 308)
    assert resp.headers["location"] == "/ui/"


def test_ui_without_slash_redirects_to_slash(client):
    resp = client.get("/ui", follow_redirects=False)
    assert resp.status_code in (307, 308)
    assert resp.headers["location"] == "/ui/"


def test_ui_page_is_served(client):
    resp = client.get("/ui/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Reviewer Desk" in resp.text


def test_ui_assets_are_served(client):
    css = client.get("/ui/app.css")
    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]

    js = client.get("/ui/app.js")
    assert js.status_code == 200
    assert "SAMPLE_DRAFTS" in js.text


def test_ui_uses_relative_asset_paths(client):
    # Relative links keep the page styled both when served and when opened as a file.
    html = client.get("/ui/").text
    assert 'href="app.css"' in html
    assert 'src="app.js"' in html


def test_ui_mount_does_not_shadow_the_api(client):
    # The static mount is added after the routers, so the API is untouched.
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/openapi.json").status_code == 200
    # A protected route still requires auth (not swallowed by the UI mount).
    assert client.get("/annotations/").status_code == 401
