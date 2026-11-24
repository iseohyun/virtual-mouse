<#
.SYNOPSIS
    웹 대시보드의 캐시 버스팅 태그(YYYYMMDDvN)를 한 번에 올립니다. -SwVersion 을 주면 SemVer 표시도 함께 바꿉니다.
.DESCRIPTION
    고치는 곳 (모두 같은 값으로):
      - web/app.js     : const BUILD_TAG = "...";  (-SwVersion 이 있으면 const SW_VERSION = "vX.Y.Z";)
      - web/index.html : styles.css?v=..., app.js?v=..., 사이드바의 "SW vX.Y.Z (가운뎃점) 태그" 표시
    태그 규칙: 오늘 날짜(YYYYMMDD)와 같으면 N을 1 올리고, 날짜가 바뀌면 v1부터 다시 시작합니다.
    web/ 파일을 고친 뒤 배포(푸시) 전에 실행합니다. SemVer(-SwVersion)는 사용자 승인 후에만 바꿉니다.
    규칙: .agents/rules/project_architecture.md, 검증: tests/test_versions.py
.EXAMPLE
    .\scripts\bump_build_tag.ps1
.EXAMPLE
    .\scripts\bump_build_tag.ps1 -SwVersion v1.2.0
#>
param(
    [string]$SwVersion = "",
    [string]$Date = (Get-Date -Format "yyyyMMdd")
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$appJs = Join-Path $RepoRoot "web\app.js"
$indexHtml = Join-Path $RepoRoot "web\index.html"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$dot = [string][char]0x00B7

if ($Date -notmatch '^\d{8}$') { throw "Date must be YYYYMMDD" }

$app = [System.IO.File]::ReadAllText($appJs, $utf8NoBom)
$html = [System.IO.File]::ReadAllText($indexHtml, $utf8NoBom)

if ($app -notmatch 'const BUILD_TAG = "(\d{8})v(\d+)";') { throw "BUILD_TAG not found in web/app.js" }
$oldTag = "$($Matches[1])v$($Matches[2])"
if ($Matches[1] -eq $Date) { $n = [int]$Matches[2] + 1 } else { $n = 1 }
$newTag = "${Date}v$n"

if ($app -notmatch 'const SW_VERSION = "(v\d+\.\d+\.\d+)";') { throw "SW_VERSION not found in web/app.js" }
$oldSw = $Matches[1]
$newSw = $oldSw
if ($SwVersion) {
    if ($SwVersion -notmatch '^v\d+\.\d+\.\d+$') { throw "SwVersion must look like v1.2.3" }
    $newSw = $SwVersion
}

$app = $app.Replace("const BUILD_TAG = `"$oldTag`";", "const BUILD_TAG = `"$newTag`";")
$app = $app.Replace("const SW_VERSION = `"$oldSw`";", "const SW_VERSION = `"$newSw`";")

$html = $html -replace '(styles\.css|app\.js)\?v=\d{8}v\d+', ('${1}?v=' + $newTag)
$html = $html -replace ('SW v\d+\.\d+\.\d+ ' + $dot + ' \d{8}v\d+'), ("SW $newSw $dot $newTag")

$expectedRefs = ([regex]::Matches($html, [regex]::Escape("?v=$newTag"))).Count
if ($expectedRefs -ne 2) { throw "Expected 2 asset references with ?v=$newTag in web/index.html, found $expectedRefs" }
if (-not $html.Contains("SW $newSw $dot $newTag")) { throw "Version label not updated in web/index.html" }

[System.IO.File]::WriteAllText($appJs, $app, $utf8NoBom)
[System.IO.File]::WriteAllText($indexHtml, $html, $utf8NoBom)

Write-Host "BUILD_TAG : $oldTag -> $newTag"
Write-Host "SW_VERSION: $oldSw -> $newSw"
