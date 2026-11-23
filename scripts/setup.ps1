<#
.SYNOPSIS
    VirtualMouse 프로젝트의 외부 도구, Arduino 코어/라이브러리, 펌웨어 바이너리, Python 가상환경을 일괄 설치합니다.
.DESCRIPTION
    Git 저장소를 새로 클론한 PC에서 한 번 실행하면 개발 및 플래싱에 필요한 모든 사전 준비가 완료됩니다.
#>
$ErrorActionPreference = "Stop"

Write-Host "[1/4] Checking arduino-cli..." -ForegroundColor Cyan
if (-not (Get-Command arduino-cli -ErrorAction SilentlyContinue)) {
    winget install --id ArduinoSA.CLI --exact --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}

Write-Host "[2/4] Configuring Arduino AVR, HoodLoader2 core and HID-Project library..." -ForegroundColor Cyan
arduino-cli config init --overwrite | Out-Null
arduino-cli config add board_manager.additional_urls https://raw.githubusercontent.com/NicoHood/HoodLoader2/master/package_NicoHood_HoodLoader2_index.json
arduino-cli core update-index
arduino-cli core install arduino:avr
arduino-cli core install HoodLoader2:avr
arduino-cli lib install "HID-Project"

Write-Host "[3/4] Downloading dfu-programmer, Zadig, and firmware .hex files..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path tools, firmware_bins | Out-Null

if (-not (Test-Path "tools\dfu-programmer\dfu-programmer.exe")) {
    $dfuZip = "tools\dfu-programmer-x64-1.1.0.zip"
    Invoke-WebRequest -Uri "https://github.com/dfu-programmer/dfu-programmer/releases/download/v1.1.0/dfu-programmer-x64-1.1.0.zip" -OutFile $dfuZip
    Expand-Archive -Path $dfuZip -DestinationPath "tools\dfu-programmer" -Force
    Remove-Item $dfuZip -Force
}

if (-not (Test-Path "tools\zadig.exe")) {
    $zadigRel = Invoke-RestMethod -Uri "https://api.github.com/repos/pbatard/libwdi/releases/latest" -Headers @{"User-Agent"="VirtualMouseSetup"}
    $zadigAsset = $zadigRel.assets | Where-Object { $_.name -match "^zadig-.*\.exe$" } | Select-Object -First 1
    if ($zadigAsset) {
        Invoke-WebRequest -Uri $zadigAsset.browser_download_url -OutFile "tools\zadig.exe"
    }
}

if (-not (Test-Path "firmware_bins\HoodLoader2_0_5_Uno_atmega16u2.hex")) {
    Invoke-WebRequest -Uri "https://raw.githubusercontent.com/NicoHood/HoodLoader2/master/avr/bootloaders/HexFiles/HoodLoader2_0_5_Uno_atmega16u2.hex" -OutFile "firmware_bins\HoodLoader2_0_5_Uno_atmega16u2.hex"
}

if (-not (Test-Path "firmware_bins\Arduino-Uno-R3-Stock-16u2.hex")) {
    Invoke-WebRequest -Uri "https://raw.githubusercontent.com/arduino/ArduinoCore-avr/master/firmwares/atmegaxxu2/Arduino-COMBINED-dfu-usbserial-atmega16u2-Uno-Rev3.hex" -OutFile "firmware_bins\Arduino-Uno-R3-Stock-16u2.hex"
}

Write-Host "[4/4] Setting up Python virtual environment..." -ForegroundColor Cyan
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r host\requirements.txt

Write-Host "`nSetup complete!" -ForegroundColor Green
