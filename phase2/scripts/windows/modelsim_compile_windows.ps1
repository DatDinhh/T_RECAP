param(
    [string]$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$ModelSimExe = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ModelSimExe)) {
    $VlogCommand = Get-Command "vlog.exe" -ErrorAction SilentlyContinue
    if ($null -eq $VlogCommand) {
        throw "ModelSim/Questa was not found on PATH. Pass -ModelSimExe <path>."
    }
    $ModelSimBin = Split-Path -Parent $VlogCommand.Source
    $ModelSimExe = Join-Path $ModelSimBin "modelsim.exe"
    if (!(Test-Path -LiteralPath $ModelSimExe)) {
        $ModelSimExe = Join-Path $ModelSimBin "vsim.exe"
    }
}
$ModelSimExe = (Resolve-Path -LiteralPath $ModelSimExe -ErrorAction Stop).Path
$ModelSimBin = Split-Path -Parent $ModelSimExe
$Vlib = Join-Path $ModelSimBin "vlib.exe"
$Vmap = Join-Path $ModelSimBin "vmap.exe"
$Vlog = Join-Path $ModelSimBin "vlog.exe"
$Vsim = Join-Path $ModelSimBin "vsim.exe"

foreach ($p in @($Repo, $ModelSimExe, $Vlib, $Vmap, $Vlog, $Vsim)) {
    if (!(Test-Path $p)) { throw "Missing path: $p" }
}

$env:Path = "$ModelSimBin;$env:Path"
Set-Location $Repo

function Run-Native {
    param([string]$Exe, [string[]]$Args, [string]$Log)
    Write-Host ""
    Write-Host "CMD: $Exe $($Args -join ' ')"
    & $Exe @Args 2>&1 | Tee-Object -FilePath $Log
    if ($LASTEXITCODE -ne 0) { throw "FAILED: $Exe returned exit code $LASTEXITCODE. See log: $Log" }
}

function Invoke-ModelSimCompile {
    param([string]$Name, [string]$Filelist)
    $RunDir = Join-Path $Repo "runs\$Name"
    $WorkLib = Join-Path $RunDir "work"
    New-Item -ItemType Directory -Force $RunDir | Out-Null
    Remove-Item -Recurse -Force $WorkLib -ErrorAction SilentlyContinue
    if (!(Test-Path (Join-Path $Repo $Filelist))) { throw "Missing filelist: $Filelist" }
    Push-Location $Repo
    try {
        Write-Host ""
        Write-Host "============================================================"
        Write-Host "Compiling: $Name"
        Write-Host "Filelist : $Filelist"
        Write-Host "Run dir  : $RunDir"
        Write-Host "============================================================"
        Run-Native -Exe $Vlib -Args @($WorkLib) -Log (Join-Path $RunDir "vlib.log")
        Run-Native -Exe $Vmap -Args @("work", $WorkLib) -Log (Join-Path $RunDir "vmap.log")
        Run-Native -Exe $Vlog -Args @("-sv", "-suppress", "2892", "-work", "work", "-f", $Filelist) -Log (Join-Path $RunDir "compile.log")
        Write-Host "PASS: $Name"
    }
    finally { Pop-Location }
}

Invoke-ModelSimCompile -Name "compile-core"       -Filelist "filelists\rtl_core_plus_fft.f"
Invoke-ModelSimCompile -Name "compile-telemetry"  -Filelist "filelists\rtl_telemetry.f"
Invoke-ModelSimCompile -Name "compile-core-telemetry" -Filelist "filelists\rtl_core_telemetry.f"
Invoke-ModelSimCompile -Name "compile-hps-bridge" -Filelist "filelists\rtl_hps_bridge.f"

$PDWrapper = Join-Path $Repo "rtl\platform\de1soc\platform_designer_wrapper.sv"
$PDSystemV = Join-Path $Repo "platform\de1soc\qsys\system\synthesis\system.v"
$PDSystemSv = Join-Path $Repo "platform\de1soc\qsys\system\synthesis\system.sv"
if ((Test-Path $PDWrapper) -and ((Test-Path $PDSystemV) -or (Test-Path $PDSystemSv))) {
    Invoke-ModelSimCompile -Name "compile-de1soc-full" -Filelist "filelists\rtl_de1soc_full.f"
} else {
    Write-Warning "Skipping compile-de1soc-full until the hand-written wrapper and Quartus-generated system HDL are both present."
}

Write-Host ""
Write-Host "ModelSim compile sequence finished. Logs are under $Repo\runs"
