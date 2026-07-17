#!/bin/bash
# chmod +x setup.sh

# Install additional system-level dependencies/packages
python3 -m pip install --upgrade pip

# Install Python dependencies (pyproject.toml/uv.lock is the single source of truth)
pip install uv
uv sync

echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y graphviz
#- name: Install Graphviz
#  run: sudo apt-get update && sudo apt-get install -y graphviz
                                     
# Install the Python extension for Visual Studio Code
code --install-extension ms-python.python --force

