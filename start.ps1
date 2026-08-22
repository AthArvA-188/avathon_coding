# Program Z planner - one-command setup + launch (Windows / PowerShell)
# Creates the conda env if needed, runs the full pipeline, starts the UI.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
  Write-Error "conda not found on PATH - install Miniconda first"
}

$envs = conda env list
if ($envs -notmatch "avathon") {
  Write-Host "[1/4] creating conda env 'avathon'..."
  conda create -n avathon python=3.12 -y
} else {
  Write-Host "[1/4] conda env 'avathon' exists"
}

Write-Host "[2/4] installing python deps..."
conda run -n avathon python -m pip install -q -r engine/requirements.txt

Write-Host "[3/4] running pipeline: ingest -> forecast -> MPS -> scenario..."
conda run -n avathon python engine/run_pipeline.py --all

Write-Host "[4/4] installing app deps + starting the UI on http://localhost:3000"
Set-Location app
npm install
npm run dev
