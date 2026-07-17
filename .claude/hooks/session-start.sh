#!/bin/bash
set -euo pipefail

# Only relevant for Claude Code on the web / remote sessions
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Python deps — this repo is uv-managed (pyproject.toml/uv.lock), with
# requirements.txt kept in sync for setup.sh/CI parity.
if command -v uv >/dev/null 2>&1; then
  uv sync
else
  pip install -r requirements.txt
fi

# System deps: tabula-py (PDF table extraction) needs a Java runtime;
# admin/generate_sccm_graph.py needs graphviz.
if ! command -v java >/dev/null 2>&1 || ! command -v dot >/dev/null 2>&1; then
  if [ "$(id -u)" -eq 0 ]; then
    apt-get update -qq
    apt-get install -y -qq default-jre graphviz
  else
    sudo apt-get update -qq
    sudo apt-get install -y -qq default-jre graphviz
  fi
fi
