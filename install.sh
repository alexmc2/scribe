#!/usr/bin/env bash
# Installs Scribe for the current user:
#   1. checks the computer has what Scribe needs, and says what to install if not
#   2. builds Scribe's Python environment in .venv
#   3. compiles the interface (TypeScript in frontend/) into scribe/web/dist
#   4. adds the `scribe` command (~/.local/bin/scribe)
#   5. downloads the speech model, so the first start is quick
# Safe to run again, e.g. after a system upgrade changes Python.
# Set SKIP_MODEL=1 to skip the model download.
set -euo pipefail

here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
python="${PYTHON:-python3}"
bin="$HOME/.local/bin"

step() { printf '\n\033[1m%s\033[0m\n' "$*"; }

step "Checking this computer"
problems=()
if ! command -v "$python" >/dev/null; then
  problems+=("Python 3 isn't installed:  sudo apt install python3 python3-venv")
elif ! "$python" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
  problems+=("Scribe needs Python 3.10 or newer; this is $("$python" --version).")
elif ! "$python" -c 'import ensurepip, venv' 2>/dev/null; then
  problems+=("Python can't create environments:  sudo apt install python3-venv")
fi
command -v parec >/dev/null || problems+=("The 'parec' recorder is missing:  sudo apt install pulseaudio-utils")
if ! command -v npm >/dev/null || ! node -e 'const [a, b] = process.versions.node.split(".").map(Number); process.exit(a > 16 || (a === 16 && b >= 20) ? 0 : 1)' 2>/dev/null; then
  problems+=("Node.js 18 or newer is needed to build the interface:  sudo apt install nodejs npm")
fi
if ((${#problems[@]})); then
  echo "Install these first, then run ./install.sh again:"
  printf '  - %s\n' "${problems[@]}"
  exit 1
fi
echo "Python: $("$python" --version), Node.js: $(node --version)"

model="large-v3-turbo"
if command -v nvidia-smi >/dev/null && gpu="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)" && [ -n "$gpu" ]; then
  echo "GPU: $gpu"
else
  model="small.en"
  echo "No working NVIDIA driver found, so Scribe will run on the CPU: slower, with a smaller model."
  echo "To use the GPU: install the NVIDIA driver (Driver Manager), reboot, and run ./install.sh again."
fi

step "Installing Python packages (about 2.5 GB; this takes a few minutes)"
"$python" -m venv --clear "$here/.venv"
"$here/.venv/bin/pip" install --quiet --upgrade pip
"$here/.venv/bin/pip" install --quiet -r "$here/requirements.txt"

step "Building the interface"
(cd "$here/frontend" && npm ci --silent --no-audit --no-fund && npm run build --silent)
echo "Built scribe/web/dist"

step "Adding the scribe command"
mkdir -p "$bin"
if [ -e "$bin/scribe" ] && [ "$(readlink -f "$bin/scribe")" != "$here/scribe.sh" ]; then
  echo "Left $bin/scribe alone: something else is already called that."
  echo "Start Scribe with: $here/scribe.sh"
else
  ln -sfn "$here/scribe.sh" "$bin/scribe"
  echo "Added $bin/scribe"
  case ":$PATH:" in
    *":$bin:"*) ;;
    *) echo "Open a new terminal (or log out and back in) so the 'scribe' command is found." ;;
  esac
fi

step "Downloading the speech model ($model; only needed once)"
if [ "${SKIP_MODEL:-0}" = 1 ]; then
  echo "Skipped. Scribe downloads it the first time it starts."
else
  "$here/.venv/bin/python" -c "from faster_whisper.utils import download_model; download_model('$model')" >/dev/null
  echo "Done."
fi

step "Scribe is installed"
echo "Type 'scribe' in a terminal to start. 'scribe --help' lists the options."
