"""driver_install: 실행 조건, UAC 결과 구분, 시간 제한, 잠금 해제.

ShellExecuteEx(UAC)와 USB 조회는 가짜로 바꾼다: 이 테스트는 드라이버를 설치하거나 UAC 창을 띄우지 않는다.
"""

from __future__ import annotations

import os
import struct
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from vm_test_support import FakeElevatedProcess, FakeLauncher, dispatcher_mod, make_fake_dispatcher

import driver_install
from dispatcher import UpdateInProgress
from driver_install import ElevationCancelled, install_dfu_winusb_driver, to_signed_exit_code

DFU_NO_DRIVER = {"DeviceID": "USB\\VID_03EB&PID_2FEF\\5&1234", "Service": None, "Status": "Error"}
DFU_LIBUSB0 = {"DeviceID": "USB\\VID_03EB&PID_2FEF\\5&1234", "Service": "libusb0", "Status": "OK"}
DFU_WINUSB = {"DeviceID": "USB\\VID_03EB&PID_2FEF\\5&1234", "Service": "WinUSB", "Status": "OK"}
VM_HID = {"DeviceID": "HID\\VID_2341&PID_484C&MI_00", "Service": "mouhid", "Status": "OK"}


def unsigned(code: int) -> int:
    """wdi-simple 의 음수 종료 코드가 Windows 에서 보이는 모양 (DWORD)."""
    return code & 0xFFFFFFFF


class ScanSequence:
    """호출할 때마다 다음 장치 목록을 돌려주고, 마지막 목록은 계속 돌려준다."""

    def __init__(self, *results: list) -> None:
        self.results = list(results)
        self.calls = 0

    def __call__(self) -> list:
        self.calls += 1
        if len(self.results) > 1:
            return self.results.pop(0)
        return self.results[0]


class DriverInstallTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tool = Path(tmp.name) / "wdi-simple.exe"
        self.tool.write_bytes(b"MZ fake wdi-simple")
        self.logs: list[tuple[str, str]] = []
        self.finished = threading.Event()
        self.finished_calls = 0

    def _on_finished(self) -> None:
        self.finished_calls += 1
        self.finished.set()

    def install(self, scan, launcher=None, **kwargs) -> dict:
        options = {"uac_timeout": 5.0, "install_timeout": 5.0, "verify_timeout": 0.0}
        options.update(kwargs)
        return install_dfu_winusb_driver(
            log=lambda message, level="INFO": self.logs.append((level, message)),
            on_finished=self._on_finished,
            scan=scan,
            launch=launcher if launcher is not None else FakeLauncher(),
            tool=options.pop("tool", self.tool),
            **options,
        )

    # --- 실행 조건: 필요할 때만 wdi-simple 을 실행한다 ---
    def test_no_dfu_device_does_not_launch(self):
        launcher = FakeLauncher()
        result = self.install(ScanSequence([VM_HID]), launcher)
        self.assertEqual(result["status"], "no_device")
        self.assertFalse(result["ok"])
        self.assertEqual(launcher.calls, [])
        self.assertEqual(self.finished_calls, 1)

    def test_existing_winusb_driver_does_not_launch(self):
        launcher = FakeLauncher()
        result = self.install(ScanSequence([DFU_WINUSB]), launcher)
        self.assertEqual(result["status"], "already_installed")
        self.assertTrue(result["ok"])
        self.assertEqual(launcher.calls, [])
        self.assertEqual(self.finished_calls, 1)

    def test_missing_tool_is_unavailable(self):
        launcher = FakeLauncher()
        with mock.patch.object(driver_install, "find_wdi_simple", lambda: None):
            result = self.install(ScanSequence([DFU_NO_DRIVER]), launcher, tool=None)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(launcher.calls, [])
        self.assertEqual(self.finished_calls, 1)

    # --- 성공 ---
    def test_success_runs_tool_elevated_from_fresh_workdir(self):
        launcher = FakeLauncher(FakeElevatedProcess(0))
        scan = ScanSequence([DFU_NO_DRIVER], [DFU_WINUSB])
        result = self.install(scan, launcher, verify_timeout=5.0)

        self.assertEqual(result["status"], "installed")
        self.assertTrue(result["ok"])
        self.assertTrue(result["verified"])
        self.assertEqual(len(launcher.calls), 1)
        call = launcher.calls[0]
        # exe 를 빈 작업 폴더에 복사해 그 폴더에서 실행한다 (libwdi 는 상대 경로를 exe 폴더 기준으로 만든다)
        self.assertTrue(call["exe_exists"])
        self.assertEqual(os.path.dirname(call["exe"]), call["cwd"])
        self.assertEqual(call["files"], ["wdi-simple.exe"])
        self.assertTrue(launcher.process.closed)
        # 작업 폴더는 끝나면 지운다
        self.assertFalse(os.path.exists(call["cwd"]))
        self.assertEqual(self.finished_calls, 1)

    def test_arguments_are_ascii_relative_and_target_dfu_winusb(self):
        launcher = FakeLauncher(FakeElevatedProcess(0))
        self.install(ScanSequence([DFU_NO_DRIVER], [DFU_WINUSB]), launcher)
        params = launcher.calls[0]["params"]
        params.encode("ascii")  # wdi-simple 은 인수를 ANSI 코드 페이지로 받는다
        for expected in ("--vid 0x03EB", "--pid 0x2FEF", "--type 0", "--dest driver", '--name "ATmega16U2 DFU"'):
            self.assertIn(expected, params)
        self.assertNotIn(":\\", params, "경로는 상대 경로만 넘긴다 (사용자 이름이 든 경로 제외)")

    def test_replaces_non_winusb_driver(self):
        """libusb0 같은 다른 드라이버가 붙어 있으면 WinUSB 로 바꾼다 (dfu_driver_ok 가 False 인 경우)."""
        launcher = FakeLauncher(FakeElevatedProcess(0))
        result = self.install(ScanSequence([DFU_LIBUSB0], [DFU_WINUSB]), launcher)
        self.assertEqual(result["status"], "installed")
        self.assertEqual(len(launcher.calls), 1)

    def test_success_without_driver_change_is_reported_unverified(self):
        launcher = FakeLauncher(FakeElevatedProcess(0))
        result = self.install(ScanSequence([DFU_NO_DRIVER]), launcher, verify_timeout=0.0)
        self.assertEqual(result["status"], "installed")
        self.assertFalse(result["verified"])

    # --- 실패 구분 ---
    def test_uac_declined_is_cancelled(self):
        launcher = FakeLauncher(error=ElevationCancelled())
        result = self.install(ScanSequence([DFU_NO_DRIVER]), launcher)
        self.assertEqual(result["status"], "cancelled")
        self.assertFalse(result["ok"])
        self.assertEqual(self.finished_calls, 1)

    def test_launch_error_is_failed(self):
        launcher = FakeLauncher(error=OSError("boom"))
        result = self.install(ScanSequence([DFU_NO_DRIVER]), launcher)
        self.assertEqual(result["status"], "failed")
        self.assertIn("boom", result["message"])
        self.assertEqual(self.finished_calls, 1)

    def test_wdi_error_code_is_reported(self):
        launcher = FakeLauncher(FakeElevatedProcess(to_signed_exit_code(unsigned(-15))))
        result = self.install(ScanSequence([DFU_NO_DRIVER]), launcher)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], -15)
        self.assertEqual(result["error"], "WDI_ERROR_NEEDS_ADMIN")

    def test_wdi_user_cancel_code_is_cancelled(self):
        launcher = FakeLauncher(FakeElevatedProcess(-14))
        result = self.install(ScanSequence([DFU_NO_DRIVER]), launcher)
        self.assertEqual(result["status"], "cancelled")

    def test_unknown_exit_code_is_failed(self):
        launcher = FakeLauncher(FakeElevatedProcess(42))
        result = self.install(ScanSequence([DFU_NO_DRIVER]), launcher)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 42)

    # --- 시간 제한 ---
    def test_install_timeout_terminates_process(self):
        process = FakeElevatedProcess(None)  # 시간 안에 끝나지 않음
        launcher = FakeLauncher(process)
        result = self.install(ScanSequence([DFU_NO_DRIVER]), launcher, install_timeout=1.5)
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["stage"], "install")
        self.assertTrue(process.terminated)
        self.assertTrue(process.closed)
        self.assertEqual(process.waited_for, [1.5])
        self.assertEqual(self.finished_calls, 1)

    def test_uac_timeout_keeps_lock_until_job_ends(self):
        """UAC 창에 답이 없으면 먼저 timeout 으로 답하되, 작업이 끝날 때까지 on_finished(잠금 해제)를 미룬다."""
        gate = threading.Event()
        launcher = FakeLauncher(FakeElevatedProcess(0), gate=gate)
        result = self.install(ScanSequence([DFU_NO_DRIVER], [DFU_WINUSB]), launcher, uac_timeout=0.2)
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["stage"], "uac")
        self.assertTrue(result["pending"])
        self.assertEqual(self.finished_calls, 0, "UAC 창이 남아 있는 동안 잠금을 놓으면 안 된다")

        gate.set()  # 사용자가 나중에 [예]를 누름
        self.assertTrue(self.finished.wait(5))
        self.assertEqual(self.finished_calls, 1)
        self.assertTrue(any("installed" in message for _, message in self.logs))

    # --- 보조 함수 ---
    def test_exit_code_conversion(self):
        self.assertEqual(to_signed_exit_code(0), 0)
        self.assertEqual(to_signed_exit_code(5), 5)
        self.assertEqual(to_signed_exit_code(0xFFFFFFF1), -15)
        self.assertEqual(to_signed_exit_code(-14), -14)

    def test_error_table_matches_libwdi_codes(self):
        self.assertEqual(driver_install.WDI_ERRORS[-14][0], "WDI_ERROR_USER_CANCEL")
        self.assertEqual(driver_install.WDI_ERROR_USER_CANCEL, -14)
        self.assertEqual(sorted(driver_install.WDI_ERRORS), [-99] + list(range(-19, 0)))

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_shellexecuteinfo_layout(self):
        """ctypes 구조체 크기가 Windows SDK 의 SHELLEXECUTEINFOW 와 같아야 ShellExecuteExW 가 받는다."""
        expected = 112 if struct.calcsize("P") == 8 else 60
        self.assertEqual(driver_install.ctypes.sizeof(driver_install.SHELLEXECUTEINFOW), expected)


