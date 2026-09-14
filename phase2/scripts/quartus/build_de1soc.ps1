#requires -Version 5.1
# SPDX-License-Identifier: MIT
<#
.SYNOPSIS
Build the source-owned DE1-SoC project with native Windows Quartus 20.1 tools.
.DESCRIPTION
Checks generated source contracts, resolves the paired FPGA/HPS profile,
constructs or reuses the Platform Designer system, generates Verilog, and
compiles the real board project. Records stage logs and exit codes. Does not
run models/tests, clean existing products, edit vendor HDL, or program hardware.
.PARAMETER QuartusRoot
Quartus component directory (containing bin64 and sopc_builder), or its parent
installation directory containing quartus or quartusfpga/quartus. No installation path is assumed.
.PARAMETER Python
Python executable path or application name. Python 3.12 is the repository baseline.
.PARAMETER Profile
Repository-relative or absolute runtime profile JSON. Defaults to BRAM replay.
.PARAMETER RunDirectory
Empty output directory for this run's logs and provenance; relative to the repository.
.PARAMETER SkipPlatformGenerate
Reuse existing normalized Qsys/HDL/IP products. Capture fresh parameter readbacks
and check generated interfaces, but do not invoke qsys-generate.
.PARAMETER GenerateOnly
Stop after Platform Designer Verilog generation and generated-interface checks.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $QuartusRoot,
    [ValidateNotNullOrEmpty()]
    [string] $Python = 'python',
    [ValidateNotNullOrEmpty()]
    [string] $Profile = 'config/profiles/de1soc_bram_replay.json',
    [string] $RunDirectory,
    [switch] $SkipPlatformGenerate,
    [switch] $GenerateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$buildRepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$buildUtf8 = [Text.UTF8Encoding]::new($false)
$buildOldPath = $env:PATH
$buildOldQuartusRoot = $env:QUARTUS_ROOTDIR
$buildOldProfileQsf = $env:TRECAP_PROFILE_QSF
$buildOldDdrQsf = $env:TRECAP_HPS_DDR_QSF

function Get-BuildPath {
    param([string] $Path)
    if ([IO.Path]::IsPathRooted($Path)) { return [IO.Path]::GetFullPath($Path) }
    return [IO.Path]::GetFullPath((Join-Path $buildRepoRoot $Path))
}

