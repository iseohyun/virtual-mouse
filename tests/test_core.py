"""mouse_client·keycodes·device_status·updater 의 하드웨어 없는 부분."""

from __future__ import annotations

import hashlib
import io
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import vm_test_support  # noqa: F401 - host/ 경로 추가

import device_status
import updater
from device_status import detect_device_state, parse_semver
from keycodes import resolve_keycode
from mouse_client import VirtualMouse, normalize_button, validate_human_text, validate_int16, validate_raw_text


class _FakeSerial:
    """VirtualMouse.ser 대역: 쓴 바이트와 입력 버퍼 비우기 횟수를 기록한다."""

    def __init__(self, replies: list[bytes] | None = None) -> None:
        self.written: list[bytes] = []
        self.resets = 0
        self.replies = list(replies or [])

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def flush(self) -> None:
        pass

    def reset_input_buffer(self) -> None:
        self.resets += 1

    def readline(self) -> bytes:
        return self.replies.pop(0) if self.replies else b"OK\n"


def _client(replies: list[bytes] | None = None) -> VirtualMouse:
    vm = VirtualMouse.__new__(VirtualMouse)
    vm.ser = _FakeSerial(replies)
    vm.port = "FAKE"
    return vm


class RawTextTest(unittest.TestCase):
    def test_rejects_control_and_non_ascii(self):
        for bad in ("a\nBOOT", "x\r", "tab\there", "del\x7f", "한글"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                validate_raw_text(bad)

    def test_accepts_printable_ascii_and_chunks_by_32(self):
        vm = _client()
        text = "Hello VirtualMouse! " * 3  # 60자
        vm.key_write_text(text)
        self.assertEqual(len(vm.ser.written), 2)
        self.assertTrue(all(chunk.startswith(b"KW ") and chunk.endswith(b"\n") for chunk in vm.ser.written))
        self.assertTrue(all(len(chunk) <= 48 for chunk in vm.ser.written))

    def test_human_text_is_checked_as_a_whole(self):
        self.assertEqual(validate_human_text("pass\r\nword\rend\tx"), "pass\nword\nend\tx")
        with self.assertRaises(ValueError):
            validate_human_text("hello 한글")
        with self.assertRaises(ValueError):
            validate_human_text("bell\x07")


class DeviceCommandSafetyTest(unittest.TestCase):
    """M1·L1: 장치로 가는 명령에 줄바꿈이나 넘치는 값이 섞이지 않는다."""

    def test_button_must_be_l_r_m(self):
        self.assertEqual(normalize_button(" r "), "R")
        for bad in ("L\nBOOT", "X", "", "LL"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                normalize_button(bad)
        vm = _client()
        with self.assertRaises(ValueError):
            vm.press("L\nBOOT")
        self.assertEqual(vm.ser.written, [])

    def test_move_range_is_int16(self):
        self.assertEqual(validate_int16("dx", -32768), -32768)
        with self.assertRaises(ValueError):
            validate_int16("dx", 40000)
        vm = _client()
        with self.assertRaises(ValueError):
            vm.move(40000, 0)
        self.assertEqual(vm.ser.written, [])

    def test_send_rejects_multi_line_command(self):
        vm = _client()
        with self.assertRaises(ValueError):
            vm._send("PING\nBOOT")
        self.assertEqual(vm.ser.written, [])

    def test_stale_replies_are_dropped_before_each_command(self):
        """M3: 늦게 온 응답 때문에 응답이 한 줄씩 밀리지 않게 보낼 때마다 입력 버퍼를 비운다."""
        vm = _client([b"PONG\n"])
        self.assertTrue(vm.ping())
        vm.click("L")
        self.assertEqual(vm.ser.resets, 2)


class KeycodesAndVersionTest(unittest.TestCase):
    def test_resolve_keycode(self):
        self.assertEqual(resolve_keycode("ctrl"), 224)
        self.assertEqual(resolve_keycode("A"), 4)
        self.assertEqual(resolve_keycode("enter"), 40)
        self.assertEqual(resolve_keycode(42), 42)
        with self.assertRaises(ValueError):
            resolve_keycode(300)
        with self.assertRaises(ValueError):
            resolve_keycode("no-such-key")

    def test_parse_semver(self):
        self.assertEqual(parse_semver("1.2.3"), (1, 2, 3))
        self.assertEqual(parse_semver("1.2"), (1, 2, 0))
        self.assertEqual(parse_semver(None), (0, 0, 0))
        self.assertEqual(parse_semver("1.x.3"), (1, 0, 3))
        self.assertGreater(parse_semver("1.10.0"), parse_semver("1.9.9"))


class DeviceStateTest(unittest.TestCase):
    def _state(self, devices, **kwargs):
        with mock.patch.object(device_status, "scan_usb_devices", lambda force=False: devices):
            return detect_device_state(**kwargs)

    def test_ready_and_outdated(self):
        dev = [{"DeviceID": "HID\\VID_2341&PID_484C&MI_00", "Service": "mouhid", "Status": "OK"}]
        ready = self._state(dev, connected_port="COM9", firmware_version="1.1.0", expected_version="1.1.0")
        self.assertEqual(ready["state"], "ready")
        self.assertTrue(ready["hid_mouse"])
        old = self._state(dev, connected_port="COM9", firmware_version="1.0.0", expected_version="1.1.0")
        self.assertEqual(old["state"], "outdated")

    def test_port_busy_when_device_present_but_not_connected(self):
        """M4: 장치는 보이는데 COM 을 못 열면 '보드 미연결'이 아니라 port_busy."""
        dev = [
            {"DeviceID": "HID\\VID_2341&PID_484C&MI_00", "Service": "mouhid", "Status": "OK"},
            {"DeviceID": "USB\\VID_2341&PID_484C&MI_02", "Service": "usbser", "Status": "OK"},
        ]
        state = self._state(dev)
        self.assertEqual(state["state"], "port_busy")
        self.assertTrue(state["hid_mouse"])

    def test_paused_state(self):
        dev = [{"DeviceID": "HID\\VID_2341&PID_484C&MI_00", "Service": "mouhid", "Status": "OK"}]
        self.assertEqual(self._state(dev, paused=True)["state"], "paused")

    def test_dfu_driver_detection(self):
        winusb = [{"DeviceID": "USB\\VID_03EB&PID_2FEF\\1", "Service": "WinUSB", "Status": "OK"}]
        self.assertTrue(self._state(winusb)["dfu_driver_ok"])
        missing = [{"DeviceID": "USB\\VID_03EB&PID_2FEF\\1", "Service": None, "Status": "Error"}]
        state = self._state(missing)
        self.assertEqual(state["state"], "dfu_ready")
        self.assertFalse(state["dfu_driver_ok"])

    def test_stock_and_no_device(self):
        stock = [{"DeviceID": "USB\\VID_2341&PID_0043\\1", "Service": "usbser", "Status": "OK"}]
        self.assertEqual(self._state(stock)["state"], "stock_uno")
        self.assertEqual(self._state([])["state"], "no_device")

    def test_esp32_ble_states(self):
        cp210x = [
            {
                "Name": "Silicon Labs CP210x USB to UART Bridge (COM10)",
                "DeviceID": "USB\\VID_10C4&PID_EA60\\0001",
                "Service": "silabser",
                "Status": "OK",
            }
        ]
        connected = self._state(
            cp210x,
            connected_port="COM10",
            firmware_version="1.0.0",
            device_type="esp32",
            ble_state="CONNECTED",
        )
        self.assertEqual(connected["state"], "bt_ready")
        self.assertEqual(connected["device_type"], "esp32")
        self.assertTrue(connected["bt"]["ble_connected"])
        self.assertEqual(connected["bt"]["state"], "ble_connected")
        self.assertEqual(connected["bt"]["usb_bridge"], "CP210x")

        adv = self._state(
            cp210x,
            connected_port="COM10",
            firmware_version="1.0.0",
            device_type="esp32",
            ble_state="ADVERTISING",
        )
        self.assertEqual(adv["state"], "bt_advertising")
        self.assertEqual(adv["bt"]["state"], "ble_advertising")
        self.assertFalse(adv["bt"]["ble_connected"])

        no_fw = self._state(cp210x)
        self.assertEqual(no_fw["bt"]["state"], "esp32_no_fw")
        self.assertEqual(no_fw["bt"]["port"], "COM10")

        bad_driver = [{"Name": "CP2102N USB", "DeviceID": "USB\\VID_10C4&PID_EA60\\0001", "Service": None, "Status": "Error"}]
        self.assertEqual(self._state(bad_driver)["bt"]["state"], "driver_needed")

    def test_esp32_client_version_and_ble_status(self):
        vm = _client([b"VMOUSE_ESP32 1.0.0\n", b"CONNECTED\n", b"OK\n"])
        vm.device_type = "uno"
        self.assertEqual(vm.version(), "1.0.0")
        self.assertEqual(vm.device_type, "esp32")
        self.assertEqual(vm.ble_status(), "CONNECTED")
        self.assertTrue(vm.demo())


class UsbScanCacheTest(unittest.TestCase):
    """M5: 장치가 없을 때도 결과를 캐시해 폴링마다 PowerShell 을 띄우지 않는다."""

    def setUp(self) -> None:
        self.calls = 0
        patcher = mock.patch.object(device_status.subprocess, "check_output", self._fake_check_output)
        patcher.start()
        self.addCleanup(patcher.stop)
        device_status._usb_cache_ts = None
        device_status._usb_cache_data = []
        self.addCleanup(setattr, device_status, "_usb_cache_ts", None)

    def _fake_check_output(self, *args, **kwargs):
        self.calls += 1
        return ""

    def test_empty_result_is_cached(self):
        self.assertEqual(device_status.scan_usb_devices(), [])
        self.assertEqual(device_status.scan_usb_devices(), [])
        self.assertEqual(self.calls, 1)

    def test_empty_cache_expires_sooner(self):
        device_status.scan_usb_devices()
        device_status._usb_cache_ts = time.monotonic() - device_status._USB_EMPTY_CACHE_TTL - 0.1
        device_status.scan_usb_devices()
        self.assertEqual(self.calls, 2)

    def test_powershell_runs_from_system_path(self):
        seen = {}

        def capture(cmd, **kwargs):
            seen["exe"] = cmd[0]
            return ""

        with mock.patch.object(device_status.subprocess, "check_output", capture):
            device_status.scan_usb_devices(force=True)
        self.assertTrue(seen["exe"].lower().endswith("powershell.exe"))


class FirmwareDownloadTest(unittest.TestCase):
    def test_hash_mismatch_deletes_download(self):
        payload = b":00000001FF\n"
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            updater.urllib.request, "urlopen", lambda req, timeout=0: io.BytesIO(payload)
        ):
            with self.assertRaises(ValueError):
                updater.download_and_verify_firmware("https://example.invalid/fw.hex", "0" * 64, dest_dir=Path(tmp))
            self.assertFalse((Path(tmp) / "firmware_download.hex").exists())

            good = hashlib.sha256(payload).hexdigest()
            path = updater.download_and_verify_firmware("https://example.invalid/fw.hex", good, dest_dir=Path(tmp))
            self.assertEqual(path.read_bytes(), payload)

    def test_default_manifest_points_to_github_release(self):
        # 환경 변수(VMOUSE_MANIFEST_URL)와 상관없이 코드에 적힌 기본값을 확인한다
        source = (vm_test_support.HOST_DIR / "updater.py").read_text(encoding="utf-8")
        self.assertIn('"https://github.com/iseohyun/virtual-mouse/releases/latest/download/latest.json"', source)


class DfuTimeoutTest(unittest.TestCase):
    """M6: dfu-programmer 가 멈춰도 에이전트가 무기한 멈추지 않는다."""

    def setUp(self) -> None:
        patcher = mock.patch.object(updater, "find_dfu_programmer", lambda: Path("dfu-programmer.exe"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_flash_step_timeout_becomes_error(self):
        def hang(cmd, **kwargs):
            self.assertIn("timeout", kwargs)
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(updater.subprocess, "run", hang):
            hex_path = Path(tmp) / "fw.hex"
            hex_path.write_text(":00000001FF\n", encoding="ascii")
            with self.assertRaises(RuntimeError) as ctx:
                updater.flash_hex_via_dfu(hex_path)
        self.assertIn("timed out", str(ctx.exception))

    def test_probe_timeout_keeps_waiting_until_deadline(self):
        def hang(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

        started = time.monotonic()
        with mock.patch.object(updater.subprocess, "run", hang):
            self.assertFalse(updater.wait_for_dfu_ready(timeout=0.2))
        self.assertLess(time.monotonic() - started, 2.0)


if __name__ == "__main__":
    unittest.main()
