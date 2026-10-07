$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$workspace = Split-Path -Parent $projectRoot
$toolRoot = $env:TALLNUM_MSYS_ROOT
if (-not $toolRoot) { $toolRoot = Join-Path $workspace '.tools\msys64' }
if (-not (Test-Path -LiteralPath $toolRoot)) { throw 'MSYS2 not found; set TALLNUM_MSYS_ROOT to an installation with UCRT64 GCC and PETSc' }
$toolRoot = (Resolve-Path -LiteralPath $toolRoot -ErrorAction Stop).Path
$sourceBin = Join-Path $toolRoot 'ucrt64\bin'
$target = Join-Path $projectRoot 'native'
$objdump = Join-Path $sourceBin 'objdump.exe'
if (-not (Test-Path -LiteralPath $objdump)) { throw 'MSYS2 objdump is missing' }
$queue = [System.Collections.Generic.Queue[string]]::new()
Get-ChildItem -LiteralPath $target -Filter '*.exe' | ForEach-Object { $queue.Enqueue($_.FullName) }
$visited = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
while ($queue.Count -gt 0) {
    $binary = $queue.Dequeue()
    if (-not $visited.Add($binary)) { continue }
    $lines = & $objdump -p $binary | Select-String 'DLL Name: ([^\s]+)'
    foreach ($line in $lines) {
        $name = $line.Matches[0].Groups[1].Value
        $source = Join-Path $sourceBin $name
        if (-not (Test-Path -LiteralPath $source)) { continue }
        $destination = Join-Path $target $name
        if (-not (Test-Path -LiteralPath $destination)) { Copy-Item -LiteralPath $source -Destination $destination }
        $queue.Enqueue($destination)
    }
}
Get-ChildItem -LiteralPath $target -Filter '*.dll' | Select-Object Name,Length
