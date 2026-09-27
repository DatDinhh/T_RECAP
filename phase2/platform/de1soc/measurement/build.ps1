#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$MeasurementDirectory,
    [Parameter(Mandatory = $true)][string]$BuildDirectory,
    [Parameter(Mandatory = $true)][string]$QuartusRoot
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath $RepoRoot).Path
$measurement = (Resolve-Path -LiteralPath $MeasurementDirectory).Path
$build = [System.IO.Path]::GetFullPath($BuildDirectory)
$quartusBin = Join-Path $QuartusRoot 'bin64'
foreach ($tool in @('quartus_sh.exe', 'quartus_sta.exe')) {
    if (-not (Test-Path -LiteralPath (Join-Path $quartusBin $tool) -PathType Leaf)) {
        throw "Missing Quartus tool: $tool"
    }
}
if (Test-Path -LiteralPath $build) {
    if (@(Get-ChildItem -LiteralPath $build -Force).Count -ne 0) {
        throw "BuildDirectory must be new or empty to prevent stale results: $build"
    }
} else { [void][System.IO.Directory]::CreateDirectory($build) }
$started = [DateTime]::UtcNow.ToString('o')

function Invoke-Quartus([string]$Tool, [string[]]$Arguments, [string]$LogName) {
    & (Join-Path $quartusBin $Tool) @Arguments 2>&1 | Tee-Object -FilePath (Join-Path $build $LogName)
    if ($LASTEXITCODE -ne 0) { throw "$Tool failed with exit code $LASTEXITCODE; see $LogName" }
}

Invoke-Quartus 'quartus_sh.exe' @('-t', (Join-Path $measurement 'create_project.tcl'), $repo, $measurement, $build) 'create_project.log'
Push-Location -LiteralPath $build
try {
    Invoke-Quartus 'quartus_sh.exe' @('--flow', 'compile', 'trecap_measurement') 'compile.log'
    Invoke-Quartus 'quartus_sta.exe' @('-t', (Join-Path $measurement 'timing_gate.tcl'), $build) 'timing_gate.log'
} finally { Pop-Location }
$sof = Join-Path $build 'output_files\trecap_measurement.sof'
if (-not (Test-Path -LiteralPath $sof -PathType Leaf)) { throw "SOF was not created: $sof" }
if (-not (Test-Path -LiteralPath (Join-Path $build 'timing_gate\PASS.txt') -PathType Leaf)) {
    throw 'Timing gate did not create its PASS receipt.'
}
$receipt = [pscustomobject]@{
    ok = $true
    started_utc = $started
    completed_utc = [DateTime]::UtcNow.ToString('o')
    repo_root = $repo
    measurement_directory = $measurement
    build_directory = $build
    sof = $sof
    sof_sha256 = (Get-FileHash -LiteralPath $sof -Algorithm SHA256).Hash
    timing_corners_csv = Join-Path $build 'timing_gate\corners.csv'
}
$receipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $build 'build_receipt.json') -Encoding UTF8
$receipt | ConvertTo-Json
