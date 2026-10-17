$ErrorActionPreference = 'Stop'
$src = $PSScriptRoot
$root = (Resolve-Path (Join-Path $src '../../..')).Path
$out = Join-Path $root 'outputs/trecap_laptop_fpga_v01/cpu_build01'
if (Test-Path -LiteralPath $out) { throw 'Fresh build required' }
New-Item -ItemType Directory -Path $out | Out-Null
$vc = 'C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat'
$command = 'call "'+$vc+'" > environment.log 2>&1 && cl /nologo /std:c++20 /O2 /EHsc /DNOMINMAX /W3 "'+$src+'/campaign.cpp" /Fe:campaign.exe /Fo:campaign.obj > campaign_build.log 2>&1 && cl /nologo /std:c++20 /O2 /EHsc /DNOMINMAX /W3 /LD "'+$src+'/dll.cpp" /Fe:trecap.dll /Fo:dll.obj > dll_build.log 2>&1'
Push-Location $out
try {
 $command | Set-Content -LiteralPath build_command.txt
 & cmd.exe /d /s /c $command
 if ($LASTEXITCODE -ne 0) { throw ('Compiler failed: '+$LASTEXITCODE) }
 & './campaign.exe' (Join-Path $root 'outputs/trecap_stream8_v01/fixtures02') 1> campaign.jsonl 2> campaign.stderr
 if ($LASTEXITCODE -ne 0) { throw ('Campaign failed: '+$LASTEXITCODE) }
 'PASS_BUILD_AND_NATIVE_CAMPAIGN' | Set-Content status.txt
} finally { Pop-Location }
