"""Fetch external sources safely and convert them to bounded plain text."""

from __future__ import annotations

import asyncio
import io
import ipaddress
import os
import socket
import zipfile
from dataclasses import dataclass

import httpx

from core.config import get_settings
from core.net import UnsafeBaseURLError, validate_base_url

_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
_MAX_ENTRIES = 500
_TEXT_EXTENSIONS = {".md", ".txt", ".html", ".htm", ".csv", ".json"}


class SourceFetchError(ValueError):
    """The source cannot be fetched or safely parsed."""


@dataclass(frozen=True)
class FetchedSource:
    text: str
    mime_type: str
    metadata: dict


def _text_from_html(body: str) -> str:
    from html.parser import HTMLParser

    class Parser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.parts: list[str] = []
            self.title = ""
            self._skip = 0
            self._in_title = False

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "noscript"):
                self._skip += 1
            if tag == "title":
                self._in_title = True

        def handle_endtag(self, tag):
            if tag in ("script", "style", "noscript") and self._skip:
                self._skip -= 1
            if tag == "title":
                self._in_title = False

        def handle_data(self, data):
            if self._in_title:
                self.title += data
            elif not self._skip:
                self.parts.append(data)

    parser = Parser()
    parser.feed(body)
    return "\n".join(parser.parts)


async def _assert_public_host(url: str) -> None:
    """Block literal and DNS-resolved private targets (SSRF guard)."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or ""
    settings = get_settings()
    if settings.local_mode_enabled:
        return
    infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise SourceFetchError("source URL resolves to a private network address")


async def _fetch(url: str, headers: dict[str, str] | None = None) -> bytes:
    try:
        url = validate_base_url(url)
    except UnsafeBaseURLError as exc:
        raise SourceFetchError(str(exc)) from exc
    await _assert_public_host(url)
    timeout = get_settings().embedding_timeout_seconds
    chunks: list[bytes] = []
    total = 0
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=False, headers=headers or {}
        ) as client:
            async with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise SourceFetchError(
                        f"source returned HTTP {response.status_code}"
                    )
                if response.status_code in (301, 302, 303, 307, 308):
                    raise SourceFetchError("redirects are not followed for sources")
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > _MAX_SOURCE_BYTES:
                        raise SourceFetchError("source exceeds the size limit")
                    chunks.append(chunk)
    except (httpx.HTTPError, socket.gaierror) as exc:
        raise SourceFetchError(f"source fetch failed: {type(exc).__name__}") from exc
    return b"".join(chunks)


async def fetch_url(url: str) -> FetchedSource:
    body = await _fetch(url)
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceFetchError("source is not UTF-8 text") from exc
    markdown = _text_from_html(text) if "<html" in text[:2000].lower() else text
    return FetchedSource(
        text=markdown[:_MAX_SOURCE_BYTES],
        mime_type="text/plain",
        metadata={"canonical_url": url},
    )


async def fetch_github(owner: str, repo: str, ref: str | None = None) -> FetchedSource:
    token = os.environ.get("GITHUB_TOKEN")
    api = f"https://api.github.com/repos/{owner}/{repo}/zipball/{ref or 'HEAD'}"
    archive = await _fetch(api, {"Authorization": f"Bearer {token}"} if token else None)
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            names = [name for name in bundle.namelist() if not name.endswith("/")]
            if len(names) > _MAX_ENTRIES:
                raise SourceFetchError("repository has too many files")
            sections: list[str] = []
            total = 0
            for name in names:
                if not name.lower().endswith(tuple(_TEXT_EXTENSIONS)):
                    continue
                info = bundle.getinfo(name)
                if info.file_size > _MAX_SOURCE_BYTES:
                    continue
                total += info.file_size
                if total > _MAX_ARCHIVE_BYTES:
                    raise SourceFetchError("repository text exceeds the size limit")
                data = bundle.read(name)
                try:
                    content = data.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                sections.append(f"# {name}\n\n{content}")
    except zipfile.BadZipFile as exc:
        raise SourceFetchError("GitHub archive is corrupt") from exc
    return FetchedSource(
        text="\n\n".join(sections)[:_MAX_SOURCE_BYTES],
        mime_type="text/markdown",
        metadata={
            "repository": f"{owner}/{repo}",
            "commit": ref or "HEAD",
            "canonical_url": f"https://github.com/{owner}/{repo}/tree/{ref or 'HEAD'}",
        },
    )


def notion_zip_to_markdown(data: bytes) -> FetchedSource:
    """Parse a Notion export ZIP with caps; never trust archive paths."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = [
                name
                for name in archive.namelist()
                if not name.endswith("/")
                and name.lower().endswith(tuple(_TEXT_EXTENSIONS))
            ]
            if len(names) > _MAX_ENTRIES:
                raise SourceFetchError("Notion export has too many pages")
            sections: list[str] = []
            titles: list[str] = []
            total = 0
            for name in names:
                info = archive.getinfo(name)
                if info.file_size > _MAX_SOURCE_BYTES:
                    continue
                total += info.file_size
                if total > _MAX_ARCHIVE_BYTES:
                    raise SourceFetchError("Notion export exceeds the size limit")
                raw = archive.read(name)
                try:
                    content = raw.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                if name.lower().endswith((".html", ".htm")):
                    content = _text_from_html(content)
                title = name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                titles.append(title)
                sections.append(f"# {title}\n\n{content}")
    except zipfile.BadZipFile as exc:
        raise SourceFetchError("Notion export is not a valid ZIP") from exc
    return FetchedSource(
        text="\n\n".join(sections)[:_MAX_SOURCE_BYTES],
        mime_type="text/markdown",
        metadata={"notion_pages": titles},
    )
