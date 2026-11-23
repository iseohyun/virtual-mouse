<#
.SYNOPSIS
    DFU 모드로 진입한 Arduino Uno R3 (ATmega16U2)를 순정 USB-Serial 펌웨어로 복구합니다.
#>
$ErrorActionPreference = "Stop"

$dfu = Join-Path $PSScriptRoot "..\tools\dfu-programmer\dfu-programmer.exe"
$hex = Join-Path $PSScriptRoot "..\firmware_bins\Arduino-Uno-R3-Stock-16u2.hex"

if (-not (Test-Path $dfu)) { throw "dfu-programmer.exe not found. Run scripts/setup.ps1 first." }
if (-not (Test-Path $hex)) { throw "Stock Uno hex not found. Run scripts/setup.ps1 first." }

Write-Host "1) Erasing ATmega16U2..." -ForegroundColor Cyan
& $dfu atmega16u2 erase --force
if ($LASTEXITCODE -ne 0) { throw "Erase failed (exit code $LASTEXITCODE)" }

Write-Host "2) Flashing Arduino-Uno-R3-Stock-16u2.hex..." -ForegroundColor Cyan
& $dfu atmega16u2 flash --suppress-bootloader-mem $hex
if ($LASTEXITCODE -ne 0) { throw "Flash failed (exit code $LASTEXITCODE)" }

Write-Host "3) Resetting ATmega16U2..." -ForegroundColor Cyan
& $dfu atmega16u2 reset
if ($LASTEXITCODE -ne 0) { throw "Reset failed (exit code $LASTEXITCODE)" }

Write-Host "`nRestored to stock Arduino Uno R3! Unplug and replug the USB cable." -ForegroundColor Green
