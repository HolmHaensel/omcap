#!/bin/sh
# Double-click to start E-M1 Capture on macOS (opens the browser by itself).
# Remove --allow-write below for a read-only start.
cd "$(dirname "$0")" || exit 1
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
"$PY" -B -m omcap.server --allow-write
status=$?
if [ $status -ne 0 ]; then
  echo
  echo "E-M1 Capture could not start (see above). Installation: README.md"
  read -r -p "Press Enter to close this window." _
fi
