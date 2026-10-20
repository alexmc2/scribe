#!/usr/bin/env bash
# Starts Scribe. Works from any directory, and through a symlink (e.g. ~/.local/bin/scribe).
set -euo pipefail

here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
python="$here/.venv/bin/python"

if ! "$python" -c "import faster_whisper" >/dev/null 2>&1; then
  echo "Scribe's Python environment is missing or broken."
  echo "This usually happens after a system Python upgrade. Rebuild it with:"
  echo "  $here/install.sh"
  exit 1
fi

if [ ! -f "$here/scribe/web/dist/main.js" ]; then
  echo "Scribe's interface hasn't been built yet. Build it with:"
  echo "  $here/install.sh"
  exit 1
fi

PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}" exec "$python" -m scribe "$@"
