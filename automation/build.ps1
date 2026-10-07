$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$toolRoot = $env:TALLNUM_MSYS_ROOT
if (-not $toolRoot) { $toolRoot = Join-Path $workspace '.tools\msys64' }
if (-not (Test-Path -LiteralPath $toolRoot)) { throw 'MSYS2 not found; set TALLNUM_MSYS_ROOT to an installation with UCRT64 GCC and PETSc' }
$toolRoot = (Resolve-Path -LiteralPath $toolRoot -ErrorAction Stop).Path
$compiler = Join-Path $toolRoot 'ucrt64/bin/g++.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'MSYS2 UCRT64 GCC is missing; install mingw-w64-ucrt-x86_64-gcc' }
$env:PATH = (Split-Path -Parent $compiler) + ';' + $env:PATH
$env:MSYSTEM = 'UCRT64'
$env:TALLNUM_BUILD_TEMP = Join-Path $workspace '.build-tmp'
New-Item -ItemType Directory -Force $env:TALLNUM_BUILD_TEMP | Out-Null
$env:TMPDIR = $env:TALLNUM_BUILD_TEMP
$env:TMP = $env:TALLNUM_BUILD_TEMP
$env:TEMP = $env:TALLNUM_BUILD_TEMP
$native = Join-Path $workspace 'desktop/native'
New-Item -ItemType Directory -Force $native | Out-Null
& $compiler -std=c++20 -O2 -static -Wno-deprecated-declarations (Join-Path $PSScriptRoot 'native_policy.cpp') -o (Join-Path $native 'tallnum_automation_clean.exe')
if ($LASTEXITCODE -ne 0) { throw 'Automation policy bridge compilation failed' }
& $compiler -std=c++20 -O2 -static -Wno-deprecated-declarations -DTALLNUM_POLICY_MAX_CAPACITY=6 (Join-Path $PSScriptRoot 'native_policy.cpp') -o (Join-Path $native 'tallnum_automation_six_clean.exe')
if ($LASTEXITCODE -ne 0) { throw 'Six-cell clean-exit bridge compilation failed' }
& $compiler -std=c++20 -O2 -static -Wno-deprecated-declarations (Join-Path $workspace 'tallnum_reachable.cpp') -o (Join-Path $native 'tallnum_reachable_clean.exe')
if ($LASTEXITCODE -ne 0) { throw 'Automation transition generator compilation failed' }
& $compiler -std=c++20 -O2 -static -Wno-deprecated-declarations (Join-Path $workspace 'aggressive-version/tallnum_vi.cpp') -o (Join-Path $native 'tallnum_vi_aggressive.exe')
if ($LASTEXITCODE -ne 0) { throw 'Aggressive value iteration compilation failed' }
$graphSource = (Join-Path $PSScriptRoot 'petsc_graph_eval.cpp').Replace('\','/')
$graphOutput = (Join-Path $native 'petsc_graph_eval.exe').Replace('\','/')
$graphCommand = "g++ -std=c++20 -O2 -Wno-deprecated-declarations -DPETSC_FUNCTION_NAME_CXX=__func__ -DPETSC_CXX_RESTRICT=__restrict__ '$graphSource' " + '$(pkg-config --cflags --libs petsc-dso)' + " -o '$graphOutput'"
& (Join-Path $toolRoot 'usr/bin/bash.exe') -lc ('export TMPDIR="$(cygpath -m "$TALLNUM_BUILD_TEMP")"; export TMP="$TMPDIR" TEMP="$TMPDIR"; ' + $graphCommand)
if ($LASTEXITCODE -ne 0) { throw 'PETSc fixed-policy graph compilation failed' }
