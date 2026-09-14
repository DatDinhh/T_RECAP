#requires -Version 5.1
# SPDX-License-Identifier: MIT
<#
.SYNOPSIS
Program an explicit DE1-SoC SOF into volatile FPGA configuration through JTAG.
.DESCRIPTION
Inventories the selected cable and requires the DE1-SoC HPS/FPGA chain before
programming device 2 (ID 02D120DD). Records the SOF hash, inventory, command logs,
and process exit codes. Does not select an image automatically or write flash.
.PARAMETER QuartusRoot
Quartus component directory, or an installation directory containing quartus
or quartusfpga/quartus. No installation path is assumed.
.PARAMETER Sof
Explicit .sof file. Relative paths are resolved from the repository root.
.PARAMETER BuildManifest
Successful build_manifest.json from the selected build. Its fresh SOF identity
and passed fitted-pin/timing reports must match before any JTAG tool runs.
.PARAMETER Cable
Exact jtagconfig cable name. Defaults to DE-SoC [USB-1].
.PARAMETER DeviceIndex
The FPGA is device 2 in the required two-device HPS/FPGA chain.
.PARAMETER RunDirectory
Empty directory for this programming run. Relative paths use the repository root.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $QuartusRoot,
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $Sof,
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $BuildManifest,
    [ValidateNotNullOrEmpty()]
    [string] $Cable = 'DE-SoC [USB-1]',
    [ValidateSet(2)]
    [int] $DeviceIndex = 2,
    [string] $RunDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$programRepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$programUtf8 = [Text.UTF8Encoding]::new($false)
$programOldPath = $env:PATH
$programOldQuartusRoot = $env:QUARTUS_ROOTDIR

function Get-ProgramPath {
    param([string] $Path)
    if ([IO.Path]::IsPathRooted($Path)) { return [IO.Path]::GetFullPath($Path) }
    return [IO.Path]::GetFullPath((Join-Path $programRepoRoot $Path))
}

function Find-ProgramTool {
    param([string] $Root, [string] $Name)
    foreach ($toolSubdirectory in @('bin64', 'bin')) {
        $toolPath = Join-Path (Join-Path $Root $toolSubdirectory) ($Name + '.exe')
        if (Test-Path -LiteralPath $toolPath -PathType Leaf) { return $toolPath }
    }
    throw "Quartus tool '$Name.exe' not found under: $Root"
}

function Save-ProgramManifest {
    $programManifest.updated_utc = [DateTime]::UtcNow.ToString('o')
    [IO.File]::WriteAllText($programManifestPath,
        (($programManifest | ConvertTo-Json -Depth 12) + "`n"), $programUtf8)
}

function Invoke-ProgramStage {
    param([string] $Name, [string] $Executable, [string[]] $Arguments)
    $stageLog = Join-Path $programRunRoot ($Name + '.log')
    $stage = [ordered]@{
        name = $Name; executable = $Executable; arguments = @($Arguments)
        working_directory = $programRepoRoot; log = $stageLog
        started_utc = [DateTime]::UtcNow.ToString('o'); finished_utc = $null
        exit_code = $null; status = 'running'; error = $null
    }
    $programManifest.stages.Add($stage)
    Save-ProgramManifest
    Write-Host "[$Name] $Executable"
    $stageExitCode = -1
    $stageWriter = [IO.StreamWriter]::new($stageLog, $false, $programUtf8)
    $stageWriter.AutoFlush = $true
    $stageErrorPreference = $ErrorActionPreference
    $stageLocationPushed = $false
    try {
        Push-Location -LiteralPath $programRepoRoot
        $stageLocationPushed = $true
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
        $stage.error = $_.Exception.Message
        $stageWriter.WriteLine($stage.error)
    } finally {
        $ErrorActionPreference = $stageErrorPreference
        if ($stageLocationPushed) { Pop-Location }
        $stageWriter.Dispose()
        $stage.finished_utc = [DateTime]::UtcNow.ToString('o')
        $stage.exit_code = $stageExitCode
        $stage.status = if ($stageExitCode -eq 0) { 'completed' } else { 'failed' }
        Save-ProgramManifest
    }
    if ($stageExitCode -ne 0) {
        throw "Stage '$Name' failed with exit code $stageExitCode. See $stageLog"
    }
}

