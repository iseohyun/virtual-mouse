<#
.SYNOPSIS
    VirtualMouse 프로젝트의 외부 도구, Arduino 코어/라이브러리, 펌웨어 바이너리, Python 가상환경을 일괄 설치합니다.
.DESCRIPTION
    Git 저장소를 새로 클론한 PC에서 한 번 실행하면 개발 및 플래싱에 필요한 모든 사전 준비가 완료됩니다.
    외부에서 받는 것은 모두 버전(또는 커밋)을 고정하고, 파일은 SHA-256을 검사합니다. 값이 다르면 설치를 멈춥니다.
    버전을 올릴 때는 아래 고정 값(주소와 해시)을 함께 바꾸고, .github/workflows/release.yml 의 같은 값도 맞춥니다.
    외부 명령(winget, arduino-cli, python, pip)이 실패하면 그 자리에서 멈춥니다.
    사용자 전역 arduino-cli 설정은 바꾸지 않습니다 (보드 인덱스 주소는 명령마다 --additional-urls 로 넘김).
#>
$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

# --- 고정 값 (release.yml 과 같아야 함) ---
$ArduinoCliVersion = "1.6.0"
$ArduinoAvrCore = "arduino:avr@1.8.8"
$HoodLoader2Core = "HoodLoader2:avr@2.0.5"
$HidProjectLib = "HID-Project@2.8.4"
$HoodLoader2Commit = "0c1c4bbf338383cb02757ad965f1dc50657ba984"
$HoodLoader2IndexUrl = "https://raw.githubusercontent.com/NicoHood/HoodLoader2/$HoodLoader2Commit/package_NicoHood_HoodLoader2_index.json"

$DfuProgrammerZip = @{
    Url    = "https://github.com/dfu-programmer/dfu-programmer/releases/download/v1.1.0/dfu-programmer-x64-1.1.0.zip"
    Sha256 = "0ab135fd9f7c54d142fdd9112f2183d82f5a362032dc3d52860a84756fe96e27"
}
$DfuProgrammerExeSha256 = "a86cd0cc025823802152ef9e3b015a100c5d25ae3715fcd8064074f483add870"
$Zadig = @{
    Url    = "https://github.com/pbatard/libwdi/releases/download/v1.5.1/zadig-2.9.exe"
    Sha256 = "4ecaa95df3da3621486a043aef8b3050b8bafe7c901402871e816229ef82039b"
}
$HoodLoader2Hex = @{
    Url    = "https://raw.githubusercontent.com/NicoHood/HoodLoader2/$HoodLoader2Commit/avr/bootloaders/HexFiles/HoodLoader2_0_5_Uno_atmega16u2.hex"
    Sha256 = "97aa085a4577095bb2a8e0f2255dec8205e5e2efb010f2cbf226d3bfcab5943e"
}
$StockUnoHex = @{
    Url    = "https://raw.githubusercontent.com/arduino/ArduinoCore-avr/1.8.8/firmwares/atmegaxxu2/Arduino-COMBINED-dfu-usbserial-atmega16u2-Uno-Rev3.hex"
    Sha256 = "5f89a742be3f8ad2bcecab4a79ba09229bed174e4d59e4fdc540f53db0a37d74"
}

function Test-Sha256([string]$Path, [string]$Expected) {
    if (-not (Test-Path $Path)) { return $false }
    return ((Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLower() -eq $Expected.ToLower())
}

# Windows PowerShell 5.1 은 외부 명령이 실패해도 멈추지 않으므로 종료 코드를 직접 확인한다
function Invoke-Native([string]$What, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
}

function Get-VerifiedFile([hashtable]$Pin, [string]$OutFile) {
    if (Test-Sha256 $OutFile $Pin.Sha256) {
        Write-Host "  - OK (already verified): $OutFile"
        return
    }
    $tmp = "$OutFile.download"
    Invoke-WebRequest -Uri $Pin.Url -OutFile $tmp -UseBasicParsing
    if (-not (Test-Sha256 $tmp $Pin.Sha256)) {
        $actual = (Get-FileHash -Path $tmp -Algorithm SHA256).Hash.ToLower()
        Remove-Item $tmp -Force
        throw "SHA-256 mismatch for $($Pin.Url)`n  expected: $($Pin.Sha256)`n  actual:   $actual"
    }
    Move-Item -Path $tmp -Destination $OutFile -Force
    Write-Host "  - Verified: $OutFile"
}

Write-Host "[1/4] Checking arduino-cli $ArduinoCliVersion..." -ForegroundColor Cyan
if (-not (Get-Command arduino-cli -ErrorAction SilentlyContinue)) {
    Invoke-Native "winget install arduino-cli" { winget install --id ArduinoSA.CLI --exact --version $ArduinoCliVersion --accept-source-agreements --accept-package-agreements }
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
} else {
    $installed = (arduino-cli version) -replace '^.*Version:\s*([0-9.]+).*$', '$1'
    if ($installed -ne $ArduinoCliVersion) {
        Write-Host "  - arduino-cli $installed is installed (pinned: $ArduinoCliVersion). Builds may differ." -ForegroundColor Yellow
    }
}

Write-Host "[2/4] Configuring Arduino AVR, HoodLoader2 core and HID-Project library (pinned versions)..." -ForegroundColor Cyan
Invoke-Native "arduino-cli core update-index" { arduino-cli core update-index --additional-urls $HoodLoader2IndexUrl }
Invoke-Native "arduino-cli core install $ArduinoAvrCore" { arduino-cli core install $ArduinoAvrCore --additional-urls $HoodLoader2IndexUrl }
Invoke-Native "arduino-cli core install $HoodLoader2Core" { arduino-cli core install $HoodLoader2Core --additional-urls $HoodLoader2IndexUrl }
Invoke-Native "arduino-cli lib install $HidProjectLib" { arduino-cli lib install $HidProjectLib }

Write-Host "[3/4] Downloading dfu-programmer, Zadig, and firmware .hex files (SHA-256 verified)..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path tools, firmware_bins | Out-Null

$dfuExe = "tools\dfu-programmer\dfu-programmer.exe"
if (-not (Test-Sha256 $dfuExe $DfuProgrammerExeSha256)) {
    if (Test-Path "tools\dfu-programmer") { Remove-Item "tools\dfu-programmer" -Recurse -Force }
    $dfuZip = "tools\dfu-programmer-x64-1.1.0.zip"
    Get-VerifiedFile $DfuProgrammerZip $dfuZip
    Expand-Archive -Path $dfuZip -DestinationPath "tools\dfu-programmer" -Force
    Remove-Item $dfuZip -Force
    if (-not (Test-Sha256 $dfuExe $DfuProgrammerExeSha256)) { throw "dfu-programmer.exe hash mismatch after extraction." }
}
Write-Host "  - OK: $dfuExe"

Get-VerifiedFile $Zadig "tools\zadig.exe"
Get-VerifiedFile $HoodLoader2Hex "firmware_bins\HoodLoader2_0_5_Uno_atmega16u2.hex"
Get-VerifiedFile $StockUnoHex "firmware_bins\Arduino-Uno-R3-Stock-16u2.hex"

Write-Host "[4/4] Setting up Python virtual environment (pinned requirements)..." -ForegroundColor Cyan
if (-not (Test-Path ".venv")) {
    Invoke-Native "python -m venv" { python -m venv .venv }
}
Invoke-Native "pip upgrade" { .\.venv\Scripts\python.exe -m pip install --upgrade pip }
Invoke-Native "pip install requirements" { .\.venv\Scripts\python.exe -m pip install -r host\requirements.txt }

Write-Host "`nSetup complete!" -ForegroundColor Green
