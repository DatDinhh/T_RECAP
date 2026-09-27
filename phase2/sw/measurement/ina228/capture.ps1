#requires -Version 5.1
<#
.SYNOPSIS
Capture INA228 CircuitPython output from a plain Adafruit Feather RP2040.
.EXAMPLE
.\capture.ps1 -Port COM7 -OutputDirectory .\captures -Seconds 10 -Restart
.NOTES
Close other serial consoles first. -Restart interrupts code.py and soft reboots
CircuitPython, resetting its measurement session. No Python packages are needed.
The raw log preserves received bytes, including ANSI escapes and line endings.
Metadata JSONL contains the JSON payload from each '# { ... }' serial line.
CSV sessions never share a file. Attaching midstream uses the expected schema
until the next device header; use -Restart to capture startup configuration.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^COM[1-9][0-9]*$')]
    [string]$Port,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$OutputDirectory,

    [ValidateRange(1, 86400)]
    [int]$Seconds = 10,

    [switch]$Restart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$culture = [System.Globalization.CultureInfo]::InvariantCulture
$numberStyle = [System.Globalization.NumberStyles]::Float
$header = 'seq,t_start_s,t_end_s,bus_voltage_V,shunt_voltage_V,current_A,power_W,energy_J,energy_since_start_J,math_overflow,energy_overflow,memory_ok,conversion_ready,math_overflow_latched,energy_overflow_latched,memory_error_latched,accumulation_valid'
$columns = $header.Split(',')
$state = @{
    Serial = $null; Raw = $null; Metadata = $null; Csv = $null
    RawPath = $null; MetadataPath = $null; Prefix = $null; DeviceId = $null
    Sessions = [System.Collections.Generic.List[object]]::new()
    Rows = 0; MetadataLines = 0; IgnoredLines = 0; RawBytes = 0
    PartialLineDiscarded = $false; LastSequence = $null; Error = $null
    Pending = [System.Text.StringBuilder]::new()
    Decoder = [System.Text.Encoding]::UTF8.GetDecoder()
    Buffer = [byte[]]::new(4096); Chars = [char[]]::new(8192)
}
$startedUtc = [DateTime]::UtcNow.ToString('o', $culture)
$captureClock = [System.Diagnostics.Stopwatch]::new()

function Get-VerifiedDevice {
    $devices = @(Get-CimInstance -ClassName Win32_SerialPort -OperationTimeoutSec 3 |
        Where-Object { $_.DeviceID -ieq $Port })
    if ($devices.Count -ne 1) {
        throw "Expected one connected Win32_SerialPort for $Port; found $($devices.Count)."
    }
    if ([string]$devices[0].PNPDeviceID -notmatch '(?i)VID_239A&PID_80F2(?:&|\\|$)') {
        throw "$Port is not the expected plain Feather RP2040 (VID_239A&PID_80F2)."
    }
    return $devices[0]
}

function New-ExclusiveWriter([string]$Path) {
    $stream = [System.IO.FileStream]::new(
        $Path, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::Read)
    try {
        $writer = [System.IO.StreamWriter]::new($stream, [System.Text.UTF8Encoding]::new($false))
        $writer.NewLine = "`n"
        $writer.AutoFlush = $true
        return $writer
    }
    catch {
        $stream.Dispose()
        throw
    }
}

function Start-CsvSession([string]$HeaderSource) {
    if ($null -ne $state.Csv) { $state.Csv.Dispose(); $state.Csv = $null }
    $index = $state.Sessions.Count + 1
    $csvPath = '{0}.session-{1:D3}.csv' -f $state.Prefix, $index
    $state.Csv = New-ExclusiveWriter $csvPath
    $state.Csv.WriteLine($header)
    $state.LastSequence = $null
    $state.Sessions.Add([pscustomobject]@{
        session = $index; csv = $csvPath; header_source = $HeaderSource; rows = 0
    })
}

function Receive-Line([string]$RawLine) {
    # Strip OSC, CSI and short ESC sequences only from the parsing copy.
    $line = [regex]::Replace($RawLine, '\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)', '')
    $line = [regex]::Replace($line, '\x1B\[[0-?]*[ -/]*[@-~]', '')
    $line = [regex]::Replace($line, '\x1B[@-_]', '').Trim()
    if ($line.Length -eq 0) { return }
    if ($line.StartsWith('#')) {
        $payload = $line.Substring(1).Trim()
        if ($payload.StartsWith('{')) {
            # Preserve malformed metadata too, then report it as a capture error.
            $state.Metadata.WriteLine($payload)
            $state.MetadataLines++
            $null = ConvertFrom-Json -InputObject $payload -ErrorAction Stop
        }
        else { $state.IgnoredLines++ }
        return
    }
    if ($line.StartsWith('seq,')) {
        if ($line -cne $header) { throw "Unexpected CSV schema: $line" }
        Start-CsvSession 'device'
        return
    }
    # CircuitPython banners/prompts are allowed. Anything resembling a data row
    # must pass validation, including rows with an invalid first field.
    if (-not $line.Contains(',') -and $line -notmatch '^[+-]?[0-9]') {
        $state.IgnoredLines++
        return
    }
    $fields = $line.Split(',')
    if ($fields.Count -ne $columns.Count) {
        throw "Malformed CSV row: expected $($columns.Count) columns, got $($fields.Count): $line"
    }
    [UInt64]$sequence = 0
    if (-not [UInt64]::TryParse($fields[0], [System.Globalization.NumberStyles]::None,
            $culture, [ref]$sequence)) {
        throw "Invalid unsigned integer seq in CSV row: $line"
    }
    for ($i = 1; $i -lt $fields.Count; $i++) {
        [double]$value = 0
        if (-not [double]::TryParse($fields[$i], $numberStyle, $culture, [ref]$value) -or
            [double]::IsNaN($value) -or [double]::IsInfinity($value)) {
            throw "Invalid finite numeric value in column '$($columns[$i])': $line"
        }
        if ($i -ge 9 -and $fields[$i] -notmatch '^[01]$') {
            throw "Expected numeric 0/1 in column '$($columns[$i])': $line"
        }
    }
    if ($null -eq $state.Csv) { Start-CsvSession 'expected_schema' }
    if ($null -ne $state.LastSequence -and $sequence -le $state.LastSequence) {
        throw "CSV sequence reset or repeated without a new session header: $line"
    }
    $state.Csv.WriteLine($line)
    $state.LastSequence = $sequence
    $state.Rows++
    $state.Sessions[$state.Sessions.Count - 1].rows++
}

