param(
    [string]$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$ModelSimBin = "",
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path -LiteralPath $Repo -ErrorAction Stop).Path

if ([string]::IsNullOrWhiteSpace($ModelSimBin)) {
    $VlogCommand = Get-Command "vlog.exe" -ErrorAction SilentlyContinue
    if ($null -eq $VlogCommand) {
        throw "ModelSim/Questa was not found on PATH. Pass -ModelSimBin <directory>."
    }
    $ModelSimBin = Split-Path -Parent $VlogCommand.Source
}
$ModelSimBin = (Resolve-Path -LiteralPath $ModelSimBin -ErrorAction Stop).Path

$PythonPrefix = @()
if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $PythonCommand = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($null -eq $PythonCommand) {
        $PythonCommand = Get-Command "py.exe" -ErrorAction SilentlyContinue
        if ($null -ne $PythonCommand) {
            $PythonPrefix = @("-3")
        }
    }
    if ($null -eq $PythonCommand) {
        throw "Python 3 was not found on PATH. Pass -PythonExe <path>."
    }
    $PythonExe = $PythonCommand.Source
}
$PythonExe = (Resolve-Path -LiteralPath $PythonExe -ErrorAction Stop).Path

$Vlib = Join-Path $ModelSimBin "vlib.exe"
$Vmap = Join-Path $ModelSimBin "vmap.exe"
$Vlog = Join-Path $ModelSimBin "vlog.exe"
$Vsim = Join-Path $ModelSimBin "vsim.exe"
$Filelist = Join-Path $Repo "sim\filelists\step12_ddr_ring_ownership.f"
$Testbench = Join-Path $Repo "sim\tb\tb_trecap_step12_ddr_ring_ownership.sv"
$Model = Join-Path $Repo "scripts\sim\check_step12_ddr_ring_model.py"
$RunDir = Join-Path $Repo "runs\step12-ddr-ring-ownership"
$WorkLib = Join-Path $RunDir "work"

foreach ($Path in @($Repo, $PythonExe, $Vlib, $Vmap, $Vlog, $Vsim,
                    $Filelist, $Testbench, $Model)) {
    if (!(Test-Path -LiteralPath $Path)) {
        throw "Missing required path: $Path"
    }
}

function Invoke-Native {
    param(
        [string]$Exe,
        [string[]]$Arguments,
        [string]$Log
    )

    Write-Host "CMD: $Exe $($Arguments -join ' ')"
    $SavedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Exe @Arguments 2>&1 | Tee-Object -FilePath $Log
        $ExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $SavedPreference
    }
    if ($ExitCode -ne 0) {
        throw "Command failed with exit code $ExitCode. See $Log"
    }
}

New-Item -ItemType Directory -Force $RunDir | Out-Null
if (Test-Path -LiteralPath $WorkLib) {
    $RunsRoot = (Resolve-Path -LiteralPath (Join-Path $Repo "runs")).Path
    $ResolvedWork = (Resolve-Path -LiteralPath $WorkLib).Path
    if (!$ResolvedWork.StartsWith($RunsRoot + [IO.Path]::DirectorySeparatorChar,
                                  [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean work library outside repository runs/: $ResolvedWork"
    }
    Remove-Item -LiteralPath $ResolvedWork -Recurse -Force
}

Push-Location $Repo
try {
    Invoke-Native -Exe $PythonExe -Arguments ($PythonPrefix + @($Model)) `
        -Log (Join-Path $RunDir "model.log")
    Invoke-Native -Exe $Vlib -Arguments @($WorkLib) -Log (Join-Path $RunDir "vlib.log")
    Invoke-Native -Exe $Vmap -Arguments @("work", $WorkLib) -Log (Join-Path $RunDir "vmap.log")
    Invoke-Native -Exe $Vlog `
        -Arguments @("-sv", "-suppress", "2892", "-work", "work", "-f", $Filelist) `
        -Log (Join-Path $RunDir "compile.log")
    Invoke-Native -Exe $Vsim `
        -Arguments @(
            "-c", "-lib", "work", "tb_trecap_step12_ddr_ring_ownership",
            "-do", "onerror {quit -code 1}; run -all; quit -code 0"
        ) `
        -Log (Join-Path $RunDir "simulate.log")
}
finally {
    Pop-Location
}

$ModelLog = Join-Path $RunDir "model.log"
$CompileLog = Join-Path $RunDir "compile.log"
$SimLog = Join-Path $RunDir "simulate.log"
if (!(Select-String -LiteralPath $ModelLog -SimpleMatch "STEP12_DDR_RING_MODEL_PASS" -Quiet)) {
    throw "Missing STEP12_DDR_RING_MODEL_PASS sentinel. See $ModelLog"
}
if (!(Select-String -LiteralPath $SimLog -SimpleMatch "STEP12_DDR_RING_OWNERSHIP_PASS" -Quiet)) {
    throw "Missing STEP12_DDR_RING_OWNERSHIP_PASS sentinel. See $SimLog"
}
if (Select-String -Path @($ModelLog, $CompileLog, $SimLog) `
        -Pattern "\*\* (Error|Fatal):|STEP12_DDR_RING_MODEL_FAIL|STEP12_DDR_RING_OWNERSHIP_FAIL" -Quiet) {
    throw "Step-12 log contains Error/Fatal/FAIL. See $RunDir"
}

Write-Host "STEP12_DDR_RING_OWNERSHIP_RUNNER_PASS"
