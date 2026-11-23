<#
.SYNOPSIS
    새 PC 또는 새 Arduino Uno R3를 USB HID 마우스+키보드로 한 번에 자동 세팅(프로비저닝)합니다.
.DESCRIPTION
    1. 관리자 권한 확인 (필요 시 UAC 승격)
    2. 필요한 도구/코어/라이브러리 자동 점검 (scripts/setup.ps1)
    3. DFU 모드(VID_03EB&PID_2FEF) 자동 감지 (미감지 시 점퍼 리셋 대기)
    4. WinUSB 드라이버 미설치 시 wdi-simple.exe 또는 Zadig로 설치
    5. USB HID 마우스+키보드 펌웨어 컴파일 및 DFU 직접 플래싱
    6. USB 재연결 후 VID_2341&PID_484C 장치 인식 확인
#>
param(
    [switch]$SkipSetup
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Requesting Administrator privileges (UAC)..." -ForegroundColor Yellow
    $argList = @("-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    if ($SkipSetup) { $argList += "-SkipSetup" }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $argList
    exit 0
}

if (-not $SkipSetup) {
    Write-Host "[Step 1/5] Checking dependencies..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "setup.ps1")
}

Write-Host "[Step 2/5] Waiting for Arduino Uno R3 in DFU mode (VID_03EB&PID_2FEF)..." -ForegroundColor Cyan
Write-Host "           -> USB 포트 옆 6핀 헤더 중 USB쪽 2핀(RESET-GND)을 점퍼선으로 1초간 접촉했다 떼세요." -ForegroundColor Gray
$dfuDev = $null
while (-not $dfuDev) {
    $dfuDev = Get-CimInstance Win32_PnPEntity | Where-Object { $_.DeviceID -match 'VID_03EB&PID_2FEF' } | Select-Object -First 1
    if (-not $dfuDev) { Start-Sleep -Seconds 1 }
}
Write-Host "           Detected DFU device: $($dfuDev.DeviceID) (Service: $($dfuDev.Service))" -ForegroundColor Green

if ($dfuDev.Service -ne "WinUSB" -or $dfuDev.Status -ne "OK") {
    Write-Host "[Step 3/5] Installing WinUSB driver for ATmega16U2 DFU..." -ForegroundColor Cyan
    $wdiSimple = Join-Path $RepoRoot "tools\wdi-simple.exe"
    if (Test-Path $wdiSimple) {
        & $wdiSimple --vid 0x03EB --pid 0x2FEF --type 0 --name "ATmega16U2 DFU"
    } else {
        Write-Host "           Launching Zadig: Select Unknown Device #1 (03EB:2FEF) -> WinUSB -> Install Driver." -ForegroundColor Yellow
        Start-Process (Join-Path $RepoRoot "tools\zadig.exe") -Wait
    }
} else {
    Write-Host "[Step 3/5] WinUSB driver already installed." -ForegroundColor Green
}

Write-Host "[Step 4/5] Compiling & flashing USB HID Mouse+Keyboard firmware..." -ForegroundColor Cyan
& (Join-Path $PSScriptRoot "flash_mouse_firmware.ps1")

Write-Host "[Step 5/5] Waiting for VirtualMouse USB HID device (USB 케이블을 뺐다가 다시 꽂아주세요)..." -ForegroundColor Cyan
$port = $null
while (-not $port) {
    $pnp = Get-CimInstance Win32_PnPEntity | Where-Object {
        $_.DeviceID -match 'VID_2341&PID_484C' -and $_.Name -match '\((COM\d+)\)'
    } | Select-Object -First 1
    if ($pnp -and $pnp.Name -match '\((COM\d+)\)') {
        $port = $Matches[1]
    } else {
        Start-Sleep -Seconds 1
    }
}

Write-Host "`nAll done! Your Arduino Uno R3 is now a physical USB HID Mouse + Keyboard on $port." -ForegroundColor Green
