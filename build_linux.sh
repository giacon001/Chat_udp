#!/usr/bin/env bash
set -euo pipefail

PYTHON_EXE="${1:-python3}"

"${PYTHON_EXE}" -m pip install --upgrade pip
"${PYTHON_EXE}" -m pip install -r requirements-build.txt

rm -rf build dist
"${PYTHON_EXE}" -m PyInstaller --noconfirm chat_p2p.spec

echo "Build concluido. Executavel: dist/chat_p2p"
