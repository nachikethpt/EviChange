#!/bin/bash
# Claude Code cloud sessions: install the Python dependencies so pytest runs from the repo root.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"
# --break-system-packages: the container's Python is Debian-managed (PEP 668); the container is throwaway
python3 -m pip install --quiet --disable-pip-version-check --root-user-action=ignore --break-system-packages \
  -r requirements.txt -r requirements-dev.txt
