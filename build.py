"""Build the standalone app with PyInstaller, for the system it runs on.

PyInstaller can't build for another system, so build the Windows EXE on
Windows and the Mac app on a Mac (or let GitHub do both: see
.github/workflows/build.yml).

The easy way is to double-click build_exe.bat on Windows or
build_mac.command on a Mac. Each sets up a virtual environment and runs
this script. To run it by hand:

    pip install -r requirements.txt -r requirements-build.txt
    python build.py                 # bundle today's game data, then build
    python build.py --no-snapshot   # smaller; needs internet on its first run

Output: dist/ZhiaLianQuestBrowser.exe on Windows, dist/ZhiaLianQuestBrowser
on a Mac (a program that opens in Terminal when double-clicked).

The snapshot step saves the built quest model (about 50 KB compressed) and
every icon it uses into snapshot/, so the EXE works offline from the first
launch and only downloads game data when Project Gorgon publishes a newer
version.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / "snapshot"
BUILD = ROOT / "build"
NAME = "ZhiaLianQuestBrowser"
WINDOWS = sys.platform == "win32"


def app_version() -> str:
    m = re.search(r'^APP_VERSION = "([^"]+)"', (ROOT / "app.py").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "1.0.0"


def make_snapshot() -> None:
    sys.path.insert(0, str(ROOT))
    from gorgon import GorgonData
    from zhia import build_model

    g = GorgonData(BUILD / "data-cache")
    version, live = g.current_version()
    print(f"Snapshotting game data v{version}{'' if live else ' (from cache, offline)'}...")
    model = build_model(g.load_all(version), version, live)
    shutil.rmtree(SNAPSHOT, ignore_errors=True)
    (SNAPSHOT / "icons").mkdir(parents=True)
    with gzip.open(SNAPSHOT / "model.json.gz", "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(model, fh, separators=(",", ":"), ensure_ascii=False)
    (SNAPSHOT / "snapshot.json").write_text(
        json.dumps({"version": version, "built": model["event"]["built"]}), encoding="utf-8")

    ids = sorted({int(i) for i in re.findall(r"/icon/(\d+)\.png", json.dumps(model))})

    def fetch(icon_id: int) -> bool:
        try:
            (SNAPSHOT / "icons" / f"icon_{icon_id}.png").write_bytes(g.fetch_icon(version, icon_id))
            return True
        except Exception as exc:
            print(f"  icon {icon_id} skipped: {exc}")
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        got = sum(pool.map(fetch, ids))
    size = sum(p.stat().st_size for p in SNAPSHOT.rglob("*") if p.is_file())
    print(f"Snapshot ready: {len(model['quests'])} quests, {got} of {len(ids)} icons, {size // 1024} KB.")


def write_version_file(path: Path, version: str) -> None:
    """Windows file properties (Details tab) for the EXE."""
    parts = [int(x) for x in re.findall(r"\d+", version)][:4]
    parts += [0] * (4 - len(parts))
    t = tuple(parts)
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Zhia Lian Quest Browser'),
      StringStruct('FileDescription', 'Zhia Lian Quest Browser for Project Gorgon'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', '{NAME}'),
      StringStruct('LegalCopyright', 'Game data and icons: some portions copyright Elder Game, LLC.'),
      StringStruct('OriginalFilename', '{NAME}.exe'),
      StringStruct('ProductName', 'Zhia Lian Quest Browser'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")


def build_exe(onedir: bool) -> Path:
    import PyInstaller.__main__

    BUILD.mkdir(exist_ok=True)
    sep = os.pathsep
    args = [
        str(ROOT / "app.py"),
        "--name", NAME,
        "--onedir" if onedir else "--onefile",
        "--console",  # the window shows the address; closing it quits the app
        "--noconfirm", "--clean",
    ]
    if WINDOWS:  # the pumpkin icon and the Details tab only apply to an EXE
        version_file = BUILD / "version_info.txt"
        write_version_file(version_file, app_version())
        args += ["--icon", str(ROOT / "packaging" / "app.ico"), "--version-file", str(version_file)]
    args += [
        "--add-data", f"{ROOT / 'templates'}{sep}templates",
        "--add-data", f"{ROOT / 'static'}{sep}static",
        "--exclude-module", "tkinter",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(BUILD / "pyinstaller"),
        "--specpath", str(BUILD),
    ]
    if (SNAPSHOT / "model.json.gz").exists():
        args += ["--add-data", f"{SNAPSHOT}{sep}snapshot"]
    else:
        print("No snapshot folder: the app will need internet on its first run.")
    PyInstaller.__main__.run(args)
    out = ROOT / "dist" / (NAME if onedir or not WINDOWS else f"{NAME}.exe")
    print(f"\nBuilt {out}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the standalone Zhia Lian Quest Browser")
    ap.add_argument("--no-snapshot", action="store_true", help="don't bundle game data and icons")
    ap.add_argument("--keep-snapshot", action="store_true", help="reuse the existing snapshot/ folder")
    ap.add_argument("--onedir", action="store_true", help="build a folder instead of one file (starts faster)")
    ap.add_argument("--print-version", action="store_true", help="print the app version and stop")
    args = ap.parse_args()
    if args.print_version:
        print(app_version())
        return
    if args.no_snapshot:
        shutil.rmtree(SNAPSHOT, ignore_errors=True)
    elif not (args.keep_snapshot and (SNAPSHOT / "model.json.gz").exists()):
        make_snapshot()
    build_exe(args.onedir)


if __name__ == "__main__":
    main()
