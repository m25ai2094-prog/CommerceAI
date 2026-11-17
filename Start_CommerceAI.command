#!/bin/bash
# macOS launcher for CommerceAI
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.10 or newer is required. Install it from https://www.python.org/downloads/macos/ and try again."
  read -r -p "Press Return to close..."
  exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    print("Python 3.10 or newer is required. Current version:", sys.version.split()[0])
    raise SystemExit(1)
PY

python3 run.py --open
status=$?
if [ "$status" -ne 0 ]; then
  echo "CommerceAI could not start. Check the error above and README.md."
  read -r -p "Press Return to close..."
fi
exit "$status"
