$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$workspace = Split-Path -Parent $projectRoot
$toolRoot = $env:TALLNUM_MSYS_ROOT
if (-not $toolRoot) { $toolRoot = Join-Path $workspace '.tools\msys64' }
if (-not (Test-Path -LiteralPath $toolRoot)) { throw 'MSYS2 not found; set TALLNUM_MSYS_ROOT to an installation with UCRT64 GCC and PETSc' }
$toolRoot = (Resolve-Path -LiteralPath $toolRoot -ErrorAction Stop).Path
$msys = Join-Path $toolRoot 'usr\bin\bash.exe'
if (-not (Test-Path -LiteralPath $msys)) { throw 'Set TALLNUM_MSYS_ROOT to an MSYS2 installation with UCRT64 GCC and PETSc' }
New-Item -ItemType Directory -Force (Join-Path $projectRoot 'native') | Out-Null
$env:TALLNUM_MSYS_ROOT = $toolRoot
$env:MSYSTEM = 'UCRT64'
$env:TALLNUM_BUILD_TEMP = Join-Path $workspace '.build-tmp'
New-Item -ItemType Directory -Force $env:TALLNUM_BUILD_TEMP | Out-Null
$env:TMPDIR = $env:TALLNUM_BUILD_TEMP
$env:TALLNUM_WORKSPACE = $workspace
$workspaceShell = $workspace.Replace('\','/').Replace("'", "'\''")
$buildCommand = "cd '$workspaceShell' && " + 'g++ -O3 -std=c++20 -Wno-deprecated-declarations tallnum_reachable.cpp -o desktop/native/tallnum_reachable_legacy.exe && g++ -O3 -std=c++20 -Wno-deprecated-declarations tallnum_vi.cpp -o desktop/native/tallnum_vi_legacy.exe && g++ -O3 -std=c++20 -Wno-deprecated-declarations -DPETSC_FUNCTION_NAME_CXX=__func__ -DPETSC_CXX_RESTRICT=__restrict__ tallnum_policy_eval.cpp $(pkg-config --cflags --libs petsc-dso) -o desktop/native/tallnum_policy_eval_legacy.exe'
& $msys -lc ('export TMPDIR="$(cygpath -m "$TALLNUM_BUILD_TEMP")"; export TMP="$TMPDIR" TEMP="$TMPDIR"; ' + $buildCommand)
if ($LASTEXITCODE -ne 0) { throw 'Native compile failed' }
& (Join-Path $workspace 'aggressive-version\build-native.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Aggressiveness core compile failed' }
Copy-Item -Path (Join-Path $workspace 'aggressive-version\bin\*.exe') -Destination (Join-Path $projectRoot 'native')
& (Join-Path $PSScriptRoot 'copy-native.ps1')
& (Join-Path $workspace 'automation/build.ps1')

& (Join-Path $workspace 'automation/build-pending.ps1')

# The current generator owns clean-exit and EDGE metadata.
& $msys -lc ("cd '$workspaceShell' && " + 'g++ -O3 -std=c++20 -Wno-deprecated-declarations tallnum_reachable.cpp -o desktop/native/tallnum_reachable.exe')
if ($LASTEXITCODE -ne 0) { throw 'Current transition generator compile failed' }
