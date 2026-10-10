# V-cloak bootstrap (Windows / PowerShell)
#
#   Right-click this file -> "Run with PowerShell",
#   or in a terminal inside the vcloak folder:   powershell -ExecutionPolicy Bypass -File setup\bootstrap.ps1
#
# It installs Python and Git if they are missing, creates the virtual environment,
# installs the Python packages, and sets your git identity for this folder.
# It installs nothing globally except Python and Git, and it is safe to run twice.

param(
  [string]$Name  = "",     # e.g. -Name "Aditya Raj"
  [string]$Email = ""      # e.g. -Email "you@vitstudent.ac.in"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Say($msg, $colour = "Cyan") { Write-Host "`n>> $msg" -ForegroundColor $colour }
function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

Say "V-cloak setup — folder: $root"

# ── 1. Python ────────────────────────────────────────────────────────────────
$py = $null
foreach ($c in @("python", "python3", "py")) { if (Have $c) { $py = $c; break } }
if (-not $py) {
  Say "Python not found. Installing it with winget..." "Yellow"
  if (-not (Have "winget")) {
    Write-Host "winget is unavailable. Install Python 3.12 from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this script again." -ForegroundColor Red
    exit 1
  }
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  Write-Host "Python installed. CLOSE this window, open a new one, and run the script again." -ForegroundColor Yellow
  exit 0
}
$pyv = & $py --version
Say "Found $pyv"

# ── 2. Git ───────────────────────────────────────────────────────────────────
if (-not (Have "git")) {
  Say "Git not found. Installing it with winget..." "Yellow"
  if (-not (Have "winget")) {
    Write-Host "winget is unavailable. Install Git from https://git-scm.com/download/win, then run this script again." -ForegroundColor Red
    exit 1
  }
  winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements
  Write-Host "Git installed. CLOSE this window, open a new one, and run the script again." -ForegroundColor Yellow
  exit 0
}
Say ("Found " + (git --version))

# ── 3. Virtual environment ───────────────────────────────────────────────────
if (-not (Test-Path ".venv")) { Say "Creating the virtual environment (.venv)"; & $py -m venv .venv }
else { Say "Virtual environment already exists" }
$vpy = Join-Path $root ".venv\Scripts\python.exe"

Say "Installing Python packages (a few minutes the first time)"
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install --quiet `
    numpy scipy cryptography argon2-cffi pytest ruff matplotlib pandas `
    fastapi uvicorn httpx websockets "psycopg[binary]"
# CuPy is deliberately NOT installed: it needs an NVIDIA GPU. The CUDA work runs on
# the free Colab/Kaggle runner instead — see ai/GPU_RUNNER.md.

# ── 4. Git repository and identity ───────────────────────────────────────────
if (-not (Test-Path ".git")) { Say "Starting the git repository"; git init --quiet -b main }

if (-not $Name)  { $Name  = Read-Host "Your name, for commit attribution (e.g. Aditya Raj)" }
if (-not $Email) { $Email = Read-Host "Your email, for commit attribution" }
if ($Name)  { git config user.name  "$Name" }
if ($Email) { git config user.email "$Email" }
Say ("Commits in this folder will be attributed to: " + (git config user.name) + " <" + (git config user.email) + ">")

# ── 5. Check ─────────────────────────────────────────────────────────────────
& $vpy -c "import numpy, scipy, cryptography, fastapi; print('python packages OK')"
Say "Setup finished." "Green"
Write-Host @"

Next:
  1. Open THIS folder in Claude Code.
  2. Type:  continue

Each teammate runs this script once on their own machine, with their own name,
so the commit history matches who actually did the work.
"@ -ForegroundColor Green
