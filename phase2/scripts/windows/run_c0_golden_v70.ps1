param(
    [string]$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$ModelSimExe = "",
    [string]$PythonExe = "python",
    [string]$Vector = "near_threshold_multitone_Ns1024_thr64"
)

$ErrorActionPreference = "Stop"
$PreviousDontWriteBytecode = $env:PYTHONDONTWRITEBYTECODE
$PreviousPythonHashSeed = $env:PYTHONHASHSEED
$PreviousPythonUtf8 = $env:PYTHONUTF8

$Repo = (Resolve-Path -LiteralPath $Repo -ErrorAction Stop).Path
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
$Tool = Join-Path $Repo "scripts\sim\trecap_artifact_scoreboard.py"
$RunnerClosureScript = Join-Path $Repo "scripts\sim\check_c0_native_runner_closure.py"
$CoreFilelist = Join-Path $Repo "filelists\rtl_core_plus_fft.f"
$RegressionFilelist = Join-Path $Repo "sim\filelists\c0_v67_regression.f"
$GoldenFilelist = Join-Path $Repo "sim\filelists\c0_golden.f"
$DelayFilelist = Join-Path $Repo "sim\filelists\c0_delay_history.f"
$Mag2Filelist = Join-Path $Repo "sim\filelists\c0_mag2_width.f"
$RunRelative = "runs/c0-artifact-scoreboard-v70b"
$CaptureRelative = "$RunRelative/capture"
$RunDir = Join-Path $Repo "runs\c0-artifact-scoreboard-v70b"
$GeneratedDir = Join-Path $RunDir "generated"
$CaptureDir = Join-Path $RunDir "capture"
$WorkLib = Join-Path $RunDir "work"
$ExpectationPackage = Join-Path $GeneratedDir "trecap_artifact_expectations_pkg.sv"
$ExpectationManifest = Join-Path $GeneratedDir "expectations.json"
$SupportedVector = "near_threshold_multitone_Ns1024_thr64"

if ($Vector -ne $SupportedVector) {
    throw "Unsupported v70b vector '$Vector'. Expected '$SupportedVector'."
}

foreach ($Path in @(
    $Repo,
    $ModelSimExe,
    $Vlib,
    $Vmap,
    $Vlog,
    $Vsim,
    $Tool,
    $RunnerClosureScript,
    $CoreFilelist,
    $RegressionFilelist,
    $GoldenFilelist,
    $DelayFilelist,
    $Mag2Filelist
)) {
    if (!(Test-Path $Path)) {
        throw "Missing required path: $Path"
    }
}

$PythonCommand = Get-Command $PythonExe -ErrorAction Stop
$PythonPath = $PythonCommand.Source

New-Item -ItemType Directory -Force $RunDir | Out-Null
foreach ($Path in @($GeneratedDir, $CaptureDir, $WorkLib)) {
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
    }
    if (Test-Path -LiteralPath $Path) {
        throw "Failed to clean stale run path: $Path"
    }
}
New-Item -ItemType Directory -Force $GeneratedDir | Out-Null
New-Item -ItemType Directory -Force $CaptureDir | Out-Null

function Invoke-Native {
    param(
        [string]$Exe,
        [string[]]$Arguments,
        [string]$Log
    )

    Write-Host "CMD: $Exe $($Arguments -join ' ')"
    $SavedErrorActionPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 5.1 wraps native stderr as non-terminating error
        # records. Capture it in the log and judge the command by its exit code.
        $ErrorActionPreference = "Continue"
        & $Exe @Arguments 2>&1 | Tee-Object -FilePath $Log
        $ExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $SavedErrorActionPreference
    }
    if ($ExitCode -ne 0) {
        throw "Command failed with exit code $ExitCode. See $Log"
    }
}

function Require-Sentinel {
    param(
        [string]$Log,
        [string]$Sentinel
    )

    if (!(Select-String -Path $Log -SimpleMatch $Sentinel -Quiet)) {
        throw "Missing PASS sentinel '$Sentinel'. See $Log"
    }
}

