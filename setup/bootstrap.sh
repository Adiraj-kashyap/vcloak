#!/usr/bin/env bash
# V-cloak bootstrap (macOS / Linux)
#
#   bash setup/bootstrap.sh                       # asks for your name and email
#   bash setup/bootstrap.sh "Aditya Raj" "you@vitstudent.ac.in"
#
# Installs Python and Git if missing, creates the virtual environment, installs the
# Python packages, and sets your git identity for this folder. Safe to run twice.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
say() { printf '\n\033[36m>> %s\033[0m\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

NAME="${1:-}"; EMAIL="${2:-}"
say "V-cloak setup — folder: $ROOT"

# ── 1. Python ────────────────────────────────────────────────────────────────
PY=""
for c in python3 python; do if have "$c"; then PY="$c"; break; fi; done
if [ -z "$PY" ]; then
  say "Python not found — installing"
  if have brew; then brew install python@3.12
  elif have apt-get; then sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
  elif have dnf; then sudo dnf install -y python3 python3-pip
  else echo "Install Python 3.10+ from https://www.python.org/downloads/ then re-run." >&2; exit 1; fi
  PY=python3
fi
say "Found $($PY --version)"

# ── 2. Git ───────────────────────────────────────────────────────────────────
if ! have git; then
  say "Git not found — installing"
  if have brew; then brew install git
  elif have apt-get; then sudo apt-get install -y git
  elif have dnf; then sudo dnf install -y git
  else echo "Install Git from https://git-scm.com/downloads then re-run." >&2; exit 1; fi
fi
say "Found $(git --version)"

# ── 3. Virtual environment ───────────────────────────────────────────────────
if [ ! -d .venv ]; then say "Creating the virtual environment (.venv)"; "$PY" -m venv .venv
else say "Virtual environment already exists"; fi
VPY="$ROOT/.venv/bin/python"

say "Installing Python packages (a few minutes the first time)"
"$VPY" -m pip install --upgrade pip --quiet
"$VPY" -m pip install --quiet \
  numpy scipy cryptography argon2-cffi pytest ruff matplotlib pandas \
  fastapi uvicorn httpx websockets "psycopg[binary]"
# CuPy is deliberately NOT installed: it needs an NVIDIA GPU. The CUDA work runs on
# the free Colab/Kaggle runner instead — see ai/GPU_RUNNER.md.

# ── 4. Git repository and identity ───────────────────────────────────────────
[ -d .git ] || { say "Starting the git repository"; git init --quiet -b main; }
[ -n "$NAME" ]  || read -rp "Your name, for commit attribution (e.g. Aditya Raj): " NAME
[ -n "$EMAIL" ] || read -rp "Your email, for commit attribution: " EMAIL
[ -n "$NAME" ]  && git config user.name  "$NAME"
[ -n "$EMAIL" ] && git config user.email "$EMAIL"
say "Commits in this folder will be attributed to: $(git config user.name) <$(git config user.email)>"

# ── 5. Check ─────────────────────────────────────────────────────────────────
"$VPY" -c "import numpy, scipy, cryptography, fastapi; print('python packages OK')"
printf '\n\033[32m>> Setup finished.\033[0m\n'
cat <<'TXT'

Next:
  1. Open THIS folder in Claude Code.
  2. Type:  continue

Each teammate runs this script once on their own machine, with their own name,
so the commit history matches who actually did the work.
TXT
