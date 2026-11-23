<#
.SYNOPSIS
    현재 펌웨어를 컴파일하고 GitHub Release 배포용 .hex 파일과
    SHA-256 해시가 포함된 latest.json 매니페스트를 생성합니다.
.DESCRIPTION
    펌웨어 버전은 앱 릴리즈 태그(v1.1.x)와 따로 관리합니다.
    버전의 원본은 firmware\uno_16u2_mouse\uno_16u2_mouse.ino 의 FW_VERSION 이며,
    host\device_status.py 의 EXPECTED_FW_VERSION 과 다르면 빌드를 멈춥니다.
    (장치가 보고하는 VER 값과 매니페스트 버전이 어긋나면 업데이트가 끝없이 반복되기 때문)
#>
param(
    [string]$BaseUrl = "https://github.com/iseohyun/virtual-mouse/releases/latest/download",
    [string]$Notes = "HID Mouse + Keyboard MultiReport, VER, software BOOT DFU"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$inoText = Get-Content -Raw -Encoding UTF8 "firmware\uno_16u2_mouse\uno_16u2_mouse.ino"
if ($inoText -notmatch '#define\s+FW_VERSION\s+"([0-9]+\.[0-9]+\.[0-9]+)"') { throw "FW_VERSION not found in firmware .ino" }
$Version = $Matches[1]
$pyText = Get-Content -Raw -Encoding UTF8 "host\device_status.py"
if ($pyText -notmatch 'EXPECTED_FW_VERSION\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"') { throw "EXPECTED_FW_VERSION not found in host\device_status.py" }
if ($Matches[1] -ne $Version) {
    throw "Firmware version mismatch: .ino FW_VERSION=$Version, device_status.py EXPECTED_FW_VERSION=$($Matches[1])"
}

$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
$gccBin = (Get-Item "$env:LOCALAPPDATA\Arduino15\packages\arduino\tools\avr-gcc\7.3.0*\bin" | Select-Object -First 1).FullName -replace '\\','/'

Write-Host "1) Compiling firmware v$Version..." -ForegroundColor Cyan
arduino-cli compile `
  --fqbn HoodLoader2:avr:HoodLoader2atmega16u2 `
  --build-property "compiler.path=$gccBin/" `
  --output-dir build\uno_16u2_mouse `
  firmware\uno_16u2_mouse
if ($LASTEXITCODE -ne 0) { throw "Firmware compile failed." }

$outDir = Join-Path $RepoRoot "dist\releases"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$hexName = "uno_16u2_mouse_$Version.hex"
$srcHex = Join-Path $RepoRoot "build\uno_16u2_mouse\uno_16u2_mouse.ino.hex"
$dstHex = Join-Path $outDir $hexName
Copy-Item $srcHex $dstHex -Force

$sha = (Get-FileHash -Path $dstHex -Algorithm SHA256).Hash.ToLower()
$manifest = [ordered]@{
    firmware_version = $Version
    firmware_url     = "$($BaseUrl.TrimEnd('/'))/$hexName"
    sha256           = $sha
    notes            = $Notes
}

$manifestPath = Join-Path $outDir "latest.json"
$jsonText = $manifest | ConvertTo-Json -Depth 3
[System.IO.File]::WriteAllText($manifestPath, $jsonText, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "`nRelease artifacts generated in dist\releases:" -ForegroundColor Green
Write-Host "  - $dstHex"
Write-Host "  - $manifestPath (SHA-256: $sha)"
