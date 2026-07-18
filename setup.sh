#!/bin/bash
# chmod +x setup.sh

# Install additional system-level dependencies/packages
python3 -m pip install --upgrade pip

# Install Python dependencies (pyproject.toml/uv.lock is the single source of truth)
pip install uv
uv sync

# Install the Python extension for Visual Studio Code
code --install-extension ms-python.python --force

