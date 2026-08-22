#!/usr/bin/env bash
# Program Z planner - one-command setup + launch (macOS / Linux / Git Bash)
# Creates the conda env if needed, runs the full pipeline, starts the UI.
set -euo pipefail
cd "$(dirname "$0")"

command -v conda >/dev/null || { echo "conda not found - install Miniconda first"; exit 1; }

if ! conda env list | grep -q avathon; then
  echo "[1/4] creating conda env 'avathon'..."
  conda create -n avathon python=3.12 -y
else
  echo "[1/4] conda env 'avathon' exists"
fi

echo "[2/4] installing python deps..."
conda run -n avathon python -m pip install -q -r engine/requirements.txt

echo "[3/4] running pipeline: ingest -> forecast -> MPS -> scenario..."
conda run -n avathon python engine/run_pipeline.py --all

echo "[4/4] installing app deps + starting the UI on http://localhost:3000"
cd app
npm install
npm run dev
