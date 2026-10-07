$ErrorActionPreference = 'Stop'
$sourceRoot = $PSScriptRoot
$workspace = Split-Path -Parent $sourceRoot
$toolRoot = $env:TALLNUM_MSYS_ROOT
if (-not $toolRoot) { $toolRoot = Join-Path (Split-Path -Parent $sourceRoot) '.tools\msys64' }
$msys = Join-Path $toolRoot 'usr\bin\bash.exe'
if (-not (Test-Path -LiteralPath $msys)) { throw 'Set TALLNUM_MSYS_ROOT to an MSYS2 installation with UCRT64 and PETSc' }
New-Item -ItemType Directory -Force (Join-Path $sourceRoot 'bin') | Out-Null
$env:MSYSTEM = 'UCRT64'
$env:TALLNUM_BUILD_TEMP = Join-Path $workspace '.build-tmp'
New-Item -ItemType Directory -Force $env:TALLNUM_BUILD_TEMP | Out-Null
$env:TMPDIR = $env:TALLNUM_BUILD_TEMP
$env:TALLNUM_RISK_SOURCE = $sourceRoot
$sourceShell = $sourceRoot.Replace('\','/').Replace("'", "'\''")
$buildCommand = "cd '$sourceShell' && " + 'g++ -O3 -std=c++20 -Wno-deprecated-declarations tallnum_reachable.cpp -o bin/tallnum_reachable.exe && g++ -O3 -std=c++20 -Wno-deprecated-declarations tallnum_vi.cpp -o bin/tallnum_vi.exe && g++ -O3 -std=c++20 -Wno-deprecated-declarations -DPETSC_FUNCTION_NAME_CXX=__func__ -DPETSC_CXX_RESTRICT=__restrict__ tallnum_policy_eval.cpp $(pkg-config --cflags --libs petsc-dso) -o bin/tallnum_policy_eval.exe'
& $msys -lc ('export TMPDIR="$(cygpath -m "$TALLNUM_BUILD_TEMP")"; export TMP="$TMPDIR" TEMP="$TMPDIR"; ' + $buildCommand)
if ($LASTEXITCODE -ne 0) { throw 'Native compile failed' }
$dllNames = @('libgcc_s_seh-1.dll','libgfortran-5.dll','libgomp-1.dll','libhwloc-15.dll','libltdl-7.dll','libopenblas.dll','libpetsc-dso.dll','libquadmath-0.dll','libstdc++-6.dll','libwinpthread-1.dll')
foreach ($dll in $dllNames) { Copy-Item -LiteralPath (Join-Path $toolRoot "ucrt64\bin\$dll") -Destination (Join-Path $sourceRoot 'bin') }
