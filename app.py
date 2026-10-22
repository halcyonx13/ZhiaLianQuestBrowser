"""Zhia Lian Quest Browser: a small Flask app over the Project Gorgon data CDN.

Run from source:   python app.py [--port:N] [--localhostonly] [--no-browser]
As a Windows EXE:  ZhiaLianQuestBrowser.exe with the same options (see build.py)

By default it listens on 0.0.0.0:80, so other devices on your network can use
it too, and opens your browser at http://localhost/.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import re
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from flask import Flask, Response, render_template, request, send_file

from gorgon import DataUnavailable, GorgonData, version_key
from zhia import build_model

APP_NAME = "ZhiaLianQuestBrowser"
APP_TITLE = "Zhia Lian Quest Browser"
APP_VERSION = "1.2.0"
FROZEN = getattr(sys, "frozen", False)

# Read-only files (templates, static, snapshot) live next to this file, or
# inside the EXE's temporary unpack folder when frozen.
RES_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def _data_dir() -> Path:
    """Writable folder for the download cache: %LOCALAPPDATA% when frozen."""
    if os.environ.get("ZHIA_DATA_DIR"):
        return Path(os.environ["ZHIA_DATA_DIR"])
    if FROZEN:
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
        return Path(base) / APP_NAME
    return Path(__file__).resolve().parent


DATA_DIR = _data_dir()
CACHE_DIR = Path(os.environ.get("ZHIA_CACHE_DIR", DATA_DIR / "cache"))
ICON_CACHE = CACHE_DIR / "icons"
SNAPSHOT_DIR = RES_DIR / "snapshot"  # optional, written by build.py
CHECK_EVERY = int(os.environ.get("ZHIA_CHECK_MINUTES", "30")) * 60
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 80

app = Flask(__name__, template_folder=str(RES_DIR / "templates"), static_folder=str(RES_DIR / "static"))
gorgon = GorgonData(CACHE_DIR)
_lock = threading.Lock()
_state: dict = {"body": None, "gz": None, "etag": None, "checked": 0.0,
                "version": None, "source": None, "live": False}


# ---------------------------------------------------------------- data
def snapshot_version():
    try:
        return json.loads((SNAPSHOT_DIR / "snapshot.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        return None


def _snapshot_model() -> dict:
    with gzip.open(SNAPSHOT_DIR / "model.json.gz", "rt", encoding="utf-8") as fh:
        model = json.load(fh)
    model["event"].update(live=False, source="snapshot")
    return model


def _build(version: str, live: bool, force: bool = False) -> dict:
    model = build_model(gorgon.load_all(version, force=force), version, live)
    model["event"]["source"] = "live" if live else "cache"
    return model


def _choose_model() -> dict:
    """Newest data we can get: download from the CDN, else the cache, else the bundled snapshot."""
    snap = snapshot_version()
    try:
        version, live = gorgon.current_version()  # offline: newest cached version
    except DataUnavailable:
        version, live = None, False
    offline_snapshot_is_newer = not live and snap and version and version_key(snap) > version_key(version)
    if version and not offline_snapshot_is_newer:
        try:
            model = _build(version, live)  # first run: downloads every file
            if live:
                gorgon.prune()
            return model
        except Exception as exc:
            app.logger.warning("  Couldn't load game data v%s: %s", version, exc)
        for v in gorgon.cached_versions():
            if v != version:
                try:
                    return _build(v, False)
                except Exception as exc:
                    app.logger.warning("  Couldn't load cached data v%s: %s", v, exc)
    if snap:
        return _snapshot_model()
    raise DataUnavailable(
        "Couldn't reach the Project Gorgon servers and there is no saved copy of the quest data yet. "
        "Check your internet connection and try again."
    )


def _install(model: dict) -> None:
    ev = model["event"]
    body = json.dumps(model, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    _state.update(
        version=ev["version"], source=ev.get("source"), live=ev.get("live"),
        body=body, gz=gzip.compress(body, 6),
        etag='"' + hashlib.sha1(body).hexdigest()[:24] + '"',  # tag by content, not version
    )
    app.logger.info("  Using game data v%s (%s)", ev["version"], ev.get("source"))


def current_payload() -> dict:
    """The served model. Every CHECK_EVERY seconds, looks for a newer game data version."""
    with _lock:
        now = time.time()
        if _state["body"] and now - _state["checked"] < CHECK_EVERY:
            return _state
        _state["checked"] = now
        if _state["body"]:
            try:
                version, _live = gorgon.current_version(allow_cached=False)
            except DataUnavailable:
                return _state  # offline: keep what we have
            if version == _state["version"] and _state["source"] == "live":
                return _state
        try:
            _install(_choose_model())
        except DataUnavailable:
            if not _state["body"]:
                raise
        return _state


def refresh(force: bool) -> tuple[dict, int]:
    """Look for newer game data (or download it all again) and switch to it."""
    with _lock:
        prev = _state["version"]
        try:
            version, _live = gorgon.current_version(allow_cached=False)
        except DataUnavailable as exc:
            return {"error": str(exc)}, 503
        _state["checked"] = time.time()
        if version == prev and _state["source"] == "live" and not force:
            return {"updated": False, "version": version,
                    "message": f"You already have the newest game data, v{version}."}, 200
        try:
            model = _build(version, True, force=force)
        except Exception as exc:
            return {"error": f"Couldn't download game data v{version}: {exc}"}, 502
        _install(model)
        gorgon.prune()
    if prev and prev != version:
        msg = f"Updated the game data from v{prev} to v{version}."
    else:
        msg = f"Downloaded all game data files for v{version} again."
    return {"updated": True, "version": version, "previous": prev, "message": msg}, 200


# ---------------------------------------------------------------- routes
@app.get("/")
def index():
    return render_template("index.html", app_version=APP_VERSION)


@app.get("/healthz")
def healthz():
    return {"app": APP_NAME, "version": APP_VERSION}


@app.get("/api/event")
def api_event():
    try:
        st = current_payload()
    except Exception as exc:  # network or data problem on first load
        msg = str(exc) if isinstance(exc, DataUnavailable) else f"Couldn't load the game data: {exc}"
        return Response(json.dumps({"error": msg}), status=503, mimetype="application/json")
    if request.headers.get("If-None-Match") == st["etag"]:
        return Response(status=304, headers={"ETag": st["etag"], "Cache-Control": "no-cache"})
    use_gz = "gzip" in request.headers.get("Accept-Encoding", "")
    resp = Response(st["gz"] if use_gz else st["body"], mimetype="application/json")
    if use_gz:
        resp.headers["Content-Encoding"] = "gzip"
    resp.headers["Vary"] = "Accept-Encoding"
    resp.headers["ETag"] = st["etag"]
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.post("/api/refresh")
def api_refresh():
    body = request.get_json(silent=True) or {}
    result, status = refresh(force=bool(body.get("force")))
    return Response(json.dumps(result), status=status, mimetype="application/json")


@app.get("/api/status")
def api_status():
    """Cheap, lock-free: what data is in use and how a running download is going."""
    return {"version": _state["version"], "source": _state["source"], "live": _state["live"],
            "checked": _state["checked"], "download": dict(gorgon.progress)}


@app.get("/icon/<int:icon_id>.png")
def icon(icon_id: int):
    """Game icons: from the download cache, the bundled snapshot, or the CDN (then cached)."""
    name = f"icon_{icon_id}.png"
    for folder in (ICON_CACHE, SNAPSHOT_DIR / "icons"):
        path = folder / name
        if path.is_file():
            return send_file(path, mimetype="image/png", max_age=7 * 86400)
    version = _state["version"] or snapshot_version()
    if version:
        try:
            data = gorgon.fetch_icon(version, icon_id)
            ICON_CACHE.mkdir(parents=True, exist_ok=True)
            (ICON_CACHE / name).write_bytes(data)
            resp = Response(data, mimetype="image/png")
            resp.headers["Cache-Control"] = "max-age=604800"
            return resp
        except Exception:
            pass
    return Response(status=404)


# ---------------------------------------------------------------- launcher
USAGE = f"""{APP_TITLE} {APP_VERSION}

