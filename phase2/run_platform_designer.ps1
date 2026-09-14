[CmdletBinding()]
param(
    [string]$Repo = $PSScriptRoot,
    [string]$QuartusRoot = "",
    [ValidateSet("16.0")]
    [string]$QsysPackageVersion = "16.0",
    [string]$RunDir,
    [string]$Python = "python.exe",
    [switch]$ValidateOnly,
    [switch]$ConstructOnly,
    [switch]$ForceReconstruct,
    [switch]$ReuseExisting,
    [switch]$KeepGenerated,
    [switch]$ProbeHps,
    [switch]$SkipContractChecks,
    [switch]$NoWrapperShell
)

# SPDX-License-Identifier: MIT
# Canonical Windows entry point for the T-RECAP DE1-SoC Platform Designer flow.
# QuartusRoot must identify one Quartus installation, not a directory containing
# several releases. This is the only supported Windows Platform Designer runner.

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -Scope Global -ErrorAction SilentlyContinue) {
    $Global:PSNativeCommandUseErrorActionPreference = $false
}

$BootstrapMarker = "T_RECAP_BOOTSTRAP_QSYS_SOURCE=1"

function ConvertTo-WindowsCommandLineArgument {
    param([AllowEmptyString()][string]$Value)

    if ($null -eq $Value) { $Value = "" }
    if (($Value.Length -gt 0) -and ($Value -notmatch '[\s"]')) { return $Value }

    # Start-Process joins ArgumentList entries. Quote explicitly according to the
    # Windows CRT/CommandLineToArgvW backslash rules so Tcl payloads and paths stay
    # one native argument in both Windows PowerShell 5.1 and PowerShell 7.
    $Builder = New-Object System.Text.StringBuilder
    [void]$Builder.Append([char]34)
    $Backslashes = 0
    foreach ($Character in $Value.ToCharArray()) {
        if ($Character -eq [char]92) {
            $Backslashes++
            continue
        }
        if ($Character -eq [char]34) {
            [void]$Builder.Append([char]92, (($Backslashes * 2) + 1))
            [void]$Builder.Append([char]34)
            $Backslashes = 0
            continue
        }
        if ($Backslashes -gt 0) {
            [void]$Builder.Append([char]92, $Backslashes)
            $Backslashes = 0
        }
        [void]$Builder.Append($Character)
    }
    if ($Backslashes -gt 0) {
        [void]$Builder.Append([char]92, ($Backslashes * 2))
    }
    [void]$Builder.Append([char]34)
    return $Builder.ToString()
}

function Append-RedirectedText {
    param(
        [Parameter(Mandatory=$true)][string]$Source,
        [Parameter(Mandatory=$true)][string]$Destination
    )

    if (!(Test-Path -LiteralPath $Source -PathType Leaf)) { return }
    $Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    foreach ($Line in (Get-Content -LiteralPath $Source -ErrorAction SilentlyContinue)) {
        [System.IO.File]::AppendAllText($Destination, "$Line`r`n", $Utf8NoBom)
        Write-Host $Line
    }
}