function Read-JtagInventory {
    param([string] $Path)
    $inventory = [Collections.Generic.List[object]]::new()
    $currentCable = $null
    foreach ($line in [IO.File]::ReadAllLines($Path, [Text.Encoding]::UTF8)) {
        if ($line -match '^\s*([0-9]+)\)\s+(.+?)\s*$') {
            $currentCable = [pscustomobject]@{
                number = [int] $Matches[1]
                name = $Matches[2]
                devices = [Collections.Generic.List[object]]::new()
                messages = [Collections.Generic.List[string]]::new()
            }
            $inventory.Add($currentCable)
        } elseif ($null -ne $currentCable -and $line -match '^\s*([0-9A-Fa-f]{8})\s+(.+?)\s*$') {
            $currentCable.devices.Add([pscustomobject]@{
                index = $currentCable.devices.Count + 1
                idcode = $Matches[1].ToUpperInvariant()
                name = $Matches[2]
            })
        } elseif ($null -ne $currentCable -and ![string]::IsNullOrWhiteSpace($line)) {
            $currentCable.messages.Add($line.Trim())
        }
    }
    return $inventory.ToArray()
}

if ([string]::IsNullOrWhiteSpace($RunDirectory)) {
    $RunDirectory = 'runs/quartus/program/windows/' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
}
$programRunRoot = Get-ProgramPath $RunDirectory
if (Test-Path -LiteralPath $programRunRoot) {
    if (!(Test-Path -LiteralPath $programRunRoot -PathType Container) -or
        @(Get-ChildItem -LiteralPath $programRunRoot -Force).Count -ne 0) {
        throw "RunDirectory must be an empty directory: $programRunRoot"
    }
} else {
    [IO.Directory]::CreateDirectory($programRunRoot) | Out-Null
}
$programManifestPath = Join-Path $programRunRoot 'program_manifest.json'
$programManifest = [ordered]@{
    schema = 'trecap_native_windows_program_sof_v1'
    scope = 'Volatile FPGA configuration through JTAG; no flash programming or functional signoff'
    status = 'running'; started_utc = [DateTime]::UtcNow.ToString('o'); updated_utc = $null
    repository = $programRepoRoot; run_directory = $programRunRoot
    sof = $null; sof_sha256 = $null; sof_size_bytes = $null
    build_provenance = $null
    requested_cable = $Cable; selected_cable = $null; device_index = $DeviceIndex
    expected_hps_idcode = '4BA00477'; expected_fpga_idcode = '02D120DD'
    inventory = @(); tools = $null; operation = $null
    stages = [Collections.Generic.List[object]]::new(); error = $null
}
Save-ProgramManifest

