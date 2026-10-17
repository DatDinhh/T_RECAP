$ErrorActionPreference = 'Stop'
$src = $PSScriptRoot
$root = (Resolve-Path (Join-Path $src '../../..')).Path
$out = Join-Path $src 'build01'
if (Test-Path -LiteralPath $out) { throw 'Fresh build required' }
New-Item -ItemType Directory -Path $out | Out-Null
$vc = 'C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat'
$codec = Join-Path $root 'work/trecap_downstream8_v01/native'
$command = 'call "'+$vc+'" > environment.log 2>&1 && cl /nologo /std:c++20 /O2 /EHsc /DNOMINMAX /W4 /GL- /LD "'+$src+'/dll.cpp" "'+$codec+'/codec.cpp" "'+$codec+'/consumer.cpp" /Fe:trecap_scheduler.dll /link /LTCG:OFF > build.log 2>&1'
Push-Location $out
try {
 $command | Set-Content -LiteralPath build_command.txt
 & cmd.exe /d /s /c $command
 if ($LASTEXITCODE -ne 0) { throw ('Compiler failed: '+$LASTEXITCODE) }
 'PASS_BUILD_ONLY' | Set-Content -LiteralPath status.txt
} finally { Pop-Location }
