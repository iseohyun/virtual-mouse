<#
.SYNOPSIS
    libwdi 의 wdi-simple(WinUSB 드라이버 설치 도구)을 고정한 소스에서 빌드해 tools\wdi-simple\ 에 둡니다.
.DESCRIPTION
    VirtualMouse-Agent.exe 가 ATmega16U2 DFU 장치(03EB:2FEF)에 WinUSB 드라이버를 설치할 때 쓰는 도구입니다.
    scripts/build_agent.ps1 이 결과물을 exe 에 함께 넣고, .github/workflows/release.yml 도 이 스크립트를 그대로 부릅니다.

    외부에서 받는 것은 모두 주소와 SHA-256으로 고정하고, 값이 다르면 그 자리에서 멈춥니다 (고정 값은 이 파일에만 둡니다).
      1. libwdi 소스: v1.5.1 태그 커밋의 GitHub 아카이브
      2. WDK 8 재배포 패키지(wdfcoinstaller.msi): WinUSB 코인스톨러 2개와 사용 조건(License.rtf)만 꺼냅니다.
         WDK 전체는 필요 없습니다. MSI 는 설치하지 않고 읽기 전용으로 열어 캐비닛만 꺼내므로 관리자 권한·UAC 가 필요 없습니다.
      3. MinGW-w64 GCC 툴체인(WinLibs): 로컬 PC 와 GitHub Actions 가 같은 컴파일러로 빌드합니다 (tools\wdi-build\ 에 한 번 풀어 둠).
      4. MinGW-w64 런타임 고지 파일: exe 에 정적으로 링크되는 런타임의 라이선스 고지 (배포할 때 함께 넣어야 함).

    빌드는 libwdi 의 MinGW(autotools) 빌드 중 64비트 전용 구성과 같은 플래그로 gcc 를 직접 부릅니다:
      ./configure --disable-32bit --disable-debug --disable-shared --enable-toggable-debug
                  --enable-examples-build --with-wdkdir=wdk --with-wdfver=1011
    libusb0·libusbK 드라이버는 넣지 않고 WinUSB 만 넣습니다.
    같은 입력이면 같은 exe 가 나오도록 PE 시각을 넣지 않고(-Wl,--no-insert-timestamp), 기호를 지우고(-s),
    exe 안에 넣는 파일의 생성 시각을 소스 커밋 시각으로 맞춥니다. 결과 exe 의 SHA-256 도 고정해 두고 확인합니다
    ($ExpectedWdiSimpleSha256): 릴리즈 CI 가 만든 exe 가 누구나 로컬에서 다시 만들 수 있는 것과 같다는 뜻입니다.

    결과물 (tools\wdi-simple\, git 에 올리지 않음):
      wdi-simple.exe, COPYING(GPL-3.0), COPYING-LGPL(LGPL-3.0), WDF-License.rtf(코인스톨러 사용 조건),
      COPYING.MinGW-w64-runtime.txt(정적 링크된 런타임 고지), BUILD-INFO.txt(소스·입력·결과 해시),
      libwdi-<커밋>.tar.gz(LGPL 대응 소스, 릴리즈 자산으로도 올림)

    빌드한 exe 는 관리자 권한 없이(asInvoker) 실행되는 콘솔 프로그램입니다. 권한 상승은 에이전트(host/driver_install.py)가
    사용자가 요청할 때만 UAC 로 합니다. 이 스크립트의 자체 시험(--extract)은 관리자 권한이 아닐 때만 돌립니다:
    관리자 권한이면 libwdi 가 자체 서명 인증서를 이 PC 의 인증서 저장소에 추가하기 때문입니다 (GitHub Actions 는 예외).
#>
$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

