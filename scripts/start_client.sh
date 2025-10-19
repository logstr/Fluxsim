#!/usr/bin/env bash
set -euo pipefail

mkdir -p /workspace

if [[ -z "$(ls -A /workspace 2>/dev/null || true)" ]]; then
  cat > /workspace/FluxLabStarter.ipynb <<'NB'
{
 "cells": [
  {"cell_type":"markdown","metadata":{},"source":["# FluxLab Starter\\nTest DNS & HTTP from the client container."]},
  {"cell_type":"code","metadata":{},"source":["!dig +short fluxynet.sim.local"],"execution_count":null,"outputs":[]},
  {"cell_type":"code","metadata":{},"source":["!curl -s http://172.60.0.80 | head -n 5"],"execution_count":null,"outputs":[]}
 ],
 "metadata":{"kernelspec":{"display_name":"Python 3","language":"python","name":"python3"},
 "language_info":{"name":"python","pygments_lexer":"ipython3"}},
 "nbformat":4,"nbformat_minor":5
}
NB
fi

echo "\\nJupyter Lab running on http://0.0.0.0:8888 (no token)."

jupyter lab \
  --no-browser --ip=0.0.0.0 --port=8888 \
  --ServerApp.token='' --ServerApp.password='' \
  --ServerApp.allow_origin='*' --ServerApp.root_dir=/workspace \
  --allow-root &

wait $!