class DispatcherDriverInstallTest(unittest.TestCase):
    """dispatcher.install_driver: 펌웨어 업데이트와 같은 잠금, 자동 실행 안 함."""

    def setUp(self) -> None:
        self.d = make_fake_dispatcher(self)
        # status() 가 실제 USB 조회(PowerShell)를 하지 않게 한다
        patcher = mock.patch.object(
            dispatcher_mod, "detect_device_state", lambda **kwargs: {"state": "dfu_ready", "dfu_driver_ok": False}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_status_reports_availability_without_installing(self):
        def fail(**kwargs):
            raise AssertionError("status() must never install a driver")

        with mock.patch.object(dispatcher_mod, "install_dfu_winusb_driver", fail), mock.patch.object(
            dispatcher_mod, "driver_installer_available", lambda: True
        ):
            status = self.d.status()
        self.assertTrue(status["driver_installer"])
        self.assertFalse(status["driver_installing"])

    def test_driver_install_and_firmware_update_are_mutually_exclusive(self):
        captured: dict = {}

        def fake_install(log, on_finished):
            captured["on_finished"] = on_finished
            return {"ok": False, "status": "timeout", "stage": "uac", "pending": True}

        with mock.patch.object(dispatcher_mod, "install_dfu_winusb_driver", fake_install):
            result = self.d.install_driver()
        self.assertEqual(result["status"], "timeout")
        # 설치 작업이 아직 끝나지 않았다 (on_finished 미호출): 펌웨어 업데이트·두 번째 설치를 막는다
        with self.assertRaises(UpdateInProgress) as ctx:
            self.d.update_firmware({"use_local": True})
        self.assertIn("드라이버", str(ctx.exception))
        with self.assertRaises(UpdateInProgress):
            self.d.install_driver()
        self.assertFalse(self.d.is_flashing(), "드라이버 설치는 종료를 늦추는 플래싱이 아니다")
        self.assertTrue(self.d.status()["driver_installing"])

        captured["on_finished"]()
        self.assertFalse(self.d._update_lock.locked())
        self.assertFalse(self.d.status()["driver_installing"])

    def test_driver_install_refused_while_firmware_update_runs(self):
        self.assertTrue(self.d._update_lock.acquire(blocking=False))
        self.d._update_kind = "firmware"
        try:
            with self.assertRaises(UpdateInProgress) as ctx:
                self.d.install_driver()
            self.assertIn("펌웨어", str(ctx.exception))
        finally:
            self.d._update_kind = None
            self.d._update_lock.release()

    def test_lock_is_released_when_nothing_to_install(self):
        with mock.patch.object(driver_install, "_scan_now", lambda: [DFU_WINUSB]):
            result = self.d.install_driver()
        self.assertEqual(result["status"], "already_installed")
        self.assertFalse(self.d._update_lock.locked())


if __name__ == "__main__":
    unittest.main()
