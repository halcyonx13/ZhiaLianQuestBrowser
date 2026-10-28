"""Start the built app and check that it really works on this system.

Run by .github/workflows/build.yml on the Mac and Windows build machines,
after build.py. It uses a made-up player file (no real character data).
Results are printed as GitHub notices, so they show on the build summary.

    python packaging/ci_smoke_test.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = sys.platform == "win32"
MAC = sys.platform == "darwin"
BIN = ROOT / "dist" / ("ZhiaLianQuestBrowser.exe" if WINDOWS else "ZhiaLianQuestBrowser")
VERSION = re.search(r'^APP_VERSION = "([^"]+)"', (ROOT / "app.py").read_text(encoding="utf-8"), re.M).group(1)
PORT = 8123
FILE = "Character_Tester_Dreva.json"
SYSTEM = "macOS" if MAC else ("Windows" if WINDOWS else sys.platform)


def notice(title: str, msg: str) -> None:
    print(f"::notice title={title}::{msg}", flush=True)


def fail(msg: str) -> None:
    print(f"::error title={SYSTEM} test failed::{msg}", flush=True)
    raise SystemExit(1)


def reports_folder() -> Path:
    """Where the game writes player files: the first place the app looks."""
    home = Path.home()
    game = Path("Elder Game") / "Project Gorgon" / "Reports"
    if WINDOWS:
        return Path(os.environ.get("USERPROFILE") or home) / "AppData" / "LocalLow" / game
    if MAC:
        return home / "Library" / "Application Support" / game
    return home / ".config" / "unity3d" / game


def data_folder() -> Path:
    home = Path.home()
    if WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / "ZhiaLianQuestBrowser"
    if MAC:
        return home / "Library" / "Application Support" / "ZhiaLianQuestBrowser"
    return home / ".local" / "share" / "ZhiaLianQuestBrowser"


def write_export(path: Path, favor: int, stamp: str) -> None:
    path.write_text(json.dumps({
        "Character": "Tester", "ServerName": "Dreva", "Timestamp": stamp,
        "Report": "CharacterSheet", "ReportVersion": 1,
        "ActiveQuests": ["Event_Halloween_UseFearAbility", "Event_Halloween_KillMummies"],
        "CompletedQuests": [],
        "NPCs": {"NPC_ZhiaLian": {"FavorLevel": "Neutral", "Favor": favor, "CouncilsSpent": 0, "PlayerNotes": ""}},
    }), encoding="utf-8")


def get(url: str, timeout: float = 120):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def post(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read() or b"{}") | {"_status": exc.code}


def start(args: list[str], log: Path) -> subprocess.Popen:
    env = dict(os.environ, ZHIA_NO_BROWSER="1")
    fh = open(log, "wb")
    return subprocess.Popen([str(BIN), *args], stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT, env=env)


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if WINDOWS:  # a one-file EXE runs as two processes; end both
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


def wait_up(base: str, proc: subprocess.Popen, seconds: int = 90) -> float:
    t0 = time.time()
    while time.time() - t0 < seconds:
        if proc.poll() is not None:
            return -1
        try:
            if json.loads(get(base + "healthz", timeout=3)[2]).get("app") == "ZhiaLianQuestBrowser":
                return time.time() - t0
        except Exception:
            time.sleep(0.5)
    return -1


def main() -> None:
    if not BIN.exists():
        fail(f"{BIN} wasn't built.")
    if MAC:
        arch = subprocess.run(["file", str(BIN)], capture_output=True, text=True).stdout.strip()
        notice("Built", arch.split(": ", 1)[-1])

    out = subprocess.run([str(BIN), "--help"], capture_output=True, text=True, timeout=120,
                         env=dict(os.environ, ZHIA_NO_BROWSER="1"))
    if out.returncode != 0 or "--localhostonly" not in out.stdout:
        fail(f"--help didn't work (exit {out.returncode}): {out.stdout[-400:]} {out.stderr[-400:]}")

    folder = reports_folder()
    folder.mkdir(parents=True, exist_ok=True)
    export = folder / FILE
    write_export(export, 64, "2026-10-29 10:00:00Z")

    log = ROOT / "dist" / "run-test.log"
    base = f"http://127.0.0.1:{PORT}/"
    proc = start([f"--port:{PORT}", "--localhostonly", "--no-browser"], log)
    try:
        took = wait_up(base, proc)
        if took < 0:
            fail("The app didn't start. Its output: " + log.read_text(errors="replace")[-800:])
        health = json.loads(get(base + "healthz")[2])
        if health.get("version") != VERSION:
            fail(f"Expected version {VERSION}, the app says {health}")

        status, ctype, page = get(base)
        if status != 200 or b"Zhia Lian Quest Browser" not in page:
            fail("The page didn't load.")
        status, ctype, _ = get(base + "static/fonts/pirata-one-latin-400-normal.woff2")
        if status != 200:
            fail("The bundled fonts are missing.")
        model = json.loads(get(base + "api/event", timeout=300)[2])
        quests = model.get("quests") or []
        if len(quests) < 100:
            fail(f"Only {len(quests)} quests loaded: {str(model)[:300]}")
        icon = re.search(r"/icon/(\d+)\.png", json.dumps(model))
        if icon and get(base + f"icon/{icon.group(1)}.png")[0] != 200:
            fail("Quest icons don't load.")
        notice("Runs", f"Started in {took:.1f}s; game data v{model['event']['version']} "
                       f"({model['event'].get('source')}), {len(quests)} quests")

        found = post(base + "api/player/locate", {"file": FILE, "character": "Tester", "server": "Dreva"})
        if not found.get("found"):
            fail(f"Didn't find {FILE} in {folder}: {found}")
        st = post(base + "api/player/watch", {"file": FILE, "character": "Tester", "server": "Dreva"})
        if not st.get("enabled") or (st.get("export") or {}).get("favor") != 64:
            fail(f"Watching didn't start: {st}")
        time.sleep(1.2)
        write_export(export, 66, "2026-10-29 10:05:00Z")  # the game saves again
        st = post(base + "api/player/recheck", {})
        if (st.get("export") or {}).get("favor") != 66:
            fail(f"The new save wasn't picked up: {st}")
        if not (data_folder() / "settings.json").exists():
            fail(f"No settings.json in {data_folder()}")
        notice("Player file", f"Found and watched {folder / FILE}; a new save updated favour 64 to 66")
    finally:
        stop(proc)
        print("--- app output ---\n" + log.read_text(errors="replace"), flush=True)

    # The default address, 0.0.0.0 port 80, without admin rights. This depends on the
    # system's rules rather than the app, so it's reported but doesn't fail the build.
    log80 = ROOT / "dist" / "run-port80.log"
    proc = start(["--no-browser"], log80)
    try:
        took = wait_up("http://127.0.0.1/", proc, seconds=60)
        if took >= 0:
            who = "as an ordinary user" if not WINDOWS and os.geteuid() != 0 else "on this build machine"
            notice("Port 80", f"Started on the default 0.0.0.0:80 {who} ({took:.1f}s)")
        else:
            text = log80.read_text(errors="replace").strip().replace("\n", " ")
            print(f"::warning title=Port 80::Couldn't use the default port 80 here: {text[-300:]}", flush=True)
    finally:
        stop(proc)
    print(f"{SYSTEM}: all checks passed.", flush=True)


if __name__ == "__main__":
    main()
