"""win_integration: virtualmouse:// 프로토콜 등록 및 Windows 시작 자동 실행 (실제 레지스트리 미접근)."""

from __future__ import annotations

import unittest
from pathlib import Path

import vm_test_support  # noqa: F401 - host/ 경로 추가

import win_integration


class FakeRegistry:
    """메모리 기반 HKCU 레지스트리 대역."""

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_value(self, subkey: str, name: str) -> str | None:
        return self.store.get((subkey, name))

    def set_value(self, subkey: str, name: str, value: str) -> None:
        self.store[(subkey, name)] = value

    def delete_value(self, subkey: str, name: str) -> None:
        if (subkey, name) not in self.store:
            raise FileNotFoundError(name)
        del self.store[(subkey, name)]


class WinIntegrationTest(unittest.TestCase):
    def test_protocol_registration_never_passes_uri_placeholder(self):
        """외부 웹페이지가 보낸 URI(%1)를 실행 인수로 넘기지 않아 인수 주입을 원천 차단한다."""
        reg = FakeRegistry()
        exe = r"C:\Apps\VirtualMouse-Agent.exe"
        res = win_integration.register_protocol_handler(backend=reg, frozen=True, executable=exe)
        self.assertTrue(res["ok"])
        self.assertEqual(reg.get_value(win_integration.PROTOCOL_KEY, "URL Protocol"), "")
        cmd = reg.get_value(win_integration.PROTOCOL_COMMAND_KEY, "")
        self.assertEqual(cmd, f'"{exe}" --from-uri')
        self.assertNotIn("%1", cmd)
        self.assertEqual(reg.get_value(win_integration.PROTOCOL_ICON_KEY, ""), f'"{exe}",0')
        self.assertTrue(win_integration.is_protocol_registered(backend=reg, check_exists=False))

    def test_protocol_registration_dev_mode_uses_server_py(self):
        reg = FakeRegistry()
        script = Path(r"C:\repo\host\server.py")
        res = win_integration.register_protocol_handler(
            backend=reg,
            frozen=False,
            executable=r"C:\py\pythonw.exe",
            script_path=script,
        )
        self.assertTrue(res["ok"])
        cmd = reg.get_value(win_integration.PROTOCOL_COMMAND_KEY, "")
        self.assertEqual(cmd, f'"C:\\py\\pythonw.exe" "{script}" --from-uri')
        self.assertNotIn("%1", cmd)

    def test_unregistered_protocol_reports_false(self):
        reg = FakeRegistry()
        self.assertFalse(win_integration.is_protocol_registered(backend=reg, check_exists=False))
        reg.set_value(win_integration.PROTOCOL_COMMAND_KEY, "", '"C:\\app.exe" --from-uri')
        # URL Protocol 값이 없으면 등록 완료로 보지 않는다
        self.assertFalse(win_integration.is_protocol_registered(backend=reg, check_exists=False))

    def test_autostart_toggle_roundtrip(self):
        reg = FakeRegistry()
        exe = r"C:\Apps\VirtualMouse-Agent.exe"
        self.assertFalse(win_integration.get_autostart(backend=reg))

        on_res = win_integration.set_autostart(True, backend=reg, frozen=True, executable=exe)
        self.assertTrue(on_res["autostart_enabled"])
        self.assertTrue(win_integration.get_autostart(backend=reg))
        self.assertEqual(
            reg.get_value(win_integration.RUN_KEY, win_integration.RUN_VALUE_NAME),
            f'"{exe}" --no-browser',
        )

        off_res = win_integration.set_autostart(False, backend=reg)
        self.assertFalse(off_res["autostart_enabled"])
        self.assertFalse(win_integration.get_autostart(backend=reg))

        # 이미 꺼져 있을 때 다시 꺼도 오류가 나지 않는다
        self.assertFalse(win_integration.set_autostart(False, backend=reg)["autostart_enabled"])


if __name__ == "__main__":
    unittest.main()
