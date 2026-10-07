# Optional native worker for the pending-value experiments.
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$toolRoot = $env:TALLNUM_MSYS_ROOT
if (-not $toolRoot) { $toolRoot = Join-Path $workspace '.tools/msys64' }
$compiler = Join-Path $toolRoot 'ucrt64/bin/g++.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Set TALLNUM_MSYS_ROOT to MSYS2 with UCRT64 GCC installed' }
$env:PATH = (Split-Path -Parent $compiler) + ';' + $env:PATH
$scratch = Join-Path $workspace '.build-tmp'
New-Item -ItemType Directory -Force $scratch | Out-Null
$env:TMPDIR = $scratch
$env:TMP = $scratch
$env:TEMP = $scratch
$output = Join-Path $PSScriptRoot 'pending_value_allcells.exe'
& $compiler -std=c++20 -O2 -static -Wno-deprecated-declarations (Join-Path $PSScriptRoot 'pending_value.cpp') -o $output
if ($LASTEXITCODE -ne 0) { throw 'Pending-value worker compilation failed' }
Copy-Item -LiteralPath $output -Destination (Join-Path $PSScriptRoot 'pending_value_all5.exe')
Copy-Item -LiteralPath $output -Destination (Join-Path $PSScriptRoot 'pending_value_experiment.exe')