# --- 고정 값 ---
$LibwdiCommit = "9b23b82a2dd1cbffc16d46c212f92c6bf8c0c602"  # libwdi 태그 v1.5.1
$LibwdiCommitTimeUtc = [DateTimeOffset]::Parse("2024-06-13T12:50:23Z").UtcDateTime
$LibwdiSource = @{
    Url    = "https://github.com/pbatard/libwdi/archive/$LibwdiCommit.tar.gz"
    Sha256 = "a65be68e20f0db155c98fa57f7748088165b2a8d0c19c2968e01c9ea5b2dfe4e"
}
# https://go.microsoft.com/fwlink/p/?LinkID=253170 (libwdi 위키·CI 가 쓰는 주소)가 가리키는 파일
$WdkRedist = @{
    Url    = "https://download.microsoft.com/download/0/5/F/05FD6919-6250-425B-86ED-9B095E54065A/wdfcoinstaller.msi"
    Sha256 = "29314207814ce9d5d73695f7e9239539cf37c79e750b9d5ea5a5ef5487a583d6"
}
$WdkCabinetStream = "wdfinst.cab"
# MSI 캐비닛 안 파일 키 -> libwdi 가 찾는 이름 (x64 만. redist.txt 에 재배포 가능 파일로 올라 있음)
$CoInstallers = @(
    @{ Key = "_WdfCoInstaller01011.dll_00001"; Name = "WdfCoInstaller01011.dll"; Sha256 = "f6fb39a8578f19616570d5a3dc7212c84a9da232b30a03376bbf08f4264fedf2" },
    @{ Key = "_winusbcoinstaller2.dll_00001"; Name = "winusbcoinstaller2.dll"; Sha256 = "981a17effddbc20377512ddaec9f22c2b7067e17a3e2a8ccf82bb7bb7b2420b6" }
)
$WdfLicense = @{ Key = "License.rtf"; Name = "WDF-License.rtf"; Sha256 = "68421cbf5aff522e2660d812220458b475dfee6d2e66363cf66c7144e956529e" }
$Toolchain = @{
    Url     = "https://github.com/brechtsanders/winlibs_mingw/releases/download/16.2.0posix-23.1.3-14.0.0-ucrt-r3/winlibs-x86_64-posix-seh-gcc-16.2.0-mingw-w64ucrt-14.0.0-r3.zip"
    Sha256  = "3c69305081e4a647144339a936244fcf7d3d9e558319e1ad7be2cd2886d4b6a1"
    Version = "16.2.0"
    Label   = "WinLibs GCC 16.2.0 + MinGW-w64 14.0.0 UCRT (posix-seh) r3"
}
# wdi-simple.exe 에 정적으로 링크되는 MinGW-w64 런타임의 고지: 바이너리를 배포할 때 함께 넣어야 한다.
# 툴체인 zip 에는 없어서 툴체인과 같은 런타임 버전(mingw-w64 v14.0.0 태그의 커밋)에서 받는다.
$MingwRuntimeNotice = @{
    Url    = "https://raw.githubusercontent.com/mingw-w64/mingw-w64/9b3dd0125792fe94d16cacdc596dbd42fca1b369/COPYING.MinGW-w64-runtime/COPYING.MinGW-w64-runtime.txt"
    Sha256 = "1db8da07b436c68833c0673ffee3d9fcb2526047f3820b81661865dfedc79a1f"
}
$DfuVidPid = "VID_03EB&PID_2FEF"
# 위 입력과 툴체인이 같으면 어느 PC·폴더에서 빌드해도 같은 exe 가 나온다 (재현 가능 빌드, 로컬 두 경로에서 확인).
# 릴리즈 CI 의 결과도 이 값과 같아야 한다. 고정 값을 일부러 바꿨다면 빌드가 알려 주는 새 해시로 함께 바꾼다.
$ExpectedWdiSimpleSha256 = "d654dc2ef455fb882132cf35211555cbadf1295d9e8c1dd0ba8b6afe9703e1ec"

# --- 경로 ---
$WorkDir = Join-Path $RepoRoot "tools\wdi-build"
$Downloads = Join-Path $WorkDir "downloads"
$ToolchainDir = Join-Path $WorkDir "toolchain"
$SrcParent = Join-Path $WorkDir "src"
$OutDir = Join-Path $RepoRoot "tools\wdi-simple"
# 시스템 프로그램은 이름이 아니라 시스템 경로로 실행한다
$SystemTar = Join-Path $env:SystemRoot "System32\tar.exe"
$SystemExpand = Join-Path $env:SystemRoot "System32\expand.exe"

function Test-Sha256([string]$Path, [string]$Expected) {
    if (-not (Test-Path $Path)) { return $false }
    return ((Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLower() -eq $Expected.ToLower())
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLower()
}

function Assert-Sha256([string]$Path, [string]$Expected, [string]$What) {
    if (-not (Test-Path $Path)) { throw "$What not found: $Path" }
    $actual = Get-Sha256 $Path
    if ($actual -ne $Expected.ToLower()) {
        throw "SHA-256 mismatch for $What`n  expected: $Expected`n  actual:   $actual"
    }
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
        $actual = Get-Sha256 $tmp
        Remove-Item $tmp -Force
        throw "SHA-256 mismatch for $($Pin.Url)`n  expected: $($Pin.Sha256)`n  actual:   $actual"
    }
    Move-Item -Path $tmp -Destination $OutFile -Force
    Write-Host "  - Verified: $OutFile"
}