Usage: ZhiaLianQuestBrowser [--port:N] [--localhostonly] [--no-browser]

  --port:N          Listen on port N instead of {DEFAULT_PORT}. Also --port N or --port=N.
  --localhostonly   Only accept connections from this computer (127.0.0.1),
                    instead of from your whole network (0.0.0.0).
  --no-browser      Don't open a browser window on start.
"""


def parse_args(argv: list[str]) -> dict:
    opts = {
        "host": os.environ.get("HOST", DEFAULT_HOST),
        "port": int(os.environ.get("PORT", DEFAULT_PORT)),
        "browser": os.environ.get("ZHIA_NO_BROWSER") != "1",
    }
    i = 0
    while i < len(argv):
        arg = argv[i]
        low = arg.lower()
        m = re.fullmatch(r"(?:--?|/)port[:=](\d+)", low)
        if m:
            opts["port"] = int(m.group(1))
        elif low in ("--port", "-port", "/port", "-p") and i + 1 < len(argv) and argv[i + 1].isdigit():
            opts["port"] = int(argv[i + 1])
            i += 1
        elif low in ("--localhostonly", "--localhost-only", "-localhostonly", "/localhostonly"):
            opts["host"] = "127.0.0.1"
        elif low in ("--no-browser", "--nobrowser", "/nobrowser"):
            opts["browser"] = False
        elif low in ("-h", "--help", "/?", "-?", "/help"):
            print(USAGE)
            sys.exit(0)
        else:
            _fail(f"Unknown option: {arg}\n\n{USAGE}", code=2)
        i += 1
    if not 1 <= opts["port"] <= 65535:
        _fail(f"Port {opts['port']} isn't valid. Use a number from 1 to 65535, for example --port:8080.", code=2)
    return opts


def _fail(message: str, code: int = 1):
    print("\n  " + message.replace("\n", "\n  ") + "\n", flush=True)
    if FROZEN and sys.stdin and sys.stdin.isatty():  # keep a double-clicked window open
        try:
            input("  Press Enter to close this window.")
        except EOFError:
            pass
    sys.exit(code)


def _is_ours(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1.5) as r:
            return json.loads(r.read().decode()).get("app") == APP_NAME
    except Exception:
        return False


def _bind_problem(host: str, port: int):
    """None if we can listen there, else a plain-language reason."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return None
        except PermissionError:
            return (f"This computer won't let the app use port {port} without administrator rights.\n"
                    f"Start it with a higher port instead, for example: --port:8080")
        except OSError:
            return (f"Port {port} is already in use by another program (often a web server or Skype).\n"
                    f"Start the app with a different port, for example: --port:8080")


