<#
.SYNOPSIS
    로컬 API 서버, 웹 가이드(web/), dfu-programmer, 최신 펌웨어(.hex)를
    단일 실행 파일(dist\VirtualMouse-Agent.exe)로 패키징합니다.
#>
$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$webDir = Join-Path $RepoRoot "web"
$dfuDir = Join-Path $RepoRoot "tools\dfu-programmer"
$hexFile = Join-Path $RepoRoot "build\uno_16u2_mouse\uno_16u2_mouse.ino.hex"

if (-not (Test-Path $py)) { throw ".venv not found. Run scripts/setup.ps1 first." }
if (-not (Test-Path "$dfuDir\dfu-programmer.exe")) { throw "dfu-programmer.exe not found. Run scripts/setup.ps1 first." }
if (-not (Test-Path $hexFile)) { throw "Compiled firmware .hex not found. Run scripts/build_release.ps1 first." }

Write-Host "Building single-file dist\VirtualMouse-Agent.exe with PyInstaller..." -ForegroundColor Cyan

& $py -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --name "VirtualMouse-Agent" `
  --paths "$RepoRoot\host" `
  --add-data "$webDir;web" `
  --add-data "$dfuDir\dfu-programmer.exe;tools/dfu-programmer" `
  --add-data "$dfuDir\libusb-1.0.dll;tools/dfu-programmer" `
  --add-data "$hexFile;firmware_bins" `
  --workpath "$RepoRoot\build\pyinstaller" `
  --specpath "$RepoRoot\build\pyinstaller" `
  --distpath "$RepoRoot\dist" `
  "$RepoRoot\host\server.py"

if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$exePath = Join-Path $RepoRoot "dist\VirtualMouse-Agent.exe"
$sizeMB = [math]::Round((Get-Item $exePath).Length / 1MB, 2)
Write-Host "`nBuild succeeded: $exePath ($sizeMB MB)" -ForegroundColor Green