function Assert-MicrosoftSignature([string]$Path) {
    $sig = Get-AuthenticodeSignature -FilePath $Path
    if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "O=Microsoft Corporation") {
        throw "Unexpected Authenticode signature on ${Path}: $($sig.Status) / $($sig.SignerCertificate.Subject)"
    }
}

# MSI 를 읽기 전용으로 열어 _Streams 테이블의 스트림(캐비닛) 하나를 파일로 꺼낸다 (설치·권한 상승 없음)
function Export-MsiStream([string]$MsiPath, [string]$StreamName, [string]$OutPath) {
    if (-not ("VirtualMouseBuild.MsiStream" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Runtime.InteropServices;
namespace VirtualMouseBuild {
    public static class MsiStream {
        [DllImport("msi.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
        static extern uint MsiOpenDatabaseW(string path, IntPtr persist, out IntPtr db);
        [DllImport("msi.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
        static extern uint MsiDatabaseOpenViewW(IntPtr db, string query, out IntPtr view);
        [DllImport("msi.dll", ExactSpelling = true)]
        static extern uint MsiViewExecute(IntPtr view, IntPtr record);
        [DllImport("msi.dll", ExactSpelling = true)]
        static extern uint MsiViewFetch(IntPtr view, out IntPtr record);
        [DllImport("msi.dll", ExactSpelling = true)]
        static extern uint MsiRecordReadStream(IntPtr record, uint field, byte[] buffer, ref uint size);
        [DllImport("msi.dll", ExactSpelling = true)]
        static extern uint MsiCloseHandle(IntPtr handle);

        static void Check(uint rc, string what) {
            if (rc != 0) throw new InvalidOperationException(what + " failed (error " + rc + ")");
        }

        public static long Export(string msiPath, string streamName, string outPath) {
            if (streamName.IndexOf('\'') >= 0) throw new ArgumentException("invalid stream name");
            IntPtr db = IntPtr.Zero, view = IntPtr.Zero, record = IntPtr.Zero;
            try {
                // persist = MSIDBOPEN_READONLY (0)
                Check(MsiOpenDatabaseW(msiPath, IntPtr.Zero, out db), "MsiOpenDatabase");
                Check(MsiDatabaseOpenViewW(db, "SELECT `Data` FROM `_Streams` WHERE `Name` = '" + streamName + "'", out view), "MsiDatabaseOpenView");
                Check(MsiViewExecute(view, IntPtr.Zero), "MsiViewExecute");
                Check(MsiViewFetch(view, out record), "MsiViewFetch (" + streamName + ")");
                long total = 0;
                byte[] buffer = new byte[65536];
                using (FileStream fs = new FileStream(outPath, FileMode.CreateNew, FileAccess.Write)) {
                    while (true) {
                        uint n = (uint)buffer.Length;
                        Check(MsiRecordReadStream(record, 1, buffer, ref n), "MsiRecordReadStream");
                        if (n == 0) break;
                        fs.Write(buffer, 0, (int)n);
                        total += n;
                    }
                }
                return total;
            } finally {
                if (record != IntPtr.Zero) MsiCloseHandle(record);
                if (view != IntPtr.Zero) MsiCloseHandle(view);
                if (db != IntPtr.Zero) MsiCloseHandle(db);
            }
        }
    }
}
"@
    }
    [VirtualMouseBuild.MsiStream]::Export($MsiPath, $StreamName, $OutPath) | Out-Null
}

function Install-Toolchain {
    $marker = Join-Path $ToolchainDir ".verified-$($Toolchain.Sha256)"
    $gccExe = Join-Path $ToolchainDir "mingw64\bin\gcc.exe"
    if ((Test-Path $marker) -and (Test-Path $gccExe)) {
        Write-Host "  - OK (already extracted): $ToolchainDir"
        return (Split-Path $gccExe -Parent)
    }
    $zip = Join-Path $Downloads (Split-Path $Toolchain.Url -Leaf)
    Write-Host "  - Downloading $($Toolchain.Label) (about 280 MB, once)..."
    Get-VerifiedFile $Toolchain $zip
    if (Test-Path $ToolchainDir) { Remove-Item $ToolchainDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $ToolchainDir | Out-Null
    # 문서(share)는 빼고 푼다. 압축 해제 뒤 zip 은 지워 디스크를 아낀다 (다시 받으면 해시를 다시 검사한다)
    Invoke-Native "extract toolchain" { & $SystemTar --exclude "mingw64/share" -x -f $zip -C $ToolchainDir }
    if (-not (Test-Path $gccExe)) { throw "gcc.exe not found after extracting the toolchain." }
    New-Item -ItemType File -Path $marker | Out-Null
    Remove-Item $zip -Force
    return (Split-Path $gccExe -Parent)
}

function Assert-PeMachineX64([string]$Path) {
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $peOffset = [BitConverter]::ToInt32($bytes, 0x3C)
    $signature = [BitConverter]::ToUInt32($bytes, $peOffset)
    $machine = [BitConverter]::ToUInt16($bytes, $peOffset + 4)
    if ($signature -ne 0x00004550 -or $machine -ne 0x8664) { throw "$Path is not an x64 PE executable." }
}

# PE 리소스 디렉터리에서 RT_MANIFEST(24) 항목의 내용을 모두 꺼낸다 (exe 안에 넣은 installer_x64.exe 의 문자열과 구별하려고 문자열 검색 대신 쓴다)
function Get-PeManifests([string]$Path) {
    $b = [System.IO.File]::ReadAllBytes($Path)
    $pe = [BitConverter]::ToInt32($b, 0x3C)
    $sectionCount = [BitConverter]::ToUInt16($b, $pe + 6)
    $optSize = [BitConverter]::ToUInt16($b, $pe + 20)
    $opt = $pe + 24
    $rsrcRva = [BitConverter]::ToUInt32($b, $opt + 112 + 2 * 8)  # PE32+ 데이터 디렉터리 2번 = 리소스
    $sections = for ($i = 0; $i -lt $sectionCount; $i++) {
        $s = $opt + $optSize + $i * 40
        [pscustomobject]@{ Va = [BitConverter]::ToUInt32($b, $s + 12); Size = [Math]::Max([BitConverter]::ToUInt32($b, $s + 8), [BitConverter]::ToUInt32($b, $s + 16)); Raw = [BitConverter]::ToUInt32($b, $s + 20) }
    }
    $toOffset = { param($rva) foreach ($s in $sections) { if ($rva -ge $s.Va -and $rva -lt $s.Va + $s.Size) { return $s.Raw + ($rva - $s.Va) } }; throw "RVA out of range" }
    $base = & $toOffset $rsrcRva
    $entries = { param($dir) $n = [BitConverter]::ToUInt16($b, $base + $dir + 12) + [BitConverter]::ToUInt16($b, $base + $dir + 14)
        for ($i = 0; $i -lt $n; $i++) { [pscustomobject]@{ Id = [BitConverter]::ToUInt32($b, $base + $dir + 16 + $i * 8); Target = [BitConverter]::ToUInt32($b, $base + $dir + 20 + $i * 8) } } }
    foreach ($type in (& $entries 0)) {
        if ($type.Id -ne 24) { continue }
        foreach ($name in (& $entries ($type.Target -band 0x7FFFFFFF))) {
            foreach ($lang in (& $entries ($name.Target -band 0x7FFFFFFF))) {
                $leaf = $base + $lang.Target
                $dataOffset = & $toOffset ([BitConverter]::ToUInt32($b, $leaf))
                [System.Text.Encoding]::UTF8.GetString($b, $dataOffset, [BitConverter]::ToUInt32($b, $leaf + 4))
            }
        }
    }
}

# manifest 는 libwdi 가 정한 Common-Controls 하나뿐이어야 한다. 권한 상승은 에이전트가 UAC 로만 하므로
# exe 자체가 관리자 권한을 요구하면 안 된다.
function Assert-WdiSimpleManifest([string]$Path) {
    $manifests = @(Get-PeManifests $Path)
    if ($manifests.Count -ne 1) { throw "$Path has $($manifests.Count) manifests (expected exactly 1)." }
    if ($manifests[0] -notmatch "Microsoft\.Windows\.Common-Controls") { throw "$Path has an unexpected manifest." }
    if ($manifests[0] -match "requireAdministrator|highestAvailable") { throw "$Path requests elevation in its manifest." }
}

function Test-IsElevated {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# 드라이버를 설치하지 않고 풀기만 해 본다 (--extract). 관리자 권한이면 libwdi 가 .cat 을 만들고 자체 서명한다.
# 에이전트(host/driver_install.py)와 같은 방식으로 실행한다: exe 를 빈 작업 폴더에 복사해 그 폴더에서 실행하고
# --dest 는 ASCII 상대 경로로 준다. (wdi-simple 은 인수를 ANSI 코드 페이지로 받고, libwdi 는 상대 경로를
# exe 폴더 기준으로 만들기 때문에 작업 폴더와 exe 폴더가 같아야 한다.)
function Invoke-ExtractSmokeTest([string]$Exe, [bool]$ExpectCatalog) {
    $work = Join-Path $WorkDir "smoke-test"
    if (Test-Path $work) { Remove-Item $work -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    Copy-Item $Exe (Join-Path $work "wdi-simple.exe")
    Push-Location $work
    try {
        Invoke-Native "wdi-simple --extract" {
            & .\wdi-simple.exe --vid 0x03EB --pid 0x2FEF --type 0 --name "ATmega16U2 DFU" --inf atmega16u2_dfu.inf --dest driver --extract
        }
    } finally {
        Pop-Location
    }
    $dest = Join-Path $work "driver"
    $inf = Join-Path $dest "atmega16u2_dfu.inf"
    if (-not (Test-Path $inf)) { throw "Smoke test: $inf was not created." }
    $infText = Get-Content -Path $inf -Raw -Encoding Unicode
    if ($infText -notmatch "DeviceID\s*=\s*`"$DfuVidPid`"" -or -not $infText.Contains("USB\%DeviceID%")) {
        throw "Smoke test: the inf does not target USB\$DfuVidPid."
    }
    if (-not (Test-Path (Join-Path $dest "installer_x64.exe"))) { throw "Smoke test: installer_x64.exe was not extracted." }
    foreach ($c in $CoInstallers) {
        Assert-Sha256 (Join-Path $dest "amd64\$($c.Name)") $c.Sha256 "extracted $($c.Name)"
    }
    $cat = Join-Path $dest "atmega16u2_dfu.cat"
    if ($ExpectCatalog) {
        $sig = Get-AuthenticodeSignature -FilePath $cat
        if ($sig.Status -ne "Valid") { throw "Smoke test: the self-signed catalog is not valid ($($sig.Status))." }
        Write-Host "  - Catalog self-signed by: $($sig.SignerCertificate.Subject)"
    } elseif (Test-Path $cat) {
        throw "Smoke test: a catalog was created without elevation (unexpected)."
    }
    Remove-Item $work -Recurse -Force
    Write-Host "  - Smoke test passed (inf, installer and co-installers extracted correctly)." -ForegroundColor Green
}

New-Item -ItemType Directory -Force -Path $Downloads | Out-Null

Write-Host "[1/6] MinGW-w64 toolchain ($($Toolchain.Label))..." -ForegroundColor Cyan
$tcBin = Install-Toolchain

Write-Host "[2/6] libwdi source (v1.5.1, commit $LibwdiCommit)..." -ForegroundColor Cyan
$srcArchive = Join-Path $Downloads "libwdi-$LibwdiCommit.tar.gz"
Get-VerifiedFile $LibwdiSource $srcArchive
if (Test-Path $SrcParent) { Remove-Item $SrcParent -Recurse -Force }
New-Item -ItemType Directory -Force -Path $SrcParent | Out-Null
Invoke-Native "extract libwdi source" { & $SystemTar -x -z -f $srcArchive -C $SrcParent }
$src = Join-Path $SrcParent "libwdi-$LibwdiCommit"
if (-not (Test-Path (Join-Path $src "examples\wdi-simple.c"))) { throw "Unexpected libwdi archive layout." }

Write-Host "[3/6] WinUSB co-installers from the WDK 8 redistributable package..." -ForegroundColor Cyan
$msi = Join-Path $Downloads "wdfcoinstaller.msi"
Get-VerifiedFile $WdkRedist $msi
Assert-MicrosoftSignature $msi
$cabDir = Join-Path $WorkDir "cab"
if (Test-Path $cabDir) { Remove-Item $cabDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $cabDir | Out-Null
$cab = Join-Path $cabDir $WdkCabinetStream
Export-MsiStream $msi $WdkCabinetStream $cab
$wdkX64 = Join-Path $src "wdk\redist\wdf\x64"
New-Item -ItemType Directory -Force -Path $wdkX64 | Out-Null
foreach ($c in $CoInstallers) {
    Invoke-Native "expand $($c.Key)" { & $SystemExpand $cab "-F:$($c.Key)" $cabDir | Out-Null }
    $file = Join-Path $cabDir $c.Key
    Assert-Sha256 $file $c.Sha256 $c.Name
    Assert-MicrosoftSignature $file
    Move-Item -Path $file -Destination (Join-Path $wdkX64 $c.Name)
    Write-Host "  - Verified: $($c.Name) (Microsoft signed)"
}
Invoke-Native "expand $($WdfLicense.Key)" { & $SystemExpand $cab "-F:$($WdfLicense.Key)" $cabDir | Out-Null }
Assert-Sha256 (Join-Path $cabDir $WdfLicense.Key) $WdfLicense.Sha256 $WdfLicense.Key
$mingwNotice = Join-Path $Downloads "COPYING.MinGW-w64-runtime.txt"
Get-VerifiedFile $MingwRuntimeNotice $mingwNotice

Write-Host "[4/6] Building installer_x64, embedder, libwdi and wdi-simple with gcc..." -ForegroundColor Cyan
# configure 대신 같은 값을 쓴 config.h (embedder 는 libwdi\ 에서 돌기 때문에 WDK_DIR 은 ../wdk)
$configH = @(
    "/* config.h - written by VirtualMouse scripts/build_wdi.ps1 in place of libwdi's ./configure",
    " *   --disable-32bit --disable-debug --disable-shared --enable-toggable-debug --enable-examples-build",
    " *   --with-wdkdir=wdk --with-wdfver=1011  (WinUSB only: no libusb0, libusbK or user drivers) */",
    "#define _GNU_SOURCE /**/",
    "#define WDK_DIR `"../wdk`"",
    "#define WDF_VER 1011",
    "#define COINSTALLER_DIR `"wdf`"",
    "#define X64_DIR `"x64`"",
    "#define OPT_M64 /**/",
    "#define ENABLE_LOGGING 1",
    "#define INCLUDE_DEBUG_LOGGING 1",
    ""
) -join "`n"
[System.IO.File]::WriteAllText((Join-Path $src "config.h"), $configH, (New-Object System.Text.UTF8Encoding($false)))

# libwdi configure.ac / Makefile.am 의 값 (x86_64, --disable-32bit, --disable-debug)
$AmCflags = @(
    "-Wshadow", "-Wno-stringop-truncation",
    "-DWINVER=0x0601", "-D_WIN32_WINNT=0x0601", "-D_WIN32_IE=0x0700", "-DCOBJMACROS",
    "-std=gnu99", "-Wall", "-Wundef", "-Wunused", "-Wstrict-prototypes",
    "-Werror-implicit-function-declaration", "-Wno-pointer-sign", "-Wshadow"
)
$ArchCflags = @("-m64", "-D_WIN64")
$Cflags = @("-Os")
$CppFlags = @("-DHAVE_CONFIG_H", "-I.", "-I..")
$AmLdflags = @("-Wl,--add-stdcall-alias")
# 재현 가능 빌드를 위해 더한 값: PE 시각 없음, 기호 제거
$ReproLdflags = @("-s", "-Wl,--no-insert-timestamp")

$savedPath = $env:Path
try {
    # 다른 gcc(예: PATH 의 다른 MinGW)가 끼어들지 않게 고정한 툴체인과 시스템 폴더만 쓴다 (windres 도 PATH 의 gcc 로 전처리한다)
    $env:Path = "$tcBin;$(Join-Path $env:SystemRoot 'System32');$env:SystemRoot"
    $gcc = Join-Path $tcBin "gcc.exe"
    $ar = Join-Path $tcBin "ar.exe"
    $windres = Join-Path $tcBin "windres.exe"
    $gccVersion = (& $gcc -dumpfullversion).Trim()
    if ($gccVersion -ne $Toolchain.Version) { throw "Unexpected gcc version '$gccVersion' (pinned: $($Toolchain.Version))." }

    # WinLibs gcc 는 기본 manifest(default-manifest.o)를 자동으로 링크하는데, 언어 값이 wdi-simple.rc 의 manifest 와 같아
    # ld 가 하나로 합치지 못하고 둘 다 남긴다 ('.rsrc merge failure: multiple non-default manifests').
    # MSYS2(libwdi CI)에서는 기본 manifest 가 빠지므로, wdi-simple 을 링크할 때만 그 부분을 뺀 spec 을 쓴다.
    $specLines = @(& $gcc -dumpspecs)
    $endfileIndex = [Array]::IndexOf($specLines, "*endfile:")
    $defaultManifestSpec = "%{!shared:%:if-exists(default-manifest.o%s)}"
    if ($endfileIndex -lt 0 -or -not $specLines[$endfileIndex + 1].Contains($defaultManifestSpec)) {
        throw "The toolchain's *endfile spec changed; review the default-manifest workaround."
    }
    $noDefaultManifestSpecs = Join-Path $WorkDir "no-default-manifest.specs"
    $specText = "*endfile:`n" + $specLines[$endfileIndex + 1].Replace($defaultManifestSpec, "") + "`n`n"
    [System.IO.File]::WriteAllText($noDefaultManifestSpecs, $specText, (New-Object System.Text.UTF8Encoding($false)))

    Push-Location (Join-Path $src "libwdi")
    try {
        Invoke-Native "compile installer_x64" { & $gcc @CppFlags "-m64" "-D_WIN64" @AmCflags @Cflags -c installer.c -o installer_x64-installer.o }
        Invoke-Native "link installer_x64.exe" { & $gcc "-m64" "-D_WIN64" @AmCflags @Cflags "-m64" @AmLdflags -static @ReproLdflags -o installer_x64.exe installer_x64-installer.o -lsetupapi -lnewdev -lole32 }
        Invoke-Native "build embedder" { & $gcc "-I.." embedder.c -o embedder.exe }

        # embedder 는 넣는 파일의 생성 시각을 함께 기록한다: 빌드할 때마다 같은 exe 가 나오도록 커밋 시각으로 맞춘다
        $embedded = @(Get-Item installer_x64.exe, *.inf.in, *.cat.in) + @(Get-ChildItem $wdkX64 -File)
        foreach ($f in $embedded) { $f.CreationTimeUtc = $LibwdiCommitTimeUtc; $f.LastWriteTimeUtc = $LibwdiCommitTimeUtc }
        Invoke-Native "run embedder" { & .\embedder.exe embedded.h }

        $libObjects = @()
        foreach ($name in "logging", "tokenizer", "vid_data", "pki", "libwdi_dlg", "libwdi") {
            $obj = "libwdi_la-$name.o"
            Invoke-Native "compile $name.c" { & $gcc @CppFlags @ArchCflags @AmCflags @Cflags -c "$name.c" -o $obj }
            $libObjects += $obj
        }
        Invoke-Native "archive libwdi.a" { & $ar rcsD libwdi.a @libObjects }
    } finally {
        Pop-Location
    }

    Push-Location (Join-Path $src "examples")
    try {
        # rc 파일은 UTF-8 이다: 빌드 PC 의 코드 페이지(예: CP949)와 상관없이 같은 리소스가 나오게 코드 페이지를 정한다
        Invoke-Native "compile wdi-simple.rc" { & $windres -c 65001 -i wdi-simple.rc -o wdi-simple_rc.o }
        Invoke-Native "compile wdi-simple.c" { & $gcc @CppFlags "-I../libwdi" @ArchCflags @AmCflags @Cflags -c wdi-simple.c -o wdi_simple-wdi-simple.o }
        Invoke-Native "link wdi-simple.exe" { & $gcc "-specs=$noDefaultManifestSpecs" "-I../libwdi" @ArchCflags @AmCflags @Cflags @AmLdflags -static @ReproLdflags -o wdi-simple.exe wdi_simple-wdi-simple.o wdi-simple_rc.o -L../libwdi -lwdi -lsetupapi -lole32 -lntdll }
    } finally {
        Pop-Location
    }
} finally {
    $env:Path = $savedPath
}

$builtExe = Join-Path $src "examples\wdi-simple.exe"
Assert-PeMachineX64 $builtExe
Assert-WdiSimpleManifest $builtExe
$builtSha = Get-Sha256 $builtExe
if ($builtSha -ne $ExpectedWdiSimpleSha256) {
    throw ("wdi-simple.exe is not the expected reproducible build.`n  expected: $ExpectedWdiSimpleSha256`n  actual:   $builtSha`n" +
        "  Check that the toolchain and inputs are the pinned ones. If you changed a pinned value on purpose, update `$ExpectedWdiSimpleSha256.")
}
Write-Host "  - Reproducible build verified: sha256 $builtSha"

Write-Host "[5/6] Smoke test (extract only, no driver installation)..." -ForegroundColor Cyan
if (-not (Test-IsElevated)) {
    Invoke-ExtractSmokeTest $builtExe $false
} elseif ($env:GITHUB_ACTIONS -eq "true") {
    # 일회용 CI 가상 머신에서만: 관리자 권한 경로(.cat 생성·자체 서명)까지 확인한다
    Invoke-ExtractSmokeTest $builtExe $true
} else {
    Write-Host "  - Skipped: this shell is elevated, and libwdi would add a self-signed certificate to this PC's certificate store." -ForegroundColor Yellow
    Write-Host "    Run this script from a normal (non-administrator) PowerShell to include the smoke test." -ForegroundColor Yellow
}

Write-Host "[6/6] Writing tools\wdi-simple\..." -ForegroundColor Cyan
if (Test-Path $OutDir) { Remove-Item $OutDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Copy-Item $builtExe (Join-Path $OutDir "wdi-simple.exe")
Copy-Item (Join-Path $src "COPYING") (Join-Path $OutDir "COPYING")
Copy-Item (Join-Path $src "COPYING-LGPL") (Join-Path $OutDir "COPYING-LGPL")
Copy-Item (Join-Path $cabDir $WdfLicense.Key) (Join-Path $OutDir $WdfLicense.Name)
Copy-Item $mingwNotice (Join-Path $OutDir "COPYING.MinGW-w64-runtime.txt")
Copy-Item $srcArchive (Join-Path $OutDir "libwdi-$LibwdiCommit.tar.gz")
$exeSha = Get-Sha256 (Join-Path $OutDir "wdi-simple.exe")
$buildInfo = @(
    "wdi-simple.exe - Windows USB driver installer used by VirtualMouse-Agent.exe",
    "Built by scripts/build_wdi.ps1 (https://github.com/iseohyun/virtual-mouse) with MinGW-w64, x86_64 only, WinUSB only.",
    "",
    "Output (reproducible: the same pinned inputs and toolchain give the same file)",
    "  wdi-simple.exe  sha256 $exeSha",
    "",
    "Source (LGPL-3.0-or-later, see COPYING-LGPL and COPYING)",
    "  libwdi v1.5.1, commit $LibwdiCommit",
    "  https://github.com/pbatard/libwdi/tree/$LibwdiCommit",
    "  $($LibwdiSource.Url)",
    "  sha256 $($LibwdiSource.Sha256)  (copy included: libwdi-$LibwdiCommit.tar.gz)",
    "  Build configuration: config.h written by scripts/build_wdi.ps1 (no source changes).",
    "",
    "Embedded Microsoft redistributables (Microsoft Windows Driver Frameworks 1.11, see WDF-License.rtf)",
    "  WdfCoInstaller01011.dll (x64)  sha256 $($CoInstallers[0].Sha256)",
    "  winusbcoinstaller2.dll (x64)   sha256 $($CoInstallers[1].Sha256)",
    "  from $($WdkRedist.Url)",
    "  sha256 $($WdkRedist.Sha256)",
    "",
    "Toolchain",
    "  $($Toolchain.Label)",
    "  $($Toolchain.Url)",
    "  sha256 $($Toolchain.Sha256)",
    "  Statically linked runtime: MinGW-w64 runtime (notices: COPYING.MinGW-w64-runtime.txt) and libgcc",
    "  (GPL-3.0 with the GCC Runtime Library Exception). No winpthreads.",
    ""
) -join "`r`n"
[System.IO.File]::WriteAllText((Join-Path $OutDir "BUILD-INFO.txt"), $buildInfo, (New-Object System.Text.UTF8Encoding($false)))

$sizeKB = [math]::Round((Get-Item (Join-Path $OutDir "wdi-simple.exe")).Length / 1KB, 1)
Write-Host "`nBuild succeeded: tools\wdi-simple\wdi-simple.exe ($sizeKB KB)" -ForegroundColor Green
Write-Host "  sha256 $exeSha"