try {
    if ($env:OS -ne 'Windows_NT') { throw 'This entry point requires native Windows.' }
    $programSofPath = Get-ProgramPath $Sof
    if ([IO.Path]::GetExtension($programSofPath) -ine '.sof') {
        throw 'Sof must name an explicit .sof file for volatile FPGA configuration.'
    }
    if ($programSofPath -match '[;@\r\n]') {
        throw 'The SOF path contains a delimiter reserved by the Quartus programming operation grammar.'
    }
    if (!(Test-Path -LiteralPath $programSofPath -PathType Leaf)) {
        throw "SOF file is missing: $programSofPath"
    }
    $programSofItem = Get-Item -LiteralPath $programSofPath
    if ($programSofItem.Length -eq 0) { throw 'The selected SOF is empty.' }
    $programManifest.sof = $programSofPath
    $programManifest.sof_sha256 = (Get-FileHash -LiteralPath $programSofPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $programManifest.sof_size_bytes = $programSofItem.Length

    # An explicit filename alone can still name a stale output from a failed
    # later build. Require the completed build's image and fitted-report hashes.
    $programBuildManifestPath = Get-ProgramPath $BuildManifest
    if (!(Test-Path -LiteralPath $programBuildManifestPath -PathType Leaf)) {
        throw "Successful build manifest is missing: $programBuildManifestPath"
    }
    $programBuildManifest = [IO.File]::ReadAllText($programBuildManifestPath) | ConvertFrom-Json
    if ($programBuildManifest.status -cne 'completed' -or
        $null -eq $programBuildManifest.sof -or
        $programBuildManifest.assembler_image.status -cne 'present' -or
        $programBuildManifest.assembler_image.fresh -ne $true) {
        throw 'Build manifest does not describe a completed build with a fresh nonempty SOF.'
    }
    if ($programBuildManifest.sof.sha256 -cne $programManifest.sof_sha256 -or
        $programBuildManifest.sof.size_bytes -ne $programSofItem.Length) {
        throw 'Selected SOF does not match the completed build manifest.'
    }
    foreach ($programGateName in @('fitted_pins', 'fitted_timing')) {
        $programGate = $programBuildManifest.$programGateName
        if ($programGate.status -cne 'passed') { throw "Build gate did not pass: $programGateName" }
        $programGatePath = Get-ProgramPath $programGate.report
        if (!(Test-Path -LiteralPath $programGatePath -PathType Leaf) -or
            (Get-FileHash -LiteralPath $programGatePath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $programGate.sha256) {
            throw "Build gate report is missing or changed: $programGateName"
        }
    }
    $programPinResult = [IO.File]::ReadAllText((Get-ProgramPath $programBuildManifest.fitted_pins.report)) | ConvertFrom-Json
    if ($programPinResult.status -cne 'PASS' -or $programPinResult.checked_pin_count -ne 209) {
        throw 'Fitted-pin report does not establish the complete 209-signal board contract.'
    }
    $programTimingResult = [IO.File]::ReadAllLines((Get-ProgramPath $programBuildManifest.fitted_timing.report))
    if (@($programTimingResult | Where-Object { $_ -match '^all	gate	completed	PASS	' }).Count -ne 1 -or
        @($programTimingResult | Where-Object { $_ -match '^[^	]*	[^	]*	[^	]*	FAIL	' }).Count -ne 0) {
        throw 'Fitted timing report has no unique successful completion or contains failures.'
    }
    $programManifest.build_provenance = [ordered]@{
        path = $programBuildManifestPath
        sha256 = (Get-FileHash -LiteralPath $programBuildManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
        fitted_pins_sha256 = $programBuildManifest.fitted_pins.sha256
        fitted_timing_sha256 = $programBuildManifest.fitted_timing.sha256
    }
    Save-ProgramManifest

    $programInstallation = (Resolve-Path -LiteralPath $QuartusRoot).Path
    $programQuartusDirectory = $null
    foreach ($programCandidate in @($programInstallation,
            (Join-Path $programInstallation 'quartus'),
            (Join-Path $programInstallation 'quartusfpga/quartus'))) {
        if ((Test-Path -LiteralPath (Join-Path $programCandidate 'bin64/quartus_pgm.exe') -PathType Leaf) -or
            (Test-Path -LiteralPath (Join-Path $programCandidate 'bin/quartus_pgm.exe') -PathType Leaf)) {
            $programQuartusDirectory = $programCandidate
            break
        }
    }
    if ($null -eq $programQuartusDirectory) {
        throw "Quartus component directory not found under: $programInstallation"
    }
    $programPgm = Find-ProgramTool $programQuartusDirectory 'quartus_pgm'
    $programJtag = Find-ProgramTool $programQuartusDirectory 'jtagconfig'
    $programManifest.tools = [ordered]@{ quartus_pgm = $programPgm; jtagconfig = $programJtag }
    $env:QUARTUS_ROOTDIR = $programQuartusDirectory
    $env:PATH = (Split-Path -Parent $programPgm) + ';' + $programOldPath
    Save-ProgramManifest

    Invoke-ProgramStage 'jtag-inventory' $programJtag @()
    $programInventory = @(Read-JtagInventory (Join-Path $programRunRoot 'jtag-inventory.log'))
    $programManifest.inventory = $programInventory
    Save-ProgramManifest
    $programMatches = @($programInventory | Where-Object { $_.name -ceq $Cable })
    if ($programMatches.Count -ne 1) {
        $programCableNames = @($programInventory | ForEach-Object { $_.name }) -join ', '
        throw "Cable '$Cable' must match exactly one inventory entry. Available: $programCableNames"
    }
    $programSelected = $programMatches[0]
    $programManifest.selected_cable = $programSelected
    Save-ProgramManifest
    if ($programSelected.devices.Count -ne 2 -or
        $programSelected.devices[0].idcode -cne '4BA00477' -or
        $programSelected.devices[$DeviceIndex - 1].idcode -cne '02D120DD') {
        throw 'Selected cable does not have the required HPS 4BA00477 followed by FPGA 02D120DD at device 2.'
    }
    if (@($programSelected.messages | Where-Object { $_ -match '(?i)\b(error|unable|cannot|unknown)\b' }).Count -ne 0) {
        throw 'The selected cable inventory reports an unresolved JTAG chain error.'
    }
    $programCurrentHash = (Get-FileHash -LiteralPath $programSofPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($programCurrentHash -cne $programManifest.sof_sha256) {
        throw 'The selected SOF changed during JTAG inventory; no programming command was issued.'
    }

    # The operation is a single native argument. Neither the semicolon nor
    # filename text is evaluated as PowerShell, and only volatile p is exposed.
    $programOperation = 'p;' + $programSofPath.Replace('\', '/') + '@' + $DeviceIndex
    $programManifest.operation = $programOperation
    Save-ProgramManifest
    Invoke-ProgramStage 'program-sof' $programPgm @(
        '-m', 'JTAG', '-c', $programSelected.name, '-o', $programOperation)
    $programManifest.status = 'completed'
    Save-ProgramManifest
    Write-Host "Volatile FPGA programming completed on $($programSelected.name), device $DeviceIndex."
    Write-Host "Logs and SOF identity: $programRunRoot"
} catch {
    $programManifest.status = 'failed'
    $programManifest.error = $_.Exception.Message
    Save-ProgramManifest
    throw
} finally {
    $env:PATH = $programOldPath
    $env:QUARTUS_ROOTDIR = $programOldQuartusRoot
}
