"""Watching a Project Gorgon player file (character export) on disk.

The game can write Character_<Name>_<Server>.json every time you log out
("Automatically export on logout" under Settings, VIP). The browser can't
know where an uploaded file came from, so the server finds the same file in
the game's Reports folder (or takes a path typed on this computer) and
checks it every 15 seconds. Browsers poll /api/player and update their own
ticks whenever a newer export appears.

Only a small summary of the file ever leaves this module: the character and
server names, export time, Zhia Lian favour, and the quest names.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

CHECK_SECONDS = 15
MAX_BYTES = 25 * 1024 * 1024
NAME_RX = re.compile(r"^Character_[^\\/:*?\"<>|]{1,120}\.json$", re.I)


# ---------------------------------------------------------------- where the game saves exports
def _known_folder(guid: str):
    """Windows known folder (handles moved Documents / OneDrive); None elsewhere."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        g = GUID()
        ctypes.oledll.ole32.CLSIDFromString(guid, ctypes.byref(g))
        out = ctypes.c_wchar_p()
        ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out))
        path = out.value
        ctypes.windll.ole32.CoTaskMemFree(out)
        return Path(path) if path else None
    except Exception:
        return None


def report_folders() -> list[Path]:
    """Folders where Project Gorgon may write Character_*.json, most likely first."""
    found: list[Path] = []
    if os.environ.get("ZHIA_REPORTS_DIR"):
        found.append(Path(os.environ["ZHIA_REPORTS_DIR"]))
    home = Path.home()
    game = Path("Elder Game") / "Project Gorgon" / "Reports"
    if os.name == "nt":
        low = _known_folder("{A520A1A4-1780-4FF6-BD18-167343C5AF16}")  # LocalAppDataLow
        docs = _known_folder("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}")  # Documents
        profile = Path(os.environ.get("USERPROFILE") or home)
        found += [low / game if low else None, profile / "AppData" / "LocalLow" / game,
                  (docs or profile / "Documents") / "Project Gorgon Data" / "Reports"]
    elif sys.platform == "darwin":
        support = home / "Library" / "Application Support"
        found += [support / game,
                  support / "unity.Elder Game.Project Gorgon" / "Reports",  # older Unity naming
                  home / "Documents" / "Project Gorgon Data" / "Reports"]
    else:
        found += [home / ".config" / "unity3d" / game,
                  home / "Documents" / "Project Gorgon Data" / "Reports"]
    out, seen = [], set()
    for p in found:
        if p and str(p).lower() not in seen:
            seen.add(str(p).lower())
            out.append(p)
    return out


def default_folder() -> Path:
    return report_folders()[0]


# ---------------------------------------------------------------- reading an export
class NotAnExport(ValueError):
    pass


def parse_export(raw: bytes) -> dict:
    try:
        d = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("the file isn't complete JSON (the game may still be writing it)") from exc
    if not isinstance(d, dict) or not isinstance(d.get("ActiveQuests"), list):
        raise NotAnExport("that file isn't a Project Gorgon player file")
    npcs = d.get("NPCs") if isinstance(d.get("NPCs"), dict) else {}
    zhia = npcs.get("NPC_ZhiaLian") if isinstance(npcs.get("NPC_ZhiaLian"), dict) else {}
    favor = zhia.get("Favor")
    return {
        "character": str(d.get("Character") or ""),
        "server": str(d.get("ServerName") or ""),
        "timestamp": str(d.get("Timestamp") or ""),
        "favor": favor if isinstance(favor, (int, float)) else (0 if npcs else None),
        "favorLevel": str(zhia.get("FavorLevel") or ""),
        "active": [q for q in d["ActiveQuests"] if isinstance(q, str)],
        "completed": [q for q in d.get("CompletedQuests") or [] if isinstance(q, str)],
        "hash": hashlib.sha1(raw).hexdigest()[:16],
    }


def read_export(path: Path) -> dict:
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise NotAnExport("that file is too big to be a player file")
    return parse_export(path.read_bytes())


