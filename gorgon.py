"""Minimal Project Gorgon data client.

Reads the current data version, downloads the JSON files the app needs and
caches them on disk under cache/v{version}/. If the version server can't be
reached, it can fall back to the newest version already in the cache, so the
app keeps working offline once it has run once.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

VERSION_URL = "https://client.projectgorgon.com/fileversion.txt"
DATA_URL = "https://cdn.projectgorgon.com/v{v}/data/{name}"
ICON_URL = "https://cdn.projectgorgon.com/v{v}/icons/icon_{id}.png"

# Every file the Zhia Lian model reads.
FILES = [
    "quests.json",
    "items.json",
    "npcs.json",
    "areas.json",
    "recipes.json",
    "sources_items.json",
    "sources_recipes.json",
    "playertitles.json",
    "abilities.json",
    "effects.json",
    "skills.json",
    "attributes.json",
    "Translation/strings_requested.json",
]


class DataUnavailable(RuntimeError):
    """Raised when no data version can be fetched or found in the cache."""


def version_key(v: str):
    """Sort key: numeric versions in order, anything else after them."""
    return (v.isdigit(), int(v) if v.isdigit() else 0, v)


class GorgonData:
    def __init__(self, cache_dir: Path, timeout: int = 60):
        self.cache_dir = Path(cache_dir)
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "ZhiaLianQuestBrowser/1.2"
        self._lock = threading.Lock()
        self._plock = threading.Lock()
        # What the downloader is doing, for the page's progress messages.
        self.progress = {"active": False, "version": None, "done": 0, "total": len(FILES)}

    # ---------- versions ----------
    def cached_versions(self) -> list[str]:
        """Versions with every needed file already on disk, newest first."""
        found = []
        if self.cache_dir.exists():
            for d in self.cache_dir.iterdir():
                if d.is_dir() and re.fullmatch(r"v[A-Za-z0-9]+", d.name) and all((d / f).exists() for f in FILES):
                    found.append(d.name[1:])
        return sorted(found, key=version_key, reverse=True)

    def current_version(self, allow_cached: bool = True) -> tuple[str, bool]:
        """Return (version, is_live).

        With allow_cached, falls back to the newest cached version when the
        version server can't be reached; otherwise raises DataUnavailable.
        """
        try:
            r = self.session.get(VERSION_URL, timeout=15)
            r.raise_for_status()
            text = r.text.strip()
            if re.fullmatch(r"[A-Za-z0-9]+", text):
                return text, True
            raise ValueError(f"unexpected version text: {text!r}")
        except Exception as exc:  # network down, odd response, etc.
            cached = self.cached_versions() if allow_cached else []
            if cached:
                return cached[0], False
            raise DataUnavailable(
                "Couldn't reach client.projectgorgon.com to read the game data version. "
                "Check your internet connection and try again."
            ) from exc

    # ---------- files ----------
    def _folder(self, version: str) -> Path:
        return self.cache_dir / f"v{version}"

    def _fetch_to(self, version: str, name: str, folder: Path, force: bool) -> Path:
        path = folder / name
        if path.exists() and not force:
            return path
        r = self.session.get(DATA_URL.format(v=version, name=name), timeout=self.timeout)
        r.raise_for_status()
        # A missing version or file still answers 200, with an HTML page.
        if "json" not in r.headers.get("content-type", ""):
            raise DataUnavailable(f"v{version}/{name} isn't on the CDN (got a non-JSON page).")
        json.loads(r.content.decode("utf-8-sig"))  # never cache a truncated file
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        tmp.write_bytes(r.content)
        tmp.replace(path)  # atomic, so a half-written file is never used
        return path

    def _tick(self, **kw):
        with self._plock:
            self.progress.update(kw)

    def download(self, version: str, force: bool = False) -> Path:
        """Make sure every file for this version is on disk.

        force downloads everything again into a side folder and swaps it in
        only when all files arrived, so a failed refresh leaves the cache intact.
        """
        with self._lock:
            final = self._folder(version)
            target = final.with_name(final.name + ".new") if force else final
            if force:
                shutil.rmtree(target, ignore_errors=True)
            missing = [n for n in FILES if force or not (final / n).exists()]
            self._tick(active=bool(missing), version=version, total=len(FILES),
                       done=len(FILES) - len(missing))
            try:
                with ThreadPoolExecutor(max_workers=6) as pool:
                    futures = [pool.submit(self._fetch_to, version, n, target, force) for n in missing]
                    for fut in futures:
                        fut.result()
                        with self._plock:
                            self.progress["done"] += 1
                if force:
                    old = final.with_name(final.name + ".old")
                    shutil.rmtree(old, ignore_errors=True)
                    if final.exists():
                        final.rename(old)
                    target.rename(final)
                    shutil.rmtree(old, ignore_errors=True)
            finally:
                self._tick(active=False)
            return final

    def load_all(self, version: str, force: bool = False) -> dict:
        """Download (if needed) and parse every file. Keys drop '.json' and the folder."""
        folder = self.download(version, force=force)
        data = {}
        for name in FILES:
            key = name.rsplit("/", 1)[-1].removesuffix(".json")
            data[key] = json.loads((folder / name).read_text(encoding="utf-8-sig"))
        return data

    def prune(self, keep: int = 2) -> list[str]:
        """Delete all but the newest `keep` complete versions (about 50 MB each)."""
        removed = []
        for v in self.cached_versions()[keep:]:
            shutil.rmtree(self._folder(v), ignore_errors=True)
            removed.append(v)
        return removed

    def fetch_icon(self, version: str, icon_id: int) -> bytes:
        """Download one icon PNG. A missing icon answers 200 with HTML, so check the type."""
        r = self.session.get(ICON_URL.format(v=version, id=icon_id), timeout=20)
        r.raise_for_status()
        if "image/png" not in r.headers.get("content-type", ""):
            raise DataUnavailable(f"icon {icon_id} isn't on the CDN")
        return r.content

    @staticmethod
    def icon_url(version: str, icon_id) -> str | None:
        """Icons go through the app's /icon route, which caches them for offline use."""
        if not icon_id:
            return None
        return f"/icon/{int(icon_id)}.png"
