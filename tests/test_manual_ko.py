from fastapi.testclient import TestClient

from assistant_app.main import app

client = TestClient(app)


def test_admin_page_surfaces_korean_docs_link() -> None:
    response = client.get("/admin-page")

    assert response.status_code == 200
    assert "/admin-page/docs-ko" in response.text


def test_admin_page_provider_copy_mentions_ollama_live_apply_support() -> None:
    response = client.get("/admin-page")

    assert response.status_code == 200
    body = response.text
    assert "rule_based" in body
    assert "ollama" in body
    assert "selected model exists" in body


def test_admin_page_docs_surfaces_korean_manual_entries() -> None:
    response = client.get("/admin-page/docs")

    assert response.status_code == 200
    body = response.text
    assert "/admin-page/docs-ko" in body
    assert "/admin-page/manuals/MANUAL_KO.md" in body


def test_admin_page_docs_ko_renders_korean_companion() -> None:
    response = client.get("/admin-page/docs-ko")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert '<html lang="ko">' in body
    assert "Webex Device Assistant 한국어 가이드" in body
    assert "/admin-page/manuals/MANUAL_KO.md" in body
    assert "/admin-page/docs" in body


def test_admin_page_manual_route_serves_korean_manual() -> None:
    response = client.get("/admin-page/manuals/MANUAL_KO.md")

    assert response.status_code == 200
    assert "text/markdown" in response.headers["content-type"]
    assert "# Webex Device Assistant 앱 아키텍처 및 사용 가이드" in response.text


def test_admin_page_docs_ko_sets_korean_language() -> None:
    response = client.get("/admin-page/docs-ko")

    assert response.status_code == 200
    assert '<html lang="ko">' in response.text