function Run-NativeLogged {
    param(
        [Parameter(Mandatory=$true)][string]$Exe,
        [Parameter(Mandatory=$true)][string[]]$Args,
        [Parameter(Mandatory=$true)][string]$Log,
        [Parameter(Mandatory=$true)][string]$WorkDir,
        [switch]$OutputOnly
    )

    $LogParent = Split-Path -Parent $Log
    if (!(Test-Path -LiteralPath $LogParent -PathType Container)) {
        New-Item -ItemType Directory -Path $LogParent -Force | Out-Null
    }
    $TmpOut = "$Log.stdout.tmp"
    $TmpErr = "$Log.stderr.tmp"
    Remove-Item -LiteralPath $TmpOut, $TmpErr -Force -ErrorAction SilentlyContinue

    $NativeArgumentLine = (($Args | ForEach-Object {
        ConvertTo-WindowsCommandLineArgument -Value $_
    }) -join " ")
    Write-Host ""
    Write-Host "CMD: $Exe $NativeArgumentLine"

    $Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    if ($OutputOnly) {
        [System.IO.File]::WriteAllText($Log, "", $Utf8NoBom)
    } else {
        [System.IO.File]::WriteAllText(
            $Log,
            "CMD:`r`n  $Exe $NativeArgumentLine`r`n`r`n",
            $Utf8NoBom
        )
    }

    $Process = Start-Process -FilePath $Exe `
                             -ArgumentList $NativeArgumentLine `
                             -WorkingDirectory $WorkDir `
                             -RedirectStandardOutput $TmpOut `
                             -RedirectStandardError $TmpErr `
                             -NoNewWindow `
                             -Wait `
                             -PassThru
    $ReturnCode = [int]$Process.ExitCode

    Append-RedirectedText -Source $TmpOut -Destination $Log
    Append-RedirectedText -Source $TmpErr -Destination $Log
    Remove-Item -LiteralPath $TmpOut, $TmpErr -Force -ErrorAction SilentlyContinue

    if ($ReturnCode -ne 0) {
        Write-Host ""
        Write-Host "FAILED log tail:"
        Get-Content -LiteralPath $Log -Tail 120 -ErrorAction SilentlyContinue
        throw "FAILED: $Exe exit code $ReturnCode. See log: $Log"
    }
}

function ConvertTo-Utf8Hex {
    param([AllowEmptyString()][Parameter(Mandatory=$true)][string]$Value)

    $Bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
    return ([System.BitConverter]::ToString($Bytes)).Replace("-", "").ToLowerInvariant()
}

function Run-QsysScriptLogged {
    param(
        [Parameter(Mandatory=$true)][string]$Exe,
        [Parameter(Mandatory=$true)][string]$PackageVersion,
        [Parameter(Mandatory=$true)][string]$Script,
        [Parameter(Mandatory=$true)][string[]]$TclArgs,
        [Parameter(Mandatory=$true)][string]$PythonExe,
        [Parameter(Mandatory=$true)][string]$Log,
        [Parameter(Mandatory=$true)][string]$WorkDir
    )

    # Quartus 20.1 documents --cmd, not a bare "--" forwarding convention.
    # UTF-8 hex survives PowerShell, native Windows argument parsing, and Tcl.
    $ForwardedTclArgs = @($TclArgs) + @("--python-exe", $PythonExe)
    $EncodedArgs = (($ForwardedTclArgs | ForEach-Object {
        ConvertTo-Utf8Hex -Value $_
    }) -join ",")
    $TclCommand = "set ::trecap_pd_cli_hex {$EncodedArgs}"
    Run-NativeLogged -Exe $Exe -Args @(
        "--package-version=$PackageVersion",
        "--cmd=$TclCommand",
        "--script=$Script"
    ) -Log $Log -WorkDir $WorkDir
}

function Select-ExistingFile {
    param([Parameter(Mandatory=$true)][string[]]$Candidates)

    foreach ($Candidate in $Candidates) {
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            return [System.IO.Path]::GetFullPath($Candidate)
        }
    }
    return $null
}

function Assert-NoReparsePointWithinBoundary {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$Boundary
    )

    $BoundaryPath = [System.IO.Path]::GetFullPath($Boundary).TrimEnd([char[]]"\/")
    $CurrentPath = [System.IO.Path]::GetFullPath($Path)
    while ($true) {
        $Item = Get-Item -LiteralPath $CurrentPath -Force
        if (($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing reparse-point path inside a trusted tree: $CurrentPath"
        }
        $ComparablePath = $CurrentPath.TrimEnd([char[]]"\/")
        if ($ComparablePath.Equals($BoundaryPath, [System.StringComparison]::OrdinalIgnoreCase)) {
            return
        }
        $ParentPath = Split-Path -Parent $CurrentPath
        if ([string]::IsNullOrWhiteSpace($ParentPath) -or
            $ParentPath.Equals($CurrentPath, [System.StringComparison]::OrdinalIgnoreCase)) {
            break
        }
        $CurrentPath = [System.IO.Path]::GetFullPath($ParentPath)
    }
    throw "Path is not contained by the trusted boundary: path=$Path boundary=$Boundary"
}

function Assert-NoNestedReparsePoints {
    param([Parameter(Mandatory=$true)][string]$Directory)

    foreach ($Child in @(Get-ChildItem -LiteralPath $Directory -Force -ErrorAction Stop)) {
        if (($Child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing generated tree containing a reparse point: $($Child.FullName)"
        }
        if ($Child.PSIsContainer) {
            Assert-NoNestedReparsePoints -Directory $Child.FullName
        }
    }
}

function Resolve-QuartusTools {
    param(
        [Parameter(Mandatory=$true)][string]$Root,
        [Parameter(Mandatory=$true)][bool]$RequireGenerate
    )

    if (!(Test-Path -LiteralPath $Root -PathType Container)) {
        throw "QuartusRoot does not identify an installation directory: $Root"
    }
    $ResolvedRoot = (Resolve-Path -LiteralPath $Root).Path
    $NestedQuartus = Join-Path $ResolvedRoot "quartus"
    if (Test-Path -LiteralPath $NestedQuartus -PathType Container) {
        $QuartusDir = (Resolve-Path -LiteralPath $NestedQuartus).Path
    } else {
        $QuartusDir = $ResolvedRoot
    }

    # Deliberately enumerate only fixed locations inside this installation. Do
    # not recurse into sibling/version directories and mix executable releases.
    $QuartusSh = Select-ExistingFile -Candidates @(
        (Join-Path $QuartusDir "bin64\quartus_sh.exe"),
        (Join-Path $QuartusDir "bin\quartus_sh.exe"),
        (Join-Path $QuartusDir "quartus_sh.exe")
    )

    $QsysScript = $null
    $QsysGenerate = $null
    $QsysDirectories = @(
        (Join-Path $QuartusDir "sopc_builder\bin64"),
        (Join-Path $QuartusDir "sopc_builder\bin"),
        (Join-Path $QuartusDir "bin64"),
        (Join-Path $QuartusDir "bin")
    )
    foreach ($QsysDirectory in $QsysDirectories) {
        $QsysScriptCandidate = Join-Path $QsysDirectory "qsys-script.exe"
        $QsysGenerateCandidate = Join-Path $QsysDirectory "qsys-generate.exe"
        if (!(Test-Path -LiteralPath $QsysScriptCandidate -PathType Leaf)) { continue }
        $GeneratePresent = Test-Path -LiteralPath $QsysGenerateCandidate -PathType Leaf
        if ($null -eq $QsysScript) {
            $QsysScript = [System.IO.Path]::GetFullPath($QsysScriptCandidate)
        }
        if ($RequireGenerate -and !$GeneratePresent) { continue }
        $QsysScript = [System.IO.Path]::GetFullPath($QsysScriptCandidate)
        if ($GeneratePresent) {
            $QsysGenerate = [System.IO.Path]::GetFullPath($QsysGenerateCandidate)
        }
        break
    }

    if (($null -eq $QuartusSh) -or ($null -eq $QsysScript)) {
        throw "QuartusRoot must name one Quartus 20.1 installation containing quartus_sh.exe and qsys-script.exe in standard bin locations; no recursive installation search is performed: $ResolvedRoot"
    }
    if ($RequireGenerate -and ($null -eq $QsysGenerate)) {
        throw "This lifecycle requires qsys-generate.exe co-located with qsys-script.exe under the explicit QuartusRoot: $ResolvedRoot"
    }

    $QuartusPrefix = $QuartusDir
    if (!$QuartusPrefix.EndsWith([System.IO.Path]::DirectorySeparatorChar.ToString())) {
        $QuartusPrefix += [System.IO.Path]::DirectorySeparatorChar
    }
    $ResolvedTools = @($QuartusSh, $QsysScript)
    if ($null -ne $QsysGenerate) { $ResolvedTools += $QsysGenerate }
    foreach ($ToolPath in $ResolvedTools) {
        if (!$ToolPath.StartsWith($QuartusPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Resolved tool is outside the explicit Quartus installation: $ToolPath"
        }
        Assert-NoReparsePointWithinBoundary -Path $ToolPath -Boundary $QuartusDir
    }

    return [pscustomobject]@{
        Root = [System.IO.Path]::GetFullPath($QuartusDir)
        QuartusSh = $QuartusSh
        QsysScript = $QsysScript
        QsysGenerate = $QsysGenerate
    }
}

function Resolve-CommandPath {
    param([Parameter(Mandatory=$true)][string]$Command)

    if (Test-Path -LiteralPath $Command -PathType Leaf) {
        return (Resolve-Path -LiteralPath $Command).Path
    }
    $Resolved = Get-Command $Command -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $Resolved) { throw "Required executable is not available: $Command" }
    return $Resolved.Source
}

function Require-File {
    param([Parameter(Mandatory=$true)][string]$Path)

    if (!(Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required file is missing: $Path"
    }
}

function Get-ArtifactFingerprint {
    param([Parameter(Mandatory=$true)][string]$Path)

    if (!(Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $Item = Get-Item -LiteralPath $Path -Force
    return [pscustomobject]@{
        Length = [int64]$Item.Length
        LastWriteTimeUtc = $Item.LastWriteTimeUtc
        Sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Require-FreshGeneratedFile {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][DateTime]$GenerationStartedUtc,
        [AllowNull()]$PreviousFingerprint
    )

    Require-File -Path $Path
    $Current = Get-ArtifactFingerprint -Path $Path
    if ($Current.Length -le 0) {
        throw "Generated artifact is empty: $Path"
    }
    # NTFS is precise, but retain a small allowance for tools/filesystems that
    # round timestamps while also requiring a changed pre-run fingerprint.
    if ($Current.LastWriteTimeUtc -lt $GenerationStartedUtc.AddSeconds(-2)) {
        throw "Generated artifact was not refreshed by this run: $Path"
    }
    if (($null -ne $PreviousFingerprint) -and
        ($Current.Length -eq $PreviousFingerprint.Length) -and
        ($Current.LastWriteTimeUtc -eq $PreviousFingerprint.LastWriteTimeUtc) -and
        ($Current.Sha256 -eq $PreviousFingerprint.Sha256)) {
        throw "Generated artifact still matches its complete pre-run fingerprint: $Path"
    }
}

function Assert-ManifestArtifactRecord {
    param(
        [Parameter(Mandatory=$true)]$Record,
        [Parameter(Mandatory=$true)][string]$ExpectedRelativePath,
        [Parameter(Mandatory=$true)][string]$Root
    )

    if ($Record.present -ne $true) {
        throw "Manifest marks a required artifact absent: $ExpectedRelativePath"
    }
    if ($Record.path -ne $ExpectedRelativePath) {
        throw "Manifest artifact path mismatch: expected=$ExpectedRelativePath actual=$($Record.path)"
    }
    if (($Record.sha256 -as [string]) -notmatch '^[0-9a-fA-F]{64}$') {
        throw "Manifest artifact has no valid SHA-256: $ExpectedRelativePath"
    }
    $NativeRelativePath = $ExpectedRelativePath.Replace(
        "/",
        [System.IO.Path]::DirectorySeparatorChar.ToString()
    )
    $ActualPath = Join-Path $Root $NativeRelativePath
    Require-File -Path $ActualPath
    $ActualItem = Get-Item -LiteralPath $ActualPath -Force
    $ActualHash = (Get-FileHash -LiteralPath $ActualPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ([int64]$Record.size_bytes -ne [int64]$ActualItem.Length) {
        throw "Manifest size does not match current artifact: $ExpectedRelativePath"
    }
    if ($Record.sha256.ToLowerInvariant() -ne $ActualHash) {
        throw "Manifest hash does not match current artifact: $ExpectedRelativePath"
    }
}

function Assert-GenerationManifest {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$Root,
        [Parameter(Mandatory=$true)][string]$ExpectedModeRequested,
        [Parameter(Mandatory=$true)][string]$ExpectedModeEffective,
        [Parameter(Mandatory=$true)][string]$ExpectedConstructionPerformed,
        [Parameter(Mandatory=$true)][string]$ExpectedQsysGenerate,
        [Parameter(Mandatory=$true)][bool]$RequireGenerated,
        [Parameter(Mandatory=$true)][bool]$RequireReadback
    )

    Require-File -Path $Path
    try {
        $Manifest = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    } catch {
        throw "Cannot parse generation manifest JSON: $Path ($($_.Exception.Message))"
    }
    if ($Manifest.schema -ne "trecap_phase2_platform_generation_manifest_v3") {
        throw "Unexpected generation manifest schema: $($Manifest.schema)"
    }
    if ($Manifest.complete -ne $true -or @($Manifest.errors).Count -ne 0) {
        throw "Generation manifest is not complete: $Path"
    }
    if ($Manifest.mode_requested -ne $ExpectedModeRequested -or
        $Manifest.mode_effective -ne $ExpectedModeEffective) {
        throw "Generation manifest mode mismatch: requested=$($Manifest.mode_requested) effective=$($Manifest.mode_effective)"
    }
    $ExpectedConstructionBoolean = $ExpectedConstructionPerformed -eq "true"
    if ($Manifest.construction_performed -ne $ExpectedConstructionBoolean) {
        throw "Generation manifest construction flag mismatch"
    }
    if ($Manifest.tools.qsys_generate -ne $ExpectedQsysGenerate) {
        throw "Generation manifest qsys-generate provenance mismatch"
    }
    if ($Manifest.generated_artifacts_required -ne $RequireGenerated) {
        throw "Generation manifest generated-artifact policy mismatch"
    }

    Assert-ManifestArtifactRecord -Record $Manifest.artifacts.system_qsys `
        -ExpectedRelativePath "platform/de1soc/qsys/system.qsys" -Root $Root

    if ($RequireReadback) {
        if ($Manifest.hps_readback.present -ne $true -or
            [int]$Manifest.hps_readback.parameter_count -ne 44 -or
            ($Manifest.hps_readback.canonical_sha256 -as [string]) -notmatch '^[0-9a-fA-F]{64}$') {
            throw "Generation manifest lacks a complete 44-parameter HPS readback capture"
        }
    }

    if ($RequireGenerated) {
        if ($Manifest.qsys_state -ne "quartus_normalized") {
            throw "Generation manifest does not describe a normalized Qsys source"
        }
        Assert-ManifestArtifactRecord -Record $Manifest.artifacts.system_sopcinfo `
            -ExpectedRelativePath "platform/de1soc/qsys/system.sopcinfo" -Root $Root
        Assert-ManifestArtifactRecord -Record $Manifest.artifacts.system_qip `
            -ExpectedRelativePath "platform/de1soc/qsys/system/synthesis/system.qip" -Root $Root

        $PresentHdlRecords = @($Manifest.artifacts.generated_hdl | Where-Object { $_.present -eq $true })
        if ($PresentHdlRecords.Count -eq 0) {
            throw "Generation manifest contains no generated system.v/system.sv record"
        }
        foreach ($HdlRecord in $PresentHdlRecords) {
            if ($HdlRecord.path -notin @(
                "platform/de1soc/qsys/system/synthesis/system.v",
                "platform/de1soc/qsys/system/synthesis/system.sv"
            )) {
                throw "Generation manifest contains an unexpected HDL path: $($HdlRecord.path)"
            }
            Assert-ManifestArtifactRecord -Record $HdlRecord `
                -ExpectedRelativePath $HdlRecord.path -Root $Root
        }
    }
}

function Get-QsysState {
    param([Parameter(Mandatory=$true)][string]$Path)

    Require-File -Path $Path
    $Text = [System.IO.File]::ReadAllText($Path)
    if ($Text.Contains($BootstrapMarker)) { return "bootstrap" }
    return "quartus_normalized"
}

function Remove-ExactGeneratedOutputs {
    param(
        [Parameter(Mandatory=$true)][string]$GeneratedDirectory,
        [Parameter(Mandatory=$true)][string]$Sopcinfo,
        [Parameter(Mandatory=$true)][string]$TrustedBoundary
    )

    $GeneratedParent = Split-Path -Parent $GeneratedDirectory
    Assert-NoReparsePointWithinBoundary -Path $GeneratedParent -Boundary $TrustedBoundary
    if (Test-Path -LiteralPath $GeneratedDirectory) {
        $GeneratedItem = Get-Item -LiteralPath $GeneratedDirectory -Force
        if (!$GeneratedItem.PSIsContainer) {
            throw "Expected generated output directory is not a directory: $GeneratedDirectory"
        }
        if (($GeneratedItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing to clean a reparse-point generated directory: $GeneratedDirectory"
        }
        Assert-NoNestedReparsePoints -Directory $GeneratedDirectory
        Remove-Item -LiteralPath $GeneratedDirectory -Recurse -Force
    }

    Assert-NoReparsePointWithinBoundary -Path (Split-Path -Parent $Sopcinfo) -Boundary $TrustedBoundary
    if (Test-Path -LiteralPath $Sopcinfo) {
        $SopcItem = Get-Item -LiteralPath $Sopcinfo -Force
        if ($SopcItem.PSIsContainer) {
            throw "Expected SOPCINFO path is a directory: $Sopcinfo"
        }
        if (($SopcItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing to clean a reparse-point SOPCINFO: $Sopcinfo"
        }
        Remove-Item -LiteralPath $Sopcinfo -Force
    }
}

if ($ValidateOnly -and $ConstructOnly) {
    throw "-ValidateOnly and -ConstructOnly are mutually exclusive"
}
if ($ForceReconstruct -and $ReuseExisting) {
    throw "-ForceReconstruct and -ReuseExisting are mutually exclusive"
}
if ($ReuseExisting -and ($ValidateOnly -or $ConstructOnly)) {
    throw "-ReuseExisting is valid only for the default generation lifecycle"
}
if ($ForceReconstruct -and $ValidateOnly) {
    throw "-ForceReconstruct cannot be combined with -ValidateOnly"
}
if ($ProbeHps -and $ValidateOnly) {
    throw "-ProbeHps cannot be combined with -ValidateOnly"
}
if ($NoWrapperShell) {
    Write-Verbose "-NoWrapperShell is retained for compatibility; this runner never creates wrapper RTL."
}

if (!(Test-Path -LiteralPath $Repo -PathType Container)) {
    throw "Repo does not exist: $Repo"
}
$RepoPath = (Resolve-Path -LiteralPath $Repo).Path
foreach ($RequiredRepoPath in @(
    (Join-Path $RepoPath "Makefile"),
    (Join-Path $RepoPath "platform\de1soc\qsys\platform_designer.tcl"),
    (Join-Path $RepoPath "platform\de1soc\qsys\hps_config.tcl"),
    (Join-Path $RepoPath "platform\de1soc\qsys\system_blueprint.xml"),
    (Join-Path $RepoPath "platform\de1soc\qsys\system.qsys"),
    (Join-Path $RepoPath "scripts\check_hps_platform.py"),
    (Join-Path $RepoPath "scripts\check_address_map.py"),
    (Join-Path $RepoPath "scripts\check_csr_adapter.py"),
    (Join-Path $RepoPath "scripts\check_platform_designer_wrapper.py"),
    (Join-Path $RepoPath "scripts\write_platform_generation_manifest.py")
)) {
    Require-File -Path $RequiredRepoPath
}

$PdTcl = Join-Path $RepoPath "platform\de1soc\qsys\platform_designer.tcl"
$QsysDir = Join-Path $RepoPath "platform\de1soc\qsys"
$QsysFile = Join-Path $QsysDir "system.qsys"
$QsysOut = Join-Path $QsysDir "system"
$Sopcinfo = Join-Path $QsysDir "system.sopcinfo"
$Qip = Join-Path $QsysOut "synthesis\system.qip"
$SystemV = Join-Path $QsysOut "synthesis\system.v"
$SystemSv = Join-Path $QsysOut "synthesis\system.sv"
$HpsCheck = Join-Path $RepoPath "scripts\check_hps_platform.py"
$AddressCheck = Join-Path $RepoPath "scripts\check_address_map.py"
$CsrAdapterCheck = Join-Path $RepoPath "scripts\check_csr_adapter.py"
$PlatformWrapperCheck = Join-Path $RepoPath "scripts\check_platform_designer_wrapper.py"
$ManifestWriter = Join-Path $RepoPath "scripts\write_platform_generation_manifest.py"

$InitialQsysState = Get-QsysState -Path $QsysFile
if ($ReuseExisting -and ($InitialQsysState -eq "bootstrap")) {
    throw "-ReuseExisting requires a Quartus-normalized system.qsys; the working file is still the bootstrap"
}
if ($ConstructOnly -and ($InitialQsysState -eq "quartus_normalized") -and !$ForceReconstruct) {
    throw "-ConstructOnly refuses to replace a normalized system.qsys without explicit -ForceReconstruct"
}

if ($ValidateOnly) {
    $ModeRequested = "validate"
    $ModeEffective = "validate"
    $ConstructionPerformed = "false"
    $DoConstruct = $false
    $DoGenerate = $false
} elseif ($ConstructOnly) {
    $ModeRequested = "construct"
    $ModeEffective = "construct"
    $ConstructionPerformed = "true"
    $DoConstruct = $true
    $DoGenerate = $false
} else {
    $ModeRequested = "auto"
    if ($ReuseExisting) {
        $ModeRequested = "generate"
        $ModeEffective = "generate"
        $DoConstruct = $false
    } elseif ($ForceReconstruct -or ($InitialQsysState -eq "bootstrap")) {
        $ModeEffective = "construct+generate"
        $DoConstruct = $true
    } else {
        $ModeEffective = "generate"
        $DoConstruct = $false
    }
    $ConstructionPerformed = if ($DoConstruct) { "true" } else { "false" }
    $DoGenerate = $true
}

if ([string]::IsNullOrWhiteSpace($QuartusRoot)) {
    if (![string]::IsNullOrWhiteSpace($env:QUARTUS_ROOTDIR)) {
        $QuartusRoot = $env:QUARTUS_ROOTDIR
    } else {
        $QuartusCommand = Get-Command "quartus_sh.exe" -ErrorAction SilentlyContinue
        if ($null -eq $QuartusCommand) {
            throw "Quartus was not found. Pass -QuartusRoot or set QUARTUS_ROOTDIR."
        }
        $QuartusBin = Split-Path -Parent $QuartusCommand.Source
        $QuartusRoot = Split-Path -Parent $QuartusBin
    }
}
$Tools = Resolve-QuartusTools -Root $QuartusRoot -RequireGenerate $DoGenerate
$PythonExe = Resolve-CommandPath -Command $Python

if ([string]::IsNullOrWhiteSpace($RunDir)) {
    $RunId = "{0}-win-{1}-{2}" -f `
        [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ"), `
        $PID, `
        ([Guid]::NewGuid().ToString("N").Substring(0, 8))
    $RunDirPath = Join-Path $RepoPath ("runs\platform\de1soc\qsys\" + $RunId)
} elseif ([System.IO.Path]::IsPathRooted($RunDir)) {
    $RunDirPath = [System.IO.Path]::GetFullPath($RunDir)
} else {
    $RunDirPath = [System.IO.Path]::GetFullPath((Join-Path $RepoPath $RunDir))
}
$QsysOutPrefix = $QsysOut
if (!$QsysOutPrefix.EndsWith([System.IO.Path]::DirectorySeparatorChar.ToString())) {
    $QsysOutPrefix += [System.IO.Path]::DirectorySeparatorChar
}
if ($RunDirPath.Equals($QsysOut, [System.StringComparison]::OrdinalIgnoreCase) -or
    $RunDirPath.StartsWith($QsysOutPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "RunDir cannot be the generated output directory or one of its descendants: $RunDirPath"
}
if (Test-Path -LiteralPath $RunDirPath) {
    throw "RunDir already exists; use a unique directory to avoid stale evidence: $RunDirPath"
}
New-Item -ItemType Directory -Path $RunDirPath | Out-Null

$VersionLog = Join-Path $RunDirPath "quartus_version.log"
$ReadbackTsv = Join-Path $RunDirPath "hps_readback.tsv"
$ManifestFile = Join-Path $RunDirPath "generate_system_manifest.json"

Write-Host "Repo                = $RepoPath"
Write-Host "QuartusRoot         = $($Tools.Root)"
Write-Host "QuartusSh           = $($Tools.QuartusSh)"
Write-Host "QsysScript          = $($Tools.QsysScript)"
$QsysGenerateDisplay = if ($DoGenerate) { $Tools.QsysGenerate } else { "<not-required>" }
Write-Host "QsysGenerate        = $QsysGenerateDisplay"
Write-Host "QsysPackageVersion  = $QsysPackageVersion"
Write-Host "InitialQsysState    = $InitialQsysState"
Write-Host "RunDir              = $RunDirPath"

Run-NativeLogged -Exe $Tools.QuartusSh -Args @("--version") `
    -Log $VersionLog -WorkDir $RepoPath -OutputOnly
$QuartusVersionText = [System.IO.File]::ReadAllText($VersionLog)
if ($QuartusVersionText -notmatch '(?i)\bQuartus\b') {
    throw "quartus_sh --version did not identify Quartus; see $VersionLog"
}
$QuartusIdentityMatch = [regex]::Match($QuartusVersionText,
    '(?im)^\s*(?:Quartus\s+Prime\s+)?Version\s+(?<release>20\.1(?:\.\d+)?)\s+Build\s+\d+\b[^\r\n]*?\b(?<edition>Standard|Lite)\s+Edition\b')
if (!$QuartusIdentityMatch.Success) {
    throw "This flow requires Quartus Prime 20.1.x Standard or Lite Edition; see $VersionLog"
}
$QuartusObservedEdition = if ($QuartusIdentityMatch.Groups['edition'].Value -ieq 'Lite') {
    'Lite Edition'
} else {
    'Standard Edition'
}
Write-Host ("Selected Quartus {0} {1}" -f $QuartusIdentityMatch.Groups['release'].Value, $QuartusObservedEdition)

Run-NativeLogged -Exe $PythonExe -Args @(
    $HpsCheck,
    "--repo-root", $RepoPath
) -Log (Join-Path $RunDirPath "hps_platform_source_check.log") -WorkDir $RepoPath
Run-NativeLogged -Exe $PythonExe -Args @(
    $AddressCheck,
    "--repo-root", $RepoPath
) -Log (Join-Path $RunDirPath "address_map_source_check.log") -WorkDir $RepoPath
Run-NativeLogged -Exe $PythonExe -Args @(
    $CsrAdapterCheck,
    "--repo-root", $RepoPath
) -Log (Join-Path $RunDirPath "csr_adapter_source_check.log") -WorkDir $RepoPath
Run-NativeLogged -Exe $PythonExe -Args @(
    $PlatformWrapperCheck,
    "--repo-root", $RepoPath
) -Log (Join-Path $RunDirPath "platform_wrapper_source_check.log") -WorkDir $RepoPath

if (!$SkipContractChecks) {
    $CheckGenerated = Join-Path $RepoPath "scripts\check_generated.py"
    $GenerateFilelists = Join-Path $RepoPath "scripts\gen_filelists.py"
    if (Test-Path -LiteralPath $CheckGenerated -PathType Leaf) {
        Run-NativeLogged -Exe $PythonExe -Args @($CheckGenerated, "--quiet") `
            -Log (Join-Path $RunDirPath "check_generated.log") -WorkDir $RepoPath
    }
    if (Test-Path -LiteralPath $GenerateFilelists -PathType Leaf) {
        Run-NativeLogged -Exe $PythonExe -Args @($GenerateFilelists, "--check", "--quiet") `
            -Log (Join-Path $RunDirPath "gen_filelists.log") -WorkDir $RepoPath
    }
}

Run-QsysScriptLogged -Exe $Tools.QsysScript -PackageVersion $QsysPackageVersion `
    -Script $PdTcl -PythonExe $PythonExe -TclArgs @(
        "--mode", "validate",
        "--repo-root", $RepoPath,
        "--print-summary"
    ) -Log (Join-Path $RunDirPath "qsys_validate.log") -WorkDir $RepoPath

Write-Host "ModeRequested       = $ModeRequested"
Write-Host "ModeEffective       = $ModeEffective"

if (!$ValidateOnly) {
    Run-QsysScriptLogged -Exe $Tools.QsysScript -PackageVersion $QsysPackageVersion `
        -Script $PdTcl -PythonExe $PythonExe -TclArgs @(
            "--mode", "emit-configs",
            "--repo-root", $RepoPath,
            "--emit-all-manifests"
        ) -Log (Join-Path $RunDirPath "qsys_emit_configs.log") -WorkDir $RepoPath
}

if ($ProbeHps) {
    Run-QsysScriptLogged -Exe $Tools.QsysScript -PackageVersion $QsysPackageVersion `
        -Script $PdTcl -PythonExe $PythonExe -TclArgs @(
            "--mode", "probe-hps",
            "--repo-root", $RepoPath
        ) -Log (Join-Path $RunDirPath "qsys_probe_hps.log") -WorkDir $RepoPath
}

if ($DoConstruct) {
    $ConstructArgs = @(
        "--mode", "construct",
        "--repo-root", $RepoPath,
        "--strict-exports",
        "--readback-output", $ReadbackTsv,
        "--emit-all-manifests",
        "--print-summary"
    )
    if ($ForceReconstruct) { $ConstructArgs += "--force" }
    Run-QsysScriptLogged -Exe $Tools.QsysScript -PackageVersion $QsysPackageVersion `
        -Script $PdTcl -PythonExe $PythonExe -TclArgs $ConstructArgs `
        -Log (Join-Path $RunDirPath "qsys_construct.log") -WorkDir $RepoPath

    if ((Get-QsysState -Path $QsysFile) -ne "quartus_normalized") {
        throw "qsys-script construct completed without producing a normalized system.qsys"
    }
    Require-File -Path $ReadbackTsv
}

if ($DoGenerate) {
    if ((Get-QsysState -Path $QsysFile) -ne "quartus_normalized") {
        throw "Generation requires a Quartus-normalized system.qsys"
    }

    # A just-constructed graph already emitted the readback capture. Reuse mode
    # must load the normalized graph read-only before qsys-generate.
    if (!$DoConstruct) {
        Run-QsysScriptLogged -Exe $Tools.QsysScript -PackageVersion $QsysPackageVersion `
            -Script $PdTcl -PythonExe $PythonExe -TclArgs @(
                "--mode", "capture-readback",
                "--repo-root", $RepoPath,
                "--readback-output", $ReadbackTsv
            ) -Log (Join-Path $RunDirPath "qsys_readback.log") -WorkDir $RepoPath
        Require-File -Path $ReadbackTsv
    }

    $PreGenerationFingerprints = @{}
    foreach ($ArtifactPath in @($Sopcinfo, $Qip, $SystemV, $SystemSv)) {
        $PreGenerationFingerprints[$ArtifactPath] = Get-ArtifactFingerprint -Path $ArtifactPath
    }
    if (!$KeepGenerated) {
        Write-Host "Cleaning exact generated paths:"
        Write-Host "  $QsysOut"
        Write-Host "  $Sopcinfo"
        Remove-ExactGeneratedOutputs -GeneratedDirectory $QsysOut -Sopcinfo $Sopcinfo `
            -TrustedBoundary $RepoPath
    }

    $GenerationStartedUtc = [DateTime]::UtcNow
    Run-NativeLogged -Exe $Tools.QsysGenerate -Args @(
        $QsysFile,
        "--synthesis=VERILOG",
        "--output-directory=$QsysOut"
    ) -Log (Join-Path $RunDirPath "qsys_generate.log") -WorkDir $RepoPath

    Require-FreshGeneratedFile -Path $Sopcinfo -GenerationStartedUtc $GenerationStartedUtc `
        -PreviousFingerprint ($PreGenerationFingerprints[$Sopcinfo])
    Require-FreshGeneratedFile -Path $Qip -GenerationStartedUtc $GenerationStartedUtc `
        -PreviousFingerprint ($PreGenerationFingerprints[$Qip])
    $GeneratedHdlCandidates = @()
    foreach ($HdlPath in @($SystemV, $SystemSv)) {
        if (Test-Path -LiteralPath $HdlPath -PathType Leaf) {
            Require-FreshGeneratedFile -Path $HdlPath -GenerationStartedUtc $GenerationStartedUtc `
                -PreviousFingerprint ($PreGenerationFingerprints[$HdlPath])
            $GeneratedHdlCandidates += $HdlPath
        }
    }
    if ($GeneratedHdlCandidates.Count -eq 0) {
        throw "Mandatory generated HDL is missing; expected one of $SystemV or $SystemSv"
    }
    $GeneratedHdl = $GeneratedHdlCandidates[0]
    Run-NativeLogged -Exe $PythonExe -Args @(
        $AddressCheck,
        "--repo-root", $RepoPath,
        "--require-sopcinfo"
    ) -Log (Join-Path $RunDirPath "address_map_hardware_evidence_check.log") -WorkDir $RepoPath
    Run-NativeLogged -Exe $PythonExe -Args @(
        $PlatformWrapperCheck,
        "--repo-root", $RepoPath,
        "--require-generated"
    ) -Log (Join-Path $RunDirPath "platform_wrapper_generated_abi_check.log") -WorkDir $RepoPath
}

$ManifestArgs = @(
    $ManifestWriter,
    "--repo-root", $RepoPath,
    "--output", $ManifestFile,
    "--mode-requested", $ModeRequested,
    "--mode-effective", $ModeEffective,
    "--construction-performed", $ConstructionPerformed,
    "--qsys-script", $Tools.QsysScript,
    "--qsys-generate", $QsysGenerateDisplay,
    "--quartus-version-file", $VersionLog
)
if (Test-Path -LiteralPath $ReadbackTsv -PathType Leaf) {
    $ManifestArgs += @("--readback-tsv", $ReadbackTsv)
}
if ($DoGenerate) { $ManifestArgs += "--require-generated" }
Run-NativeLogged -Exe $PythonExe -Args $ManifestArgs `
    -Log (Join-Path $RunDirPath "manifest_writer.log") -WorkDir $RepoPath
Require-File -Path $ManifestFile
Assert-GenerationManifest -Path $ManifestFile -Root $RepoPath `
    -ExpectedModeRequested $ModeRequested -ExpectedModeEffective $ModeEffective `
    -ExpectedConstructionPerformed $ConstructionPerformed `
    -ExpectedQsysGenerate $QsysGenerateDisplay -RequireGenerated $DoGenerate `
    -RequireReadback ($DoConstruct -or $DoGenerate)

Write-Host ""
Write-Host "Platform Designer lifecycle completed: $ModeEffective"
Write-Host "Run manifest        = $ManifestFile"
Write-Host "Quartus version log = $VersionLog"
if (Test-Path -LiteralPath $ReadbackTsv -PathType Leaf) {
    Write-Host "HPS readback TSV    = $ReadbackTsv"
}
if ($DoGenerate) {
    Write-Host "system.sopcinfo     = $Sopcinfo"
    Write-Host "system.qip          = $Qip"
    Write-Host "system HDL          = $GeneratedHdl"
}
Write-Host "NOTE: This runner does not create or edit wrapper RTL."
