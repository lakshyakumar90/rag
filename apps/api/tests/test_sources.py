"""URL, GitHub and Notion source parsing with caps and provenance."""

import io
import zipfile

import pytest

from services.sources import (
    SourceFetchError,
    fetch_github,
    fetch_url,
    notion_zip_to_markdown,
)


def _zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


async def test_url_source_keeps_canonical_url(monkeypatch) -> None:
    import services.sources as sources

    async def fake_fetch(url, headers=None):
        return b"<html><title>Guide</title><body>Useful URL text</body></html>"

    async def no_private(url):
        return None

    monkeypatch.setattr(sources, "_fetch", fake_fetch)
    monkeypatch.setattr(sources, "_assert_public_host", no_private)
    result = await fetch_url("https://example.com/guide")
    assert result.metadata["canonical_url"] == "https://example.com/guide"
    assert "Useful URL text" in result.text


async def test_github_source_keeps_repository_and_commit(monkeypatch) -> None:
    import services.sources as sources

    archive = _zip({"repo-main/README.md": "# Readme\nHello repository"})

    async def fake_fetch(url, headers=None):
        assert "zipball/main" in url
        return archive

    async def no_private(url):
        return None

    monkeypatch.setattr(sources, "_fetch", fake_fetch)
    monkeypatch.setattr(sources, "_assert_public_host", no_private)
    result = await fetch_github("acme", "docs", "main")
    assert result.metadata["repository"] == "acme/docs"
    assert result.metadata["commit"] == "main"
    assert "Hello repository" in result.text


def test_notion_export_preserves_page_titles() -> None:
    data = _zip(
        {
            "Export Page One.md": "# One\nFirst page body",
            "Export Page Two.html": "<html><body>Second page body</body></html>",
        }
    )
    result = notion_zip_to_markdown(data)
    assert result.metadata["notion_pages"] == ["Export Page One", "Export Page Two"]
    assert "First page body" in result.text
    assert "Second page body" in result.text


async def test_source_endpoint_enqueues_and_records_provenance(client) -> None:
    PASSWORD = "StrongPassw0rd!"
    await client.post(
        "/api/v1/auth/register",
        json={"email": "source-owner@example.com", "password": PASSWORD},
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "source-owner@example.com", "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    workspace = await client.post(
        "/api/v1/workspaces",
        headers=headers,
        json={"name": "Sources", "slug": "sources"},
    )
    workspace_id = workspace.json()["id"]
    response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/sources",
        headers=headers,
        json={"type": "url", "url": "https://example.com/guide"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source_type"] == "url"
    assert body["source_url"] == "https://example.com/guide"


def test_notion_export_rejects_bad_zip() -> None:
    with pytest.raises(SourceFetchError):
        notion_zip_to_markdown(b"not a zip")
