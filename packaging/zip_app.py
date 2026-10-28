"""Zip the built Mac app so it unzips as one runnable file.

    python packaging/zip_app.py dist/ZhiaLianQuestBrowser dist/ZhiaLianQuestBrowser-1.3.1-mac-intel.zip

The zip holds just ZhiaLianQuestBrowser at the top, marked as runnable
(Unix mode 755), with none of the Mac's extra file attributes. A plain
upload to GitHub would drop the runnable mark, so the workflow uploads this
zip instead.
"""
from __future__ import annotations

import sys
import time
import zipfile
from pathlib import Path


def make_zip(src: Path, dest: Path) -> None:
    info = zipfile.ZipInfo(src.name, date_time=time.localtime(src.stat().st_mtime)[:6])
    info.create_system = 3                  # Unix, so the mode below is honoured
    info.external_attr = (0o100755 << 16)   # regular file, rwxr-xr-x
    info.compress_type = zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(dest, "w") as zf, open(src, "rb") as fh:
        zf.writestr(info, fh.read(), compresslevel=9)


def check(dest: Path, name: str) -> None:
    with zipfile.ZipFile(dest) as zf:
        entries = zf.infolist()
        if [e.filename for e in entries] != [name] or (entries[0].external_attr >> 16) & 0o111 != 0o111:
            raise SystemExit(f"::error title=Package::{dest.name} should hold just a runnable {name}, "
                             f"but holds {[(e.filename, oct(e.external_attr >> 16)) for e in entries]}")


if __name__ == "__main__":
    src, dest = Path(sys.argv[1]), Path(sys.argv[2])
    make_zip(src, dest)
    check(dest, src.name)
    print(f"{dest}: {src.name}, runnable, {dest.stat().st_size // 1024} KB")
