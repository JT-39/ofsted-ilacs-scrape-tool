#!/bin/bash
set -euo pipefail

# Only relevant for Claude Code on the web / remote sessions
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Python deps - this repo is uv-managed; pyproject.toml/uv.lock is the single source of truth
if ! command -v uv >/dev/null 2>&1; then
  pip install uv
fi
uv sync

# System deps: tabula-py (PDF table extraction) needs a Java runtime.
if ! command -v java >/dev/null 2>&1; then
  if [ "$(id -u)" -eq 0 ]; then
    apt-get update -qq
    apt-get install -y -qq default-jre
  else
    sudo apt-get update -qq
    sudo apt-get install -y -qq default-jre
  fi
fi