function Reject-Simulation-Diagnostics {
    param([string]$Log)

    if (Select-String -Path $Log `
            -Pattern "\*\* (Error|Fatal):|C0_.*_MISMATCH" -Quiet) {
        throw "Simulation log contains Error/Fatal/MISMATCH. See $Log"
    }
}

function Invoke-Regression {
    param(
        [string]$Top,
        [string[]]$Sentinels,
        [string]$LogName,
        [string[]]$ExtraArguments = @()
    )

    $SimLog = Join-Path $RunDir $LogName
    $Arguments = @("-c", "-lib", "work", $Top)
    $Arguments += $ExtraArguments
    $Arguments += @(
        "-do",
        "onerror {quit -code 1}; run -all; quit -code 0"
    )
    Invoke-Native -Exe $Vsim -Arguments $Arguments -Log $SimLog
    foreach ($Sentinel in $Sentinels) {
        Require-Sentinel -Log $SimLog -Sentinel $Sentinel
    }
    Reject-Simulation-Diagnostics -Log $SimLog
}

function Invoke-ModelCheck {
    param(
        [string]$Script,
        [string]$Sentinel,
        [string]$LogName
    )

    $Log = Join-Path $RunDir $LogName
    Invoke-Native -Exe $PythonPath -Arguments @($Script) -Log $Log
    Require-Sentinel -Log $Log -Sentinel $Sentinel
}

$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONHASHSEED = "0"
$env:PYTHONUTF8 = "1"
Push-Location $Repo
try {
    Invoke-ModelCheck `
        -Script "scripts\sim\check_c0_native_runner_closure.py" `
        -Sentinel "C0_NATIVE_RUNNER_CLOSURE_PASS" `
        -LogName "native-runner-closure.log"
    Invoke-ModelCheck `
        -Script "scripts\sim\check_c0_flow_control_model.py" `
        -Sentinel "C0_FLOW_CONTROL_MODEL_PASS" `
        -LogName "model-flow-control.log"
    Invoke-ModelCheck `
        -Script "scripts\sim\check_c0_active_tail_model.py" `
        -Sentinel "ACTIVE_TAIL_MODEL_PASS" `
        -LogName "model-active-tail.log"
    Invoke-ModelCheck `
        -Script "scripts\sim\check_c0_exact_completion_model.py" `
        -Sentinel "C0_EXACT_COMPLETION_MODEL_PASS" `
        -LogName "model-exact-completion.log"
    Invoke-ModelCheck `
        -Script "scripts\sim\check_c0_delay_history_model.py" `
        -Sentinel "C0_DELAY_HISTORY_MODEL_PASS" `
        -LogName "model-delay-history.log"

    $EmbeddedIntegrityLog = Join-Path $RunDir "reference-embedded-integrity.log"
    Invoke-Native -Exe $PythonPath `
        -Arguments @(
            "sw\reference_model\tools\artifact_check.py",
            "--artifacts", "sw\reference_model\artifacts",
            "--schemas", "sw\reference_model\spec\schemas",
            "--output-subdir", "golden",
            "--source-root", "sw\reference_model"
        ) `
        -Log $EmbeddedIntegrityLog
    Require-Sentinel -Log $EmbeddedIntegrityLog -Sentinel "artifact_check: OK"
    Write-Host "REFERENCE_EMBEDDED_DAG_PASS"

    $RootIntegrityLog = Join-Path $RunDir "reference-root-import-integrity.log"
    Invoke-Native -Exe $PythonPath `
        -Arguments @(
            "sw\reference_model\tools\artifact_check.py",
            "--artifacts", "artifacts",
            "--schemas", "spec\schemas",
            "--output-subdir", "reference_outputs",
            "--source-root", "sw\reference_model",
            "--architecture-root", ".",
            "--import-manifest", "artifacts\manifests\reference_import_manifest.json"
        ) `
        -Log $RootIntegrityLog
    Require-Sentinel -Log $RootIntegrityLog -Sentinel "artifact_check: OK"
    Write-Host "REFERENCE_ROOT_IMPORT_DAG_PASS"

    $SelfTestLog = Join-Path $RunDir "artifact-tool-selftest.log"
    Invoke-Native -Exe $PythonPath `
        -Arguments @(
            "scripts\sim\trecap_artifact_scoreboard.py",
            "self-test",
            "--repo", ".",
            "--vector", $Vector
        ) `
        -Log $SelfTestLog
    Require-Sentinel -Log $SelfTestLog -Sentinel "C0_ARTIFACT_TOOL_SELFTEST_PASS"

    $PreflightLog = Join-Path $RunDir "artifact-preflight.log"
    Invoke-Native -Exe $PythonPath `
        -Arguments @(
            "scripts\sim\trecap_artifact_scoreboard.py",
            "prepare",
            "--repo", ".",
            "--vector", $Vector,
            "--header", $ExpectationPackage,
            "--manifest", $ExpectationManifest
        ) `
        -Log $PreflightLog
    Require-Sentinel -Log $PreflightLog -Sentinel "C0_ARTIFACT_PREFLIGHT_PASS"

    Invoke-Native -Exe $Vlib `
        -Arguments @($WorkLib) `
        -Log (Join-Path $RunDir "vlib.log")
    Invoke-Native -Exe $Vmap `
        -Arguments @("work", $WorkLib) `
        -Log (Join-Path $RunDir "vmap.log")
    Invoke-Native -Exe $Vlog `
        -Arguments @("-version") `
        -Log (Join-Path $RunDir "tool-version.log")
    Invoke-Native -Exe $Vlog `
        -Arguments @(
            "-sv",
            "-suppress", "2892",
            "-work", "work",
            "-f", "filelists\rtl_core_plus_fft.f",
            "-f", "sim\filelists\c0_mag2_width.f",
            $ExpectationPackage,
            "-f", "sim\filelists\c0_v67_regression.f",
            "-f", "sim\filelists\c0_golden.f",
            "-f", "sim\filelists\c0_delay_history.f"
        ) `
        -Log (Join-Path $RunDir "compile.log")

    # Bind the compiled package to the exact source snapshot immediately before simulation.
    $SnapshotLog = Join-Path $RunDir "artifact-snapshot.log"
    Invoke-Native -Exe $PythonPath `
        -Arguments @(
            "scripts\sim\trecap_artifact_scoreboard.py",
            "verify",
            "--repo", ".",
            "--vector", $Vector,
            "--expectation-package", $ExpectationPackage,
            "--expectation-manifest", $ExpectationManifest
        ) `
        -Log $SnapshotLog
    Require-Sentinel -Log $SnapshotLog -Sentinel "C0_ARTIFACT_SNAPSHOT_PASS"

    Invoke-Regression `
        -Top "tb_trecap_mag2_width" `
        -Sentinels @("C0_MAG2_WIDTH_PASS") `
        -LogName "simulate-mag2-width.log"
    Invoke-Regression `
        -Top "tb_trecap_delay_history" `
        -Sentinels @("C0_DELAY_HISTORY_PASS") `
        -LogName "simulate-delay-history.log"
    Invoke-Regression `
        -Top "tb_trecap_c0_flow_control" `
        -Sentinels @("C0_FLOW_CONTROL_PASS") `
        -LogName "simulate-flow-control.log"
    Invoke-Regression `
        -Top "tb_trecap_wola_tail_drain" `
        -Sentinels @("WOLA_TAIL_DRAIN_PASS") `
        -LogName "simulate-wola-tail-drain.log"
    Invoke-Regression `
        -Top "tb_trecap_c0_active_tail" `
        -Sentinels @("C0_EXACT_COMPLETION_PASS", "C0_ACTIVE_TAIL_PASS") `
        -LogName "simulate-exact-completion.log"
    Invoke-Regression `
        -Top "tb_trecap_c0_golden" `
        -Sentinels @("C0_ARTIFACT_RTL_PASS") `
        -LogName "simulate-artifact-scoreboard.log" `
        -ExtraArguments @("+C0_CAPTURE_DIR=$CaptureRelative")

    $PostcheckLog = Join-Path $RunDir "artifact-postcheck.log"
    Invoke-Native -Exe $PythonPath `
        -Arguments @(
            "scripts\sim\trecap_artifact_scoreboard.py",
            "compare",
            "--repo", ".",
            "--vector", $Vector,
            "--capture-dir", $CaptureDir,
            "--expectation-package", $ExpectationPackage,
            "--expectation-manifest", $ExpectationManifest
        ) `
        -Log $PostcheckLog
    Require-Sentinel -Log $PostcheckLog -Sentinel "C0_ARTIFACT_POSTCHECK_PASS"

    # Recheck the source snapshot after every native simulation and postcheck.
    $FinalSnapshotLog = Join-Path $RunDir "artifact-final-snapshot.log"
    Invoke-Native -Exe $PythonPath `
        -Arguments @(
            "scripts\sim\trecap_artifact_scoreboard.py",
            "verify",
            "--repo", ".",
            "--vector", $Vector,
            "--expectation-package", $ExpectationPackage,
            "--expectation-manifest", $ExpectationManifest
        ) `
        -Log $FinalSnapshotLog
    Require-Sentinel -Log $FinalSnapshotLog -Sentinel "C0_ARTIFACT_SNAPSHOT_PASS"
}
finally {
    Pop-Location
    $env:PYTHONDONTWRITEBYTECODE = $PreviousDontWriteBytecode
    $env:PYTHONHASHSEED = $PreviousPythonHashSeed
    $env:PYTHONUTF8 = $PreviousPythonUtf8
}

Write-Host ""
Write-Host "C0_GOLDEN_SUITE_PASS vectors=1 revision=v70b"
Write-Host "PASS: full-width mag2, delay history, embedded/root DAGs, flow control, active-tail, exact completion, and AC9-AC12 artifact checks."
Write-Host "Evidence: $RunDir"