def _lan_addresses() -> list[str]:
    found = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; this just picks the outgoing interface
            found.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        found.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    return sorted(a for a in found if not a.startswith(("127.", "169.254.")))


def _url(host: str, port: int) -> str:
    return f"http://{host}{'' if port == 80 else f':{port}'}/"


def _warm():
    try:
        current_payload()
    except Exception as exc:  # shown in the page on first load instead
        app.logger.warning("  Couldn't load game data yet: %s", exc)


def main(argv=None):
    opts = parse_args(sys.argv[1:] if argv is None else argv)
    host, port = opts["host"], opts["port"]
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("waitress").setLevel(logging.ERROR)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    if FROZEN and os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(APP_TITLE)
        except Exception:
            pass

    local_url = _url("localhost", port)
    if _is_ours(port):  # already running: just bring the page up again
        print(f"\n  {APP_TITLE} is already running at {local_url}\n", flush=True)
        if opts["browser"]:
            webbrowser.open(local_url)
        if FROZEN:
            time.sleep(3)
        return
    problem = _bind_problem(host, port)
    if problem:
        _fail(problem)

    lines = [f"{APP_TITLE} {APP_VERSION}", f"On this computer: {local_url}"]
    if host == "0.0.0.0":
        lan = _lan_addresses()
        if lan:
            lines.append("From other devices on your network: " + ", ".join(_url(a, port) for a in lan))
    else:
        lines.append("Only this computer can connect (--localhostonly).")
    lines += [f"Data folder: {DATA_DIR}", "Close this window to quit."]
    print("\n  " + "\n  ".join(lines) + "\n", flush=True)

    threading.Thread(target=_warm, daemon=True).start()
    if opts["browser"]:
        threading.Timer(1.2, webbrowser.open, args=[local_url]).start()
    try:
        from waitress import serve
        serve(app, host=host, port=port, threads=8, ident=APP_NAME)
    except ImportError:  # running from source without waitress installed
        app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
