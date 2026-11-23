<#
.SYNOPSIS
    콘솔(CMD) 창 없이 시스템 트레이(VM 아이콘)로 상주하는
    단일 실행 파일(dist\VirtualMouse-Agent.exe)을 패키징합니다.
#>
$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$webDir = Join-Path $RepoRoot "web"
$dfuDir = Join-Path $RepoRoot "tools\dfu-programmer"
$hexFile = Join-Path $RepoRoot "build\uno_16u2_mouse\uno_16u2_mouse.ino.hex"
$icoFile = Join-Path $RepoRoot "build\pyinstaller\vm_icon.ico"

if (-not (Test-Path $py)) { throw ".venv not found. Run scripts/setup.ps1 first." }
if (-not (Test-Path "$dfuDir\dfu-programmer.exe")) { throw "dfu-programmer.exe not found. Run scripts/setup.ps1 first." }
if (-not (Test-Path $hexFile)) { throw "Compiled firmware .hex not found. Run scripts/build_release.ps1 first." }

Write-Host "1) Generating VM RoundRect .ico icon..." -ForegroundColor Cyan
& $py -c "import sys; from pathlib import Path; sys.path.insert(0, 'host'); from tray import save_vm_ico; save_vm_ico(Path(r'$icoFile'))"
if ($LASTEXITCODE -ne 0) { throw "Icon generation failed." }

Write-Host "2) Building console-less single-file dist\VirtualMouse-Agent.exe..." -ForegroundColor Cyan

& $py -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --noconsole `
  --icon "$icoFile" `
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
