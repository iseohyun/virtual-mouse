"""여러 파일에 흩어진 버전·고정 값이 서로 같은지 확인한다 (.agents/rules/project_architecture.md)."""

from __future__ import annotations

import re
import unittest
from unittest import mock

from vm_test_support import REPO_ROOT

import device_status


def read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8-sig")


def find(pattern: str, text: str, label: str) -> str:
    match = re.search(pattern, text)
    if not match:
        raise AssertionError(f"{label}: pattern not found: {pattern}")
    return match.group(1)


class FirmwareVersionTest(unittest.TestCase):
    def test_ino_matches_expected_version(self):
        ino = read("firmware/uno_16u2_mouse/uno_16u2_mouse.ino")
        fw = find(r'#define\s+FW_VERSION\s+"([0-9]+\.[0-9]+\.[0-9]+)"', ino, "FW_VERSION")
        self.assertEqual(fw, device_status.EXPECTED_FW_VERSION)
        self.assertIn(f"VMOUSE {fw}", ino, "프로토콜 주석의 VER 응답도 같은 버전이어야 합니다")


class WebVersionTest(unittest.TestCase):
    def test_build_tag_and_version_label_agree(self):
        app = read("web/app.js")
        html = read("web/index.html")
        sw = find(r'const SW_VERSION = "(v\d+\.\d+\.\d+)";', app, "SW_VERSION")
        tag = find(r'const BUILD_TAG = "(\d{8}v\d+)";', app, "BUILD_TAG")
        self.assertEqual(re.findall(r"styles\.css\?v=(\d{8}v\d+)", html), [tag])
        self.assertEqual(re.findall(r"app\.js\?v=(\d{8}v\d+)", html), [tag])
        self.assertIn(f"SW {sw} · {tag}", html)


class WebHardeningTest(unittest.TestCase):
    """M10: 공개 대시보드 출처를 지키는 장치들."""

    def test_csp_limits_scripts_and_connections(self):
        html = read("web/index.html")
        csp = find(r'http-equiv="Content-Security-Policy"\s+content="([^"]+)"', html, "CSP")
        self.assertIn("script-src 'self'", csp)
        self.assertIn("object-src 'none'", csp)
        connect = find(r"connect-src ([^;]+)", csp, "connect-src")
        self.assertEqual(set(connect.split()), {"'self'", "http://127.0.0.1:18080", "http://localhost:18080"})

    def test_no_inline_scripts_or_styles(self):
        html = read("web/index.html")
        self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)[^>]*>", "인라인 <script> 는 CSP 에 막힙니다")
        self.assertNotRegex(html, r"\sstyle=\"", "style 속성은 CSP(style-src 'self')에 막힙니다")
        self.assertNotRegex(html, r"\son[a-z]+=\"", "인라인 이벤트 처리기는 CSP 에 막힙니다")

    def test_deploy_runs_tests_first_and_limits_permissions(self):
        deploy = read(".github/workflows/deploy.yml")
        self.assertIn("uses: ./.github/workflows/test.yml", deploy)
        self.assertRegex(deploy, r"build:\s+needs: test")
        top_permissions = find(r"(?m)^permissions:\n((?:[ \t]+.+\n)+)", deploy, "top-level permissions")
        self.assertNotIn("pages:", top_permissions, "Pages 쓰기 권한은 deploy 작업에만 둔다")
        self.assertNotIn("id-token:", top_permissions)
        self.assertIn("workflow_call:", read(".github/workflows/test.yml"))


