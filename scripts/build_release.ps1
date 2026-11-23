<#
.SYNOPSIS
    현재 펌웨어를 컴파일하고 원격 서버(virtual-mouse.iseohyun.com/releases/) 배포용
    .hex 파일과 SHA-256 해시가 포함된 latest.json 매니페스트를 생성합니다.
#>
param(
    [string]$Version = "1.1.0",
    [string]$BaseUrl = "https://virtual-mouse.iseohyun.com/releases",
    [string]$Notes = "HID Mouse + Keyboard MultiReport, VER, software BOOT DFU"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

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
