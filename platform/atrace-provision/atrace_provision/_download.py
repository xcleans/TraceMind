"""Download helpers with caching."""

from __future__ import annotations

import urllib.request
from pathlib import Path

CACHE_DIR = Path.home() / ".local" / "share" / "atrace" / "prebuilts"


def download(url: str, dest: Path, show_progress: bool = True) -> Path:
    """Download *url* to *dest*, with optional progress output."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    try:
        print(f"  Downloading {url}")
        with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as f:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if show_progress and total:
                    pct = downloaded * 100 // total
                    print(f"\r  Progress: {pct}%", end="", flush=True)
        if show_progress:
            print()
        tmp.rename(dest)
        return dest
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Download failed: {url}: {e}") from e


def download_cached(name: str, url: str) -> Path:
    """Download to cache dir; skip if already present."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = CACHE_DIR / name
    if dest.exists():
        return dest
    return download(url, dest)
