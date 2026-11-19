# MANAGED BY AI-HARNESS
param(
    [Parameter(Position=0)]
    [string]$Command = 'verify',

    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Args
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = $PSScriptRoot
$HarnessHome = Join-Path $HOME 'ai-harness'
$HarnessScript = Join-Path $HarnessHome 'scripts\harness.ps1'
$RepoUrl = 'https://github.com/kijm32-ops/ai-harness.git'

function Ensure-Git {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw 'Git is required but was not found in PATH.'
    }
}

function Ensure-Harness {
    Ensure-Git

    if (-not (Test-Path $HarnessHome)) {
        Write-Host "Harness not found. Cloning to $HarnessHome"
        git clone $RepoUrl $HarnessHome
        if ($LASTEXITCODE -ne 0) { throw 'git clone failed.' }
    }

    if (-not (Test-Path $HarnessScript)) {
        throw "Harness script not found: $HarnessScript"
    }
}

function Update-Harness {
    Ensure-Harness
    git -C $HarnessHome pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw 'git pull --ff-only failed.' }
}

switch ($Command.ToLowerInvariant()) {
    'setup' {
        Ensure-Harness
        Update-Harness
        if (Test-Path (Join-Path $ProjectRoot 'SESSION_STATE.md')) {
            & $HarnessScript upgrade $ProjectRoot
        } else {
            & $HarnessScript init $ProjectRoot
        }
        exit $LASTEXITCODE
    }
    'update' {
        Update-Harness
        exit 0
    }
    default {
        Ensure-Harness
        & $HarnessScript $Command $ProjectRoot @Args
        exit $LASTEXITCODE
    }
}