class PinnedToolsTest(unittest.TestCase):
    """scripts/setup.ps1 과 .github/workflows/release.yml 의 고정 값이 같아야 한다."""

    def test_setup_and_release_pins_agree(self):
        setup = read("scripts/setup.ps1")
        release = read(".github/workflows/release.yml")
        pairs = [
            (r'\$ArduinoCliVersion = "([^"]+)"', r'ARDUINO_CLI_VERSION: "([^"]+)"'),
            (r'\$ArduinoAvrCore = "([^"]+)"', r'ARDUINO_AVR_CORE: "([^"]+)"'),
            (r'\$HoodLoader2Core = "([^"]+)"', r'HOODLOADER2_CORE: "([^"]+)"'),
            (r'\$HidProjectLib = "([^"]+)"', r'HID_PROJECT_LIB: "([^"]+)"'),
            (r'\$HoodLoader2Commit = "([0-9a-f]{40})"', r"HoodLoader2/([0-9a-f]{40})/package_NicoHood"),
        ]
        for setup_pattern, release_pattern in pairs:
            with self.subTest(setup_pattern):
                self.assertEqual(find(setup_pattern, setup, "setup.ps1"), find(release_pattern, release, "release.yml"))

        dfu_setup = re.search(r"\$DfuProgrammerZip = @\{.*?Sha256 = \"([0-9a-f]{64})\"", setup, re.S)
        self.assertIsNotNone(dfu_setup)
        self.assertEqual(dfu_setup.group(1), find(r'DFU_PROGRAMMER_SHA256: "([0-9a-f]{64})"', release, "release.yml"))

    def test_no_floating_downloads(self):
        setup = read("scripts/setup.ps1")
        release = read(".github/workflows/release.yml")
        for text in (setup, release):
            self.assertNotIn("/master/", text)
            self.assertNotIn("releases/latest", text)

    def test_workflow_actions_are_pinned_to_commits(self):
        for name in ("deploy.yml", "release.yml", "test.yml"):
            text = read(f".github/workflows/{name}")
            for ref in re.findall(r"uses:\s*[\w\-./]+@([^\s#]+)", text):
                with self.subTest(workflow=name, ref=ref):
                    self.assertRegex(ref, r"^[0-9a-f]{40}$")

    def test_setup_does_not_overwrite_user_config_and_checks_exit_codes(self):
        """M9: 전역 arduino-cli 설정을 덮어쓰지 않고, 외부 명령은 종료 코드를 확인한다."""
        setup = read("scripts/setup.ps1")
        self.assertNotIn("config init --overwrite", setup)
        self.assertNotIn("config add board_manager", setup)
        for line in setup.splitlines():
            stripped = line.strip()
            if stripped.startswith(("arduino-cli ", "winget ", ".\\.venv\\Scripts\\python.exe", "python -m")):
                with self.subTest(line=stripped):
                    self.fail("외부 명령은 Invoke-Native 로 감싸 종료 코드를 확인해야 합니다")

    def test_build_wdi_downloads_are_pinned(self):
        """scripts/build_wdi.ps1: 내려받는 것마다 주소와 SHA-256 을 함께 고정하고, 떠다니는 주소를 쓰지 않는다."""
        text = read("scripts/build_wdi.ps1")
        urls = re.findall(r'^\s*Url\s*=\s*"([^"]+)"', text, re.M)
        pinned = re.findall(r'Url\s*=\s*"([^"]+)"\s*\n\s*Sha256\s*=\s*"([0-9a-f]{64})"', text)
        self.assertEqual(len(urls), 4)  # libwdi 소스, WDK 재배포 MSI, 툴체인, MinGW-w64 런타임 고지
        self.assertEqual([u for u, _ in pinned], urls, "every Url needs a Sha256 right below it")
        for url in urls:
            with self.subTest(url=url):
                self.assertTrue(url.startswith("https://"))
                for floating in ("releases/latest", "/master/", "/main/", "fwlink"):
                    self.assertNotIn(floating, url)
        commit = find(r'\$LibwdiCommit = "([0-9a-f]{40})"', text, "LibwdiCommit")
        self.assertIn("/archive/$LibwdiCommit.tar.gz", text)
        self.assertEqual(len(re.findall(r'\bSha256\s*=\s*"[0-9a-f]{64}"', text)), 7)  # 다운로드 4 + 코인스톨러 2 + 사용 조건 1
        find(r'\$ExpectedWdiSimpleSha256 = "([0-9a-f]{64})"', text, "ExpectedWdiSimpleSha256")
        self.assertEqual(len(commit), 40)

    def test_build_wdi_only_extracts_and_never_elevates(self):
        """빌드 스크립트는 드라이버를 설치하거나 권한을 올리지 않는다 (wdi-simple 은 --extract 로만 실행)."""
        text = read("scripts/build_wdi.ps1")
        for forbidden in ("RunAs", "msiexec", "pnputil", "Start-Process"):
            self.assertNotIn(forbidden, text)
        runs = [line for line in text.splitlines() if "wdi-simple.exe --" in line]
        self.assertTrue(runs)
        for line in runs:
            with self.subTest(line=line.strip()):
                self.assertIn("--extract", line)

    def test_wdi_simple_is_built_bundled_and_released(self):
        release = read(".github/workflows/release.yml")
        self.assertLess(release.index("build_wdi.ps1"), release.index("build_agent.ps1"))
        self.assertIn(r"tools\wdi-simple\libwdi-*.tar.gz", release, "LGPL 대응 소스를 릴리즈 자산으로 올린다")
        agent = read("scripts/build_agent.ps1")
        self.assertIn(r'Join-Path $RepoRoot "tools\wdi-simple"', agent)
        self.assertIn(";tools/wdi-simple", agent)
        for name in ("wdi-simple.exe", "COPYING", "COPYING-LGPL", "WDF-License.rtf", "COPYING.MinGW-w64-runtime.txt", "BUILD-INFO.txt"):
            self.assertIn(f'"{name}"', agent)

    def test_wdi_simple_paths_agree(self):
        import driver_install

        expected = REPO_ROOT / "tools" / "wdi-simple" / "wdi-simple.exe"
        with mock.patch.object(driver_install, "_resource_root", lambda: REPO_ROOT), mock.patch.object(
            driver_install.Path, "is_file", lambda self: True
        ):
            self.assertEqual(driver_install.find_wdi_simple(), expected)
        self.assertIn(r'$OutDir = Join-Path $RepoRoot "tools\wdi-simple"', read("scripts/build_wdi.ps1"))
        self.assertIn(r'"tools\wdi-simple\wdi-simple.exe"', read("scripts/provision_uno.ps1"))

    def test_python_requirements_are_pinned(self):
        for name in ("host/requirements.txt", "host/requirements-dev.txt"):
            for line in read(name).splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "-r")):
                    continue
                with self.subTest(requirement=line):
                    self.assertRegex(line, r"^[A-Za-z0-9_.\-]+==[0-9][0-9A-Za-z.\-]*$")


if __name__ == "__main__":
    unittest.main()