# ---------------------------------------------------------------- the watcher
class PlayerWatch:
    def __init__(self, settings_path: Path, interval: int = CHECK_SECONDS):
        self.settings_path = Path(settings_path)
        self.interval = interval
        self._lock = threading.RLock()
        self._thread = None
        self.path: Path | None = None
        self.enabled = False
        self.export: dict | None = None
        self.error: str | None = None
        self.checked = 0.0       # last time we looked at the file
        self.changed = 0.0       # last time a new export was read
        self._sig = None         # (mtime_ns, size) of the last file read
        self._fails = 0
        self._load_settings()

    # ----- settings, kept in the data folder so watching survives a restart
    def _load_settings(self):
        try:
            s = json.loads(self.settings_path.read_text(encoding="utf-8")).get("watch") or {}
        except (OSError, ValueError, AttributeError):
            return
        if s.get("path"):
            self.path = Path(s["path"])
            self.enabled = bool(s.get("enabled"))

    def _save_settings(self):
        try:
            try:
                data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            data["watch"] = {"path": str(self.path) if self.path else None, "enabled": self.enabled}
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.settings_path.with_name(self.settings_path.name + ".part")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self.settings_path)
        except OSError:
            pass  # watching still works this session

    # ----- finding the file
    def locate(self, name: str, character: str = "", server: str = ""):
        """Find a file with this name in the game's Reports folders. Returns (path, export) or (None, None)."""
        name = os.path.basename(name or "")
        if not NAME_RX.match(name):
            return None, None
        for folder in report_folders():
            p = folder / name
            try:
                if p.is_file():
                    exp = read_export(p)
                    if (not character or exp["character"] == character) and (not server or exp["server"] == server):
                        return p, exp
            except (OSError, ValueError):
                continue
        return None, None

    # ----- changing what is watched
    def configure(self, path: Path) -> dict:
        """Watch this file from now on. Raises ValueError with a plain-language reason."""
        path = Path(os.path.expandvars(os.path.expanduser(str(path).strip().strip('"'))))
        if not path.name.lower().endswith(".json"):
            raise ValueError("Choose the Character_….json file the game saved.")
        if not path.is_file():
            raise ValueError(f"There's no file at {path}.")
        try:
            exp = read_export(path)
        except NotAnExport as exc:
            raise ValueError(str(exc)[0].upper() + str(exc)[1:] + ".") from exc
        except (OSError, ValueError) as exc:
            raise ValueError(f"Couldn't read {path.name}: {exc}.") from exc
        with self._lock:
            self.path, self.enabled = path, True
            self._accept(exp, self._signature(path))
            self.checked = time.time()
            self.error = None
            self._save_settings()
        self.start()
        return exp

    def set_enabled(self, enabled: bool):
        with self._lock:
            if not self.path:
                raise ValueError("Import a player file first, then turn on watching.")
            self.enabled = bool(enabled)
            self._save_settings()
        if enabled:
            self.check(force=True)
            self.start()

    # ----- checking
    @staticmethod
    def _signature(path: Path):
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)

    def _accept(self, exp: dict, sig):
        if not self.export or exp["hash"] != self.export["hash"]:
            self.changed = time.time()
        self.export, self._sig, self._fails = exp, sig, 0

    def check(self, force: bool = False) -> None:
        """Look at the file now. Reads it only when it changed (or force)."""
        with self._lock:
            if not self.path:
                return
            self.checked = time.time()
            try:
                sig = self._signature(self.path)
            except OSError:
                self.error = f"Can't find {self.path.name} any more. Was it moved or deleted?"
                return
            if sig == self._sig and not force and self.export:
                self.error = None
                return
            try:
                self._accept(read_export(self.path), sig)
                self.error = None
            except NotAnExport as exc:
                self.error = f"{self.path.name}: {exc}."
            except (OSError, ValueError) as exc:
                # The game may be halfway through writing it: try again next time,
                # and only report a problem if it keeps happening.
                self._fails += 1
                if self._fails >= 2:
                    self.error = f"Can't read {self.path.name}: {exc}."

    def _run(self):
        while True:
            if self.enabled and self.path:
                self.check()
            time.sleep(self.interval)

    def start(self):
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="player-watch", daemon=True)
                self._thread.start()

    # ----- what the page sees
    def status(self, quest_ids=None, local: bool = False) -> dict:
        with self._lock:
            exp = None
            if self.export:
                keep = (lambda q: q in quest_ids) if quest_ids else (lambda q: q.startswith(("Event_Halloween", "Halloween_")))
                exp = {k: v for k, v in self.export.items() if k not in ("active", "completed")}
                exp["active"] = [q for q in self.export["active"] if keep(q)]
                exp["completed"] = [q for q in self.export["completed"] if keep(q)]
                exp["file"] = self.path.name if self.path else ""
            now = time.time()
            due = self.checked + self.interval - now if (self.enabled and self.checked) else self.interval
            return {
                "configured": bool(self.path),
                "enabled": self.enabled,
                "file": self.path.name if self.path else None,
                "path": str(self.path) if (self.path and local) else None,
                "interval": self.interval,
                "checkedAgo": round(now - self.checked, 1) if self.checked else None,
                "nextCheckIn": round(max(0.0, due), 1),
                "error": self.error,
                "export": exp,
            }