function Assert-BuildFile {
    param([string] $Path)
    if (!(Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required build input is missing: $Path"
    }
}

function Find-QuartusTool {
    param([string] $Root, [string[]] $Candidates)
    foreach ($candidate in $Candidates) {
        $toolPath = Join-Path $Root $candidate
        if (Test-Path -LiteralPath $toolPath -PathType Leaf) {
            return [IO.Path]::GetFullPath($toolPath)
        }
    }
    throw "Quartus tool not found under '$Root'; expected one of: $($Candidates -join ', ')"
}

function Save-BuildManifest {
    $buildManifest.updated_utc = [DateTime]::UtcNow.ToString('o')
    [IO.File]::WriteAllText($buildManifestPath,
        (($buildManifest | ConvertTo-Json -Depth 12) + "`n"), $buildUtf8)
}

function Invoke-BuildStage {
    param(
        [string] $Name,
        [string] $Executable,
        [string[]] $Arguments,
        [string] $WorkingDirectory = $buildRepoRoot
    )
    $stageLogPath = Join-Path $buildRunRoot ($Name + '.log')
    $stageStart = [DateTime]::UtcNow
    $stageRecord = [ordered]@{
        name = $Name
        executable = $Executable
        arguments = @($Arguments)
        working_directory = $WorkingDirectory
        log = $stageLogPath
        started_utc = $stageStart.ToString('o')
        finished_utc = $null
        exit_code = $null
        status = 'running'
        error = $null
    }
    $buildManifest.stages.Add($stageRecord)
    Save-BuildManifest
    Write-Host "[$Name] $Executable"
    $stageExitCode = -1
    $stageWriter = [IO.StreamWriter]::new($stageLogPath, $false, $buildUtf8)
    $stageWriter.AutoFlush = $true
    $stageErrorPreference = $ErrorActionPreference
    $stageLocationPushed = $false
    try {
        Push-Location -LiteralPath $WorkingDirectory
        $stageLocationPushed = $true
        # Native stderr can carry normal Quartus progress on Windows PowerShell.
        # Record both streams and use the process exit code as the stage result.
        $ErrorActionPreference = 'Continue'
        $PSNativeCommandUseErrorActionPreference = $false
        $global:LASTEXITCODE = -1
        & $Executable @Arguments 2>&1 | ForEach-Object {
            $stageLine = [string] $_
            $stageWriter.WriteLine($stageLine)
            Write-Host $stageLine
        }
        $stageExitCode = $global:LASTEXITCODE
    } catch {
        $stageRecord.error = $_.Exception.Message
        $stageWriter.WriteLine($stageRecord.error)
    } finally {
        $ErrorActionPreference = $stageErrorPreference
        if ($stageLocationPushed) { Pop-Location }
        $stageWriter.Dispose()
        $stageRecord.finished_utc = [DateTime]::UtcNow.ToString('o')
        $stageRecord.exit_code = $stageExitCode
        $stageRecord.status = if ($stageExitCode -eq 0) { 'completed' } else { 'failed' }
        Save-BuildManifest
    }
    if ($stageExitCode -ne 0) {
        throw "Stage '$Name' failed with exit code $stageExitCode. See $stageLogPath"
    }
}

function ConvertTo-QsysCommand {
    param([string[]] $Arguments)
    $encodedArguments = foreach ($argument in $Arguments) {
        [BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes($argument)).Replace('-', '').ToLowerInvariant()
    }
    return 'set ::trecap_pd_cli_hex {' + ($encodedArguments -join ',') + '}'
}

if ([string]::IsNullOrWhiteSpace($RunDirectory)) {
    $RunDirectory = 'runs/quartus/windows/' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
}
$buildRunRoot = Get-BuildPath $RunDirectory
if (Test-Path -LiteralPath $buildRunRoot) {
    if (!(Test-Path -LiteralPath $buildRunRoot -PathType Container)) {
        throw "RunDirectory is not a directory: $buildRunRoot"
    }
    if (@(Get-ChildItem -LiteralPath $buildRunRoot -Force).Count -ne 0) {
        throw "RunDirectory must be empty to preserve earlier logs: $buildRunRoot"
    }
} else {
    [IO.Directory]::CreateDirectory($buildRunRoot) | Out-Null
}
$buildManifestPath = Join-Path $buildRunRoot 'build_manifest.json'
$buildManifest = [ordered]@{
    schema = 'trecap_native_windows_quartus_build_v1'
    scope = 'Source construction and FPGA compilation; no models, simulation, programming, or hardware signoff'
    status = 'running'
    started_utc = [DateTime]::UtcNow.ToString('o')
    updated_utc = $null
    repository = $buildRepoRoot
    run_directory = $buildRunRoot
    project = 'platform/de1soc/quartus/trecap_de1soc'
    revision = 'trecap_de1soc'
    profile = $null
    profile_sha256 = $null
    tools = $null
    quartus_identity = $null
    skip_platform_generate = [bool] $SkipPlatformGenerate
    generate_only = [bool] $GenerateOnly
    platform_mode = $null
    ip_search_path = $null
    stages = [Collections.Generic.List[object]]::new()
    hps_ddr_assignments = $null
    fitted_timing = $null
    fitted_pins = $null
    previous_sof = $null
    assembler_image = $null
    sof = $null
    error = $null
}
Save-BuildManifest

try {
    if ($env:OS -ne 'Windows_NT') { throw 'Use build_de1soc.sh outside native Windows.' }
    if ($SkipPlatformGenerate -and $GenerateOnly) {
        throw '-SkipPlatformGenerate and -GenerateOnly cannot be combined.'
    }
    Assert-BuildFile (Join-Path $buildRepoRoot 'Makefile')
    $buildInstallationDirectory = (Resolve-Path -LiteralPath $QuartusRoot).Path
    $buildQuartusDirectory = $null
    foreach ($buildCandidate in @($buildInstallationDirectory,
            (Join-Path $buildInstallationDirectory 'quartus'),
            (Join-Path $buildInstallationDirectory 'quartusfpga/quartus'))) {
        if ((Test-Path -LiteralPath (Join-Path $buildCandidate 'bin64/quartus_sh.exe') -PathType Leaf) -or
            (Test-Path -LiteralPath (Join-Path $buildCandidate 'bin/quartus_sh.exe') -PathType Leaf)) {
            $buildQuartusDirectory = $buildCandidate
            break
        }
    }
    if ($null -eq $buildQuartusDirectory) {
        throw "Quartus component directory not found under: $buildInstallationDirectory"
    }
    $buildQuartusSh = Find-QuartusTool $buildQuartusDirectory @('bin64/quartus_sh.exe', 'bin/quartus_sh.exe')
    $buildQuartusMap = Find-QuartusTool $buildQuartusDirectory @('bin64/quartus_map.exe', 'bin/quartus_map.exe')
    $buildQuartusFit = Find-QuartusTool $buildQuartusDirectory @('bin64/quartus_fit.exe', 'bin/quartus_fit.exe')
    $buildQuartusAsm = Find-QuartusTool $buildQuartusDirectory @('bin64/quartus_asm.exe', 'bin/quartus_asm.exe')
    $buildQuartusSta = Find-QuartusTool $buildQuartusDirectory @('bin64/quartus_sta.exe', 'bin/quartus_sta.exe')
    $buildQsysScript = Find-QuartusTool $buildQuartusDirectory @(
        'sopc_builder/bin/qsys-script.exe', 'sopc_builder/bin/qsys-script.bat',
        'bin64/qsys-script.exe', 'bin/qsys-script.exe')
    $buildQsysGenerate = Find-QuartusTool $buildQuartusDirectory @(
        'sopc_builder/bin/qsys-generate.exe', 'sopc_builder/bin/qsys-generate.bat',
        'bin64/qsys-generate.exe', 'bin/qsys-generate.exe')
    $buildPython = (Get-Command -Name $Python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    $buildProfile = Get-BuildPath $Profile
    Assert-BuildFile $buildProfile
    $buildManifest.profile = $buildProfile
    $buildManifest.profile_sha256 = (Get-FileHash -LiteralPath $buildProfile -Algorithm SHA256).Hash.ToLowerInvariant()
    $buildManifest.tools = [ordered]@{
        quartus_sh = $buildQuartusSh; quartus_map = $buildQuartusMap
        quartus_fit = $buildQuartusFit; quartus_asm = $buildQuartusAsm
        quartus_sta = $buildQuartusSta; qsys_script = $buildQsysScript
        qsys_generate = $buildQsysGenerate; python = $buildPython; qsys_package = '16.0'
    }
    $env:QUARTUS_ROOTDIR = $buildQuartusDirectory
    $env:PATH = (Split-Path -Parent $buildQuartusSh) + ';' + (Split-Path -Parent $buildQsysScript) + ';' + $buildOldPath
    Save-BuildManifest

    Invoke-BuildStage 'quartus-version' $buildQuartusSh @('--version')
    $buildVersionFile = Join-Path $buildRunRoot 'quartus-version.log'
    $buildVersion = [IO.File]::ReadAllText($buildVersionFile)
    $buildIdentityMatch = [regex]::Match($buildVersion,
        '(?im)^\s*(?:Quartus\s+Prime\s+)?Version\s+(?<release>20\.1(?:\.\d+)?)\s+Build\s+\d+\b[^\r\n]*?\b(?<edition>Standard|Lite)\s+Edition\b')
    if (!$buildIdentityMatch.Success) {
        throw "This project requires Quartus Prime 20.1.x Standard or Lite Edition. See $buildVersionFile"
    }
    $buildObservedEdition = if ($buildIdentityMatch.Groups['edition'].Value -ieq 'Lite') {
        'Lite Edition'
    } else {
        'Standard Edition'
    }
    $buildManifest.quartus_identity = [ordered]@{
        release = $buildIdentityMatch.Groups['release'].Value
        edition = $buildObservedEdition
        version_output = $buildVersion.Trim()
    }
    Save-BuildManifest

    # These are generation/configuration checks only. check_generated.py is
    # intentionally not invoked because it also executes negative test cases.
    Invoke-BuildStage 'generated-headers' $buildPython @('scripts/gen_headers.py', '--check', '--quiet')
    Invoke-BuildStage 'generated-filelists' $buildPython @('scripts/gen_filelists.py', '--check', '--quiet')
    Invoke-BuildStage 'hps-platform-source' $buildPython @('scripts/check_hps_platform.py', '--quiet')
    Invoke-BuildStage 'address-map-source' $buildPython @('scripts/check_address_map.py', '--quiet')
    Invoke-BuildStage 'profile-source' $buildPython @(
        'scripts/check_profiles.py', '--profile', $buildProfile, '--require-build',
        '--expect-target', 'de1soc_full', '--expect-top', 'de1_soc_trecap_top',
        '--expect-platform', 'de1soc', '--expect-project', 'platform/de1soc/quartus/trecap_de1soc', '--quiet')
    Invoke-BuildStage 'runtime-profile' $buildPython @(
        'scripts/resolve_runtime_profile.py', '--profile', $buildProfile,
        '--output', (Join-Path $buildRunRoot 'effective_runtime.json'))
    $buildProfileQsf = Join-Path $buildRunRoot 'profile_parameters.qsf'
    Invoke-BuildStage 'quartus-profile' $buildPython @(
        'scripts/resolve_runtime_profile.py', '--profile', $buildProfile,
        '--format', 'qsf', '--output', $buildProfileQsf)
    $env:TRECAP_PROFILE_QSF = $buildProfileQsf.Replace('\', '/')

    $buildCsrIpDirectory = Join-Path $buildRepoRoot 'platform/de1soc/qsys/ip/trecap_csr_bridge'
    Assert-BuildFile (Join-Path $buildCsrIpDirectory 'trecap_avalon_csr_bridge_hw.tcl')
    # The literal $ preserves Quartus's standard IP catalog after our source-owned IP.
    $buildIpSearchPath = $buildCsrIpDirectory.Replace('\', '/') + '/*,$'
    $buildManifest.ip_search_path = $buildIpSearchPath
    Save-BuildManifest

    $buildQsysFile = Join-Path $buildRepoRoot 'platform/de1soc/qsys/system.qsys'
    $buildPdScript = Join-Path $buildRepoRoot 'platform/de1soc/qsys/platform_designer.tcl'
    Assert-BuildFile $buildQsysFile
    Assert-BuildFile $buildPdScript
    $buildBootstrap = [IO.File]::ReadAllText($buildQsysFile).Contains('T_RECAP_BOOTSTRAP_QSYS_SOURCE=1')
    if ($SkipPlatformGenerate -and $buildBootstrap) {
        throw '-SkipPlatformGenerate requires an existing Quartus-normalized system.qsys.'
    }
    $buildPdMode = if ($buildBootstrap) { 'construct' } else { 'capture-readback' }
    $buildReadback = Join-Path $buildRunRoot 'hps_readback.tsv'
    # Match native Qsys's path representation while keeping each complete
    # argument encoded; spaces and Tcl metacharacters never become script text.
    $buildPdArguments = @('--mode', $buildPdMode, '--repo-root', $buildRepoRoot.Replace('\', '/'),
        '--python-exe', $buildPython.Replace('\', '/'), '--strict-exports',
        '--readback-output', $buildReadback.Replace('\', '/'))
    $buildManifest.platform_mode = $buildPdMode
    Invoke-BuildStage ('qsys-' + $buildPdMode) $buildQsysScript @(
        '--package-version=16.0', ('--search-path=' + $buildIpSearchPath),
        ('--cmd=' + (ConvertTo-QsysCommand $buildPdArguments)),
        ('--script=' + $buildPdScript.Replace('\', '/')))
    Assert-BuildFile $buildReadback
    if ([IO.File]::ReadAllText($buildQsysFile).Contains('T_RECAP_BOOTSTRAP_QSYS_SOURCE=1')) {
        throw 'Platform Designer left system.qsys in bootstrap form.'
    }

    if (!$SkipPlatformGenerate) {
        Invoke-BuildStage 'qsys-generate' $buildQsysGenerate @(
            $buildQsysFile.Replace('\', '/'), '--synthesis=VERILOG',
            ('--search-path=' + $buildIpSearchPath),
            ('--output-directory=' + (Join-Path $buildRepoRoot 'platform/de1soc/qsys/system').Replace('\', '/')))
    }
    Assert-BuildFile (Join-Path $buildRepoRoot 'platform/de1soc/qsys/system.sopcinfo')
    Assert-BuildFile (Join-Path $buildRepoRoot 'platform/de1soc/qsys/system/synthesis/system.qip')
    $buildGeneratedV = Join-Path $buildRepoRoot 'platform/de1soc/qsys/system/synthesis/system.v'
    $buildGeneratedSv = Join-Path $buildRepoRoot 'platform/de1soc/qsys/system/synthesis/system.sv'
    if (!(Test-Path -LiteralPath $buildGeneratedV -PathType Leaf) -and
        !(Test-Path -LiteralPath $buildGeneratedSv -PathType Leaf)) {
        throw 'Platform Designer synthesis/system.v or system.sv is missing.'
    }
    Invoke-BuildStage 'generated-address-map' $buildPython @(
        'scripts/check_address_map.py', '--require-sopcinfo', '--quiet')
    Invoke-BuildStage 'generated-platform-wrapper' $buildPython @(
        'scripts/check_platform_designer_wrapper.py', '--require-generated', '--quiet')
    $buildEffectiveMode = if ($SkipPlatformGenerate) { 'reuse-generated' } elseif ($buildBootstrap) { 'construct+generate' } else { 'generate' }
    $buildConstruction = if ($buildBootstrap) { 'true' } else { 'false' }
    Invoke-BuildStage 'platform-manifest' $buildPython @(
        'scripts/write_platform_generation_manifest.py', '--repo-root', $buildRepoRoot,
        '--output', (Join-Path $buildRunRoot 'platform_generation_manifest.json'),
        '--mode-requested', 'native-windows', '--mode-effective', $buildEffectiveMode,
        '--construction-performed', $buildConstruction, '--qsys-script', $buildQsysScript,
        '--qsys-generate', $buildQsysGenerate, '--quartus-version-file', $buildVersionFile,
        '--readback-tsv', $buildReadback, '--require-generated')

    if (!$GenerateOnly) {
        $buildProjectDirectory = Join-Path $buildRepoRoot 'platform/de1soc/quartus'
        Assert-BuildFile (Join-Path $buildProjectDirectory 'trecap_de1soc.qpf')
        Assert-BuildFile (Join-Path $buildProjectDirectory 'trecap_de1soc.qsf')
        $buildDdrAdapter = Join-Path $buildRepoRoot 'scripts/quartus/capture_hps_ddr_assignments.tcl'
        $buildDdrVendorScript = Join-Path $buildRepoRoot 'platform/de1soc/qsys/system/synthesis/submodules/hps_sdram_p0_pin_assignments.tcl'
        Assert-BuildFile $buildDdrAdapter
        Assert-BuildFile $buildDdrVendorScript
        $buildDdrQsf = Join-Path $buildRunRoot 'hps_ddr_assignments.qsf'
        $env:TRECAP_HPS_DDR_QSF = $buildDdrQsf.Replace('\', '/')
        # Preserve any earlier image outside the active output directory before
        # starting this build; assembler exit 0 in Evaluation Mode can emit no SOF.
        $buildOutputDirectory = [IO.Path]::GetFullPath((Join-Path $buildProjectDirectory 'output_files'))
        $buildSof = [IO.Path]::GetFullPath((Join-Path $buildOutputDirectory 'trecap_de1soc.sof'))
        $buildPreviousSofDirectory = [IO.Path]::GetFullPath((Join-Path $buildRunRoot 'previous_sof'))
        $buildPreviousSof = [IO.Path]::GetFullPath((Join-Path $buildPreviousSofDirectory 'trecap_de1soc.sof'))
        if (!(Split-Path -Parent $buildSof).Equals($buildOutputDirectory, [StringComparison]::OrdinalIgnoreCase) -or
            !$buildPreviousSof.StartsWith($buildRunRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Resolved SOF archive paths leave the project output or selected run directory.'
        }
        if (Test-Path -LiteralPath $buildSof -PathType Leaf) {
            $buildManifest.previous_sof = [ordered]@{
                original_path = $buildSof; archived_path = $buildPreviousSof
                sha256 = (Get-FileHash -LiteralPath $buildSof -Algorithm SHA256).Hash.ToLowerInvariant()
            }
            [IO.Directory]::CreateDirectory($buildPreviousSofDirectory) | Out-Null
            Move-Item -LiteralPath $buildSof -Destination $buildPreviousSof -ErrorAction Stop
            Save-BuildManifest
        }
        $buildModuleArguments = @('--read_settings_files=on', '--write_settings_files=off',
            'trecap_de1soc', '-c', 'trecap_de1soc')
        Invoke-BuildStage 'quartus-map' $buildQuartusMap $buildModuleArguments $buildProjectDirectory
        Invoke-BuildStage 'hps-ddr-pin-assignments' $buildQuartusSta @(
            '-t', $buildDdrAdapter.Replace('\', '/'), 'trecap_de1soc', 'trecap_de1soc',
            $buildDdrVendorScript.Replace('\', '/'), $buildDdrQsf.Replace('\', '/'),
            $buildPython.Replace('\', '/')) $buildProjectDirectory
        Assert-BuildFile $buildDdrQsf
        $buildManifest.hps_ddr_assignments = [ordered]@{
            path = $buildDdrQsf
            sha256 = (Get-FileHash -LiteralPath $buildDdrQsf -Algorithm SHA256).Hash.ToLowerInvariant()
            vendor_script_sha256 = (Get-FileHash -LiteralPath $buildDdrVendorScript -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        Save-BuildManifest
        Invoke-BuildStage 'quartus-fit' $buildQuartusFit $buildModuleArguments $buildProjectDirectory
        $buildPinReport = Join-Path $buildRunRoot 'fitted_pins.json'
        Invoke-BuildStage 'fitted-pins' $buildPython @(
            'scripts/check_fitted_pins.py', '--pin-file',
            (Join-Path $buildOutputDirectory 'trecap_de1soc.pin'), '--report', $buildPinReport)
        $buildManifest.fitted_pins = [ordered]@{
            report = $buildPinReport
            sha256 = (Get-FileHash -LiteralPath $buildPinReport -Algorithm SHA256).Hash.ToLowerInvariant()
            status = 'passed'
        }
        Save-BuildManifest
        Invoke-BuildStage 'quartus-asm' $buildQuartusAsm $buildModuleArguments $buildProjectDirectory
        $buildSofPresent = (Test-Path -LiteralPath $buildSof -PathType Leaf) -and
            ((Get-Item -LiteralPath $buildSof).Length -gt 0)
        $buildManifest.assembler_image = [ordered]@{
            expected_path = $buildSof
            assembler_exit_code = 0
            fresh = [bool] $buildSofPresent
            status = if ($buildSofPresent) { 'present' } else { 'missing' }
        }
        Save-BuildManifest
        if (!$buildSofPresent) {
            Write-Host 'Assembler exited with code 0 but produced no SOF. Timing reports will continue; inspect quartus-asm.log for evaluation/license restrictions.'
        }
        # quartus_sta 20.1 rejects the map/fit/asm read/write-settings switches.
        Invoke-BuildStage 'quartus-sta' $buildQuartusSta @(
            'trecap_de1soc', '-c', 'trecap_de1soc') $buildProjectDirectory
        $buildTimingGate = Join-Path $buildRepoRoot 'scripts/quartus/check_fitted_timing.tcl'
        $buildTimingDirectory = Join-Path $buildRunRoot 'fitted-timing'
        Assert-BuildFile $buildTimingGate
        Invoke-BuildStage 'fitted-timing-gate' $buildQuartusSta @(
            '-t', $buildTimingGate.Replace('\', '/'), 'trecap_de1soc', 'trecap_de1soc',
            $buildTimingDirectory.Replace('\', '/')) $buildProjectDirectory
        $buildTimingReport = Join-Path $buildTimingDirectory 'fitted_timing.tsv'
        Assert-BuildFile $buildTimingReport
        $buildManifest.fitted_timing = [ordered]@{
            report = $buildTimingReport
            sha256 = (Get-FileHash -LiteralPath $buildTimingReport -Algorithm SHA256).Hash.ToLowerInvariant()
            status = 'passed'
        }
        Save-BuildManifest
        if (!$buildSofPresent -or !(Test-Path -LiteralPath $buildSof -PathType Leaf) -or
            (Get-Item -LiteralPath $buildSof).Length -eq 0) {
            throw 'No fresh nonempty FPGA image was produced although the assembler exited with code 0. Timing results are retained; inspect quartus-asm.log for evaluation/license restrictions. This build cannot be programmed.'
        }
        $buildManifest.sof = [ordered]@{
            path = $buildSof
            sha256 = (Get-FileHash -LiteralPath $buildSof -Algorithm SHA256).Hash.ToLowerInvariant()
            size_bytes = (Get-Item -LiteralPath $buildSof).Length
        }
    }
    $buildManifest.status = 'completed'
    Save-BuildManifest
    Write-Host "Build stages completed. Logs and provenance: $buildRunRoot"
    if (!$GenerateOnly) { Write-Host "FPGA image: $buildSof" }
} catch {
    $buildManifest.status = 'failed'
    $buildManifest.error = $_.Exception.Message
    if ($null -ne $buildManifest.assembler_image -and !$buildManifest.assembler_image.fresh) {
        $buildManifest.error += ' No fresh nonempty SOF was produced; this build cannot be programmed. See quartus-asm.log and retained timing diagnostics.'
        Write-Warning $buildManifest.error
    }
    Save-BuildManifest
    throw
} finally {
    $env:PATH = $buildOldPath
    $env:QUARTUS_ROOTDIR = $buildOldQuartusRoot
    $env:TRECAP_PROFILE_QSF = $buildOldProfileQsf
    $env:TRECAP_HPS_DDR_QSF = $buildOldDdrQsf
}
