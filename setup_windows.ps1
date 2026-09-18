$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Add-KnownToolPath {
    param([string]$Path)
    if ((Test-Path $Path) -and (-not (($env:Path -split ';') -contains $Path))) {
        $env:Path = "$Path;$env:Path"
    }
}

Add-KnownToolPath "C:\Program Files\Git\cmd"
Add-KnownToolPath "C:\Program Files\GitHub CLI"

$missing = @()
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { $missing += "Git" }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { $missing += "GitHub CLI" }

$usePyLauncher = $false
if (Get-Command py -ErrorAction SilentlyContinue) {
    try {
        & py -3.11 --version | Out-Host
        if ($LASTEXITCODE -eq 0) { $usePyLauncher = $true }
    } catch {}
}

$usePython = $false
if (-not $usePyLauncher -and (Get-Command python -ErrorAction SilentlyContinue)) {
    try {
        & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
        if ($LASTEXITCODE -eq 0) { $usePython = $true }
    } catch {}
}

if (-not $usePyLauncher -and -not $usePython) { $missing += "Python 3.11+" }

if ($missing.Count -gt 0) {
    Write-Host "Missing prerequisites: $($missing -join ', ')" -ForegroundColor Yellow
    Write-Host "Install only the missing items, reopen PowerShell, then run this script again:"
    Write-Host "  winget install --id Git.Git -e"
    Write-Host "  winget install --id GitHub.cli -e"
    Write-Host "  winget install --id Python.Python.3.11 -e"
    exit 1
}

& gh auth status
if ($LASTEXITCODE -ne 0) {
    Write-Host "GitHub CLI login is required. Starting gh auth login..."
    & gh auth login
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if ($usePyLauncher) {
    & py -3.11 -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & py -3.11 install_ptis.py
    exit $LASTEXITCODE
}

& python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& python install_ptis.py
exit $LASTEXITCODE
