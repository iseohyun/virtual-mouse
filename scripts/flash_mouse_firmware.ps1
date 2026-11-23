<#
.SYNOPSIS
    Uno R3 (ATmega16U2)용 USB HID 마우스 펌웨어를 컴파일하고 DFU 모드로 직접 플래싱합니다.
#>
$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
$gccBin = (Get-Item "$env:LOCALAPPDATA\Arduino15\packages\arduino\tools\avr-gcc\7.3.0*\bin" | Select-Object -First 1).FullName -replace '\\','/'
$dfu = Join-Path $RepoRoot "tools\dfu-programmer\dfu-programmer.exe"
$hex = Join-Path $RepoRoot "build\uno_16u2_mouse\uno_16u2_mouse.ino.hex"

Write-Host "1) Compiling HID mouse firmware (HoodLoader2 16u2)..." -ForegroundColor Cyan
arduino-cli compile `
  --fqbn HoodLoader2:avr:HoodLoader2atmega16u2 `
  --build-property "compiler.path=$gccBin/" `
  --output-dir build\uno_16u2_mouse `
  firmware\uno_16u2_mouse
if ($LASTEXITCODE -ne 0) { throw "Firmware compile failed." }

Write-Host "2) Erasing ATmega16U2..." -ForegroundColor Cyan
& $dfu atmega16u2 erase --force
if ($LASTEXITCODE -ne 0) { throw "Erase failed." }

Write-Host "3) Flashing $hex..." -ForegroundColor Cyan
& $dfu atmega16u2 flash $hex
if ($LASTEXITCODE -ne 0) { throw "Flash failed." }

Write-Host "4) Launching..." -ForegroundColor Cyan
& $dfu atmega16u2 launch

Write-Host "`nDone! Unplug and replug your Arduino Uno USB cable to start the USB HID Mouse." -ForegroundColor Green
