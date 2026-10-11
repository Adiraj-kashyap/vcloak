# M08 S4 - Nsight Compute divergence profile (Windows with an NVIDIA GPU). All the logic is in bench/run_ncu.py.
# Usage: pwsh bench/run_ncu.ps1 [--seed 8] [--log2n 16] [--out runs]
# ncu needs an elevated prompt, or "Manage GPU Performance Counters > Allow access to all users" in the
# NVIDIA Control Panel (Desktop > Enable Developer Settings); otherwise it reports ERR_NVGPUCTRPERM.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$py = if ($env:PYTHON) { $env:PYTHON } else { "python" }
& $py bench/run_ncu.py @args
exit $LASTEXITCODE
