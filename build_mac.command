#!/bin/bash
# Builds dist/ZhiaLianQuestBrowser on a Mac. Needs Python 3.10-3.13 from python.org.
# Double-click this file in Finder, or run it in Terminal. Options go to build.py,
# for example: ./build_mac.command --onedir
cd "$(dirname "$0")" || exit 1

fail() {
  echo
  echo "The build stopped with an error. The messages above say what went wrong."
  read -r -p "Press Enter to close this window. " _
  exit 1
}

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 isn't installed. Get it from https://www.python.org/downloads/macos/ and run this again."
  fail
fi

if [ ! -x .venv/bin/python ]; then
  echo "Creating a virtual environment..."
  python3 -m venv .venv || fail
fi
# shellcheck disable=SC1091
source .venv/bin/activate || fail

echo "Installing build tools..."
python -m pip install --quiet --upgrade pip || fail
python -m pip install --quiet -r requirements.txt -r requirements-build.txt || fail

python build.py "$@" || fail

echo
echo "Done. Your app is dist/ZhiaLianQuestBrowser. Double-click it to start."
read -r -p "Press Enter to close this window. " _