function Read-SerialBlock([switch]$Parse) {
    try { $count = $state.Serial.Read($state.Buffer, 0, $state.Buffer.Length) }
    catch [System.TimeoutException] { return }
    if ($count -le 0) { throw 'Serial port closed or disconnected during capture.' }
    $state.Raw.Write($state.Buffer, 0, $count)
    $state.RawBytes += $count
    if (-not $Parse) { return }
    $charCount = $state.Decoder.GetChars($state.Buffer, 0, $count, $state.Chars, 0)
    [void]$state.Pending.Append($state.Chars, 0, $charCount)
    $pendingText = $state.Pending.ToString()
    $offset = 0
    while (($newline = $pendingText.IndexOf("`n", $offset)) -ge 0) {
        Receive-Line $pendingText.Substring($offset, $newline - $offset).TrimEnd([char]13)
        $offset = $newline + 1
    }
    if ($offset -gt 0) { [void]$state.Pending.Remove(0, $offset) }
    if ($state.Pending.Length -gt 65536) { throw 'Serial line exceeded 65536 characters without a newline.' }
}

try {
    # Device identity is checked before opening the port or sending control bytes.
    $device = Get-VerifiedDevice
    $state.DeviceId = [string]$device.PNPDeviceID
    $directory = [System.IO.Path]::GetFullPath($OutputDirectory)
    [void][System.IO.Directory]::CreateDirectory($directory)
    $unique = 'ina228_{0}_{1}' -f [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ', $culture), [Guid]::NewGuid().ToString('N')
    $state.Prefix = Join-Path $directory $unique
    $state.RawPath = $state.Prefix + '.raw.log'
    $state.MetadataPath = $state.Prefix + '.metadata.jsonl'
    $state.Raw = [System.IO.FileStream]::new($state.RawPath,
        [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
    $state.Metadata = New-ExclusiveWriter $state.MetadataPath
    $state.Serial = [System.IO.Ports.SerialPort]::new($Port.ToUpperInvariant(), 115200,
        [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One)
    $state.Serial.Handshake = [System.IO.Ports.Handshake]::None
    $state.Serial.DtrEnable = $true
    $state.Serial.RtsEnable = $false
    $state.Serial.ReadTimeout = 200
    $state.Serial.WriteTimeout = 500
    $state.Serial.Open()
    if ($Restart) {
        $state.Serial.Write([byte[]]@(3), 0, 1)
        Start-Sleep -Milliseconds 50
        $state.Serial.Write([byte[]]@(3), 0, 1)
        $drainClock = [System.Diagnostics.Stopwatch]::StartNew()
        while ($drainClock.ElapsedMilliseconds -lt 400) { Read-SerialBlock }
        $state.Serial.Write([byte[]]@(4), 0, 1)
    }
    $captureClock.Start()
    while ($captureClock.Elapsed.TotalSeconds -lt $Seconds) {
        $remainingMs = [int][Math]::Ceiling(($Seconds * 1000) - $captureClock.Elapsed.TotalMilliseconds)
        $state.Serial.ReadTimeout = [Math]::Max(1, [Math]::Min(200, $remainingMs))
        Read-SerialBlock -Parse
    }
    # A bounded capture can end in the middle of a line. Keep it in the raw log;
    # only complete newline-terminated rows enter the validated CSV files.
    $state.PartialLineDiscarded = $state.Pending.Length -gt 0
    $finalDevice = Get-VerifiedDevice
    if ([string]$finalDevice.PNPDeviceID -cne $state.DeviceId) {
        throw 'USB device identity changed during capture.'
    }
    if ($state.Rows -eq 0) { throw 'Capture received no valid numeric rows.' }
}
catch { $state.Error = $_.Exception.Message }
finally {
    $captureClock.Stop()
    foreach ($resource in @($state.Serial, $state.Csv, $state.Metadata, $state.Raw)) {
        if ($null -ne $resource) {
            try { $resource.Dispose() }
            catch { if ($null -eq $state.Error) { $state.Error = $_.Exception.Message } }
        }
    }
}

[pscustomobject]@{
    ok = ($null -eq $state.Error)
    error = $state.Error
    port = $Port.ToUpperInvariant()
    pnp_device_id = $state.DeviceId
    restart = [bool]$Restart
    started_utc = $startedUtc
    requested_seconds = $Seconds
    elapsed_seconds = [Math]::Round($captureClock.Elapsed.TotalSeconds, 3)
    rows = $state.Rows
    raw_bytes = $state.RawBytes
    metadata_lines = $state.MetadataLines
    ignored_console_lines = $state.IgnoredLines
    partial_line_kept_only_in_raw = $state.PartialLineDiscarded
    raw_log = $state.RawPath
    metadata_jsonl = $state.MetadataPath
    sessions = @($state.Sessions.ToArray())
} | ConvertTo-Json -Depth 5
if ($null -ne $state.Error) { exit 1 }
exit 0
