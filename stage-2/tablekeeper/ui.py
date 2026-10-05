"""The browser product: one HTML shell for the screen routes plus its static assets.

Everything is read from the image at start-up and served from memory; the page loads no
external resource.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

STATIC_DIR = Path(__file__).with_name("static")
SCREENS = ("/", "/signup", "/login", "/lookup")

_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}


@dataclass(frozen=True)
class Asset:
    body: bytes
    content_type: str


def _load() -> dict[str, Asset]:
    assets = {}
    for path in STATIC_DIR.iterdir():
        if path.is_file() and path.suffix in _TYPES:
            assets[path.name] = Asset(path.read_bytes(), _TYPES[path.suffix])
    return assets


ASSETS = _load()


def screen() -> Asset:
    """The shell every screen route returns; the client renders the screen for its path."""
    return ASSETS["index.html"]


def asset(name: str) -> Asset | None:
    return None if name == "index.html" else ASSETS.get(name)
