"""
Arduino Uno R3 USB 상태 자동 판별 모듈.

반환 상태(state):
  - ready      : VirtualMouse 펌웨어 연결 및 최신 버전 일치 (1·2단계 스킵 가능)
  - outdated   : VirtualMouse 펌웨어 연결되었으나 버전이 낮음 (업데이트 필요)
  - dfu_ready  : ATmega16U2 DFU 모드 진입됨 (플래싱 대기 중)
  - stock_uno  : 순정 Arduino Uno R3 연결됨 (최초 1회 점퍼 리셋 필요)
  - port_busy  : VirtualMouse 장치는 보이지만 COM 포트를 열 수 없음
                 (시리얼 모니터 등 다른 프로그램이 포트를 쓰는 중이거나, 에이전트가 두 개 실행 중)
  - paused     : 사용자가 로컬 제어 서비스를 일시 중지함
  - no_device  : Arduino 장치가 감지되지 않음

USB 조회(PowerShell, 약 1초)는 결과를 캐시하고 한 번에 하나만 실행한다.
사용처: dispatcher.py(status), updater.py(CLI), driver_install.py(DFU 드라이버 확인)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from typing import Any, Dict, Tuple

EXPECTED_FW_VERSION = "1.1.0"
EXPECTED_BT_FW_VERSION = "1.0.0"
BLE_DEVICE_NAME = "VirtualMouse BLE"
DFU_HARDWARE_ID = "VID_03EB&PID_2FEF"  # ATmega16U2 DFU 부트로더
_ESP32_BRIDGES = (
    ("VID_10C4&PID_EA60", "CP210x"),
    ("VID_1A86&PID_7523", "CH340"),
    ("VID_1A86&PID_55D4", "CH9102"),
    ("VID_303A", "Espressif USB"),
)
_COM_PORT_RE = re.compile(r"\((COM\d+)\)", re.IGNORECASE)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_USB_CACHE_TTL = 10.0  # 장치가 보일 때
_USB_EMPTY_CACHE_TTL = 4.0  # 아무 장치도 없을 때 (새로 꽂은 장치를 너무 늦게 알아채지 않게 짧게)
_usb_cache_ts: float | None = None
_usb_cache_data: list[Dict[str, Any]] = []
_usb_scan_lock = threading.Lock()


def _powershell_exe() -> str:
    """이름만으로 실행하면 exe 옆(다운로드 폴더 등)에 심어 둔 같은 이름의 파일이 먼저 실행될 수 있어 시스템 경로를 쓴다."""
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    path = os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return path if os.path.isfile(path) else "powershell.exe"


def _usb_cache_fresh(now: float) -> bool:
    if _usb_cache_ts is None:
        return False
    ttl = _USB_CACHE_TTL if _usb_cache_data else _USB_EMPTY_CACHE_TTL
    return (now - _usb_cache_ts) < ttl


def parse_semver(ver: str | None) -> Tuple[int, ...]:
    if not ver:
        return (0, 0, 0)
    parts = []
    for token in ver.strip().split("."):
        try:
            parts.append(int(token))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def scan_usb_devices(force: bool = False) -> list[Dict[str, Any]]:
    """Windows PnP 장치 목록에서 Arduino / Atmel DFU 관련 USB 장치를 조회합니다.

    결과는 장치가 있으면 10초, 없으면 4초 동안 캐시한다. 여러 요청이 동시에 와도 PowerShell은 하나만 실행한다.
    """
    if not force and _usb_cache_fresh(time.monotonic()):
        return _usb_cache_data
    with _usb_scan_lock:
        if not force and _usb_cache_fresh(time.monotonic()):
            return _usb_cache_data
        return _scan_usb_devices_locked()


def _scan_usb_devices_locked() -> list[Dict[str, Any]]:
    global _usb_cache_ts, _usb_cache_data
    now = time.monotonic()

    ps_cmd = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "Get-CimInstance Win32_PnPEntity | "
        "Where-Object { $_.DeviceID -match 'VID_2341|VID_03EB|VID_10C4|VID_1A86|VID_303A' } | "
        "Select-Object Name, DeviceID, Service, Status | ConvertTo-Json -Compress"
    )
    try:
        out = subprocess.check_output(
            [_powershell_exe(), "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_cmd],
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
            timeout=5,
        ).strip()
        if not out:
            _usb_cache_data = []
        else:
            parsed = json.loads(out)
            _usb_cache_data = parsed if isinstance(parsed, list) else [parsed]
        _usb_cache_ts = now
        return _usb_cache_data
    except Exception:
        # 조회 실패(시간 초과 등): 마지막 결과를 쓰되, 바로 다시 실행하지 않게 시각은 갱신한다
        _usb_cache_ts = now
        return _usb_cache_data


def find_dfu_device(devices: list[Dict[str, Any]]) -> Dict[str, Any] | None:
    """USB 장치 목록에서 DFU 모드의 ATmega16U2(03EB:2FEF)를 찾는다."""
    return next((d for d in devices if DFU_HARDWARE_ID in (d.get("DeviceID") or "").upper()), None)


def dfu_driver_installed(device: Dict[str, Any]) -> bool:
    """DFU 장치에 dfu-programmer 가 쓰는 WinUSB 드라이버가 정상으로 붙어 있는지."""
    return (device.get("Service") or "").lower() == "winusb" and (device.get("Status") or "") == "OK"


def find_esp32_bridge(devices: list[Dict[str, Any]]) -> tuple[Dict[str, Any], str] | tuple[None, None]:
    """USB 장치 목록에서 ESP32 USB-UART 브리지(CP210x/CH340/Espressif)를 찾는다."""
    for dev in devices:
        dev_id = (dev.get("DeviceID") or "").upper()
        for token, label in _ESP32_BRIDGES:
            if token in dev_id:
                return dev, label
    return None, None


def _extract_com_port(name: str | None) -> str | None:
    if not name:
        return None
    match = _COM_PORT_RE.search(name)
    return match.group(1).upper() if match else None


def _build_bt_status(
    devices: list[Dict[str, Any]],
    *,
    connected_port: str | None,
    firmware_version: str | None,
    device_type: str | None,
    ble_state: str | None,
    expected_bt_version: str,
    paused: bool,
) -> Dict[str, Any]:
    bridge_dev, bridge_label = find_esp32_bridge(devices)
    bridge_port = _extract_com_port(bridge_dev.get("Name") if bridge_dev else None)
    driver_ok = bool(bridge_dev and (bridge_dev.get("Status") or "") == "OK" and bridge_port)

    if device_type == "esp32" and connected_port and firmware_version is not None:
        ble_upper = (ble_state or "").upper() or None
        ble_connected = ble_upper == "CONNECTED"
        return {
            "state": "ble_connected" if ble_connected else "ble_advertising",
            "port": connected_port,
            "firmware_version": firmware_version,
            "expected_version": expected_bt_version,
            "ble_connected": ble_connected,
            "ble_state": ble_upper or "ADVERTISING",
            "usb_bridge": bridge_label,
            "driver_ok": True,
            "ble_name": BLE_DEVICE_NAME,
        }

    if paused and bridge_dev is not None:
        return {
            "state": "paused",
            "port": bridge_port,
            "firmware_version": None,
            "expected_version": expected_bt_version,
            "ble_connected": False,
            "ble_state": None,
            "usb_bridge": bridge_label,
            "driver_ok": driver_ok,
            "ble_name": BLE_DEVICE_NAME,
        }

    if bridge_dev is not None:
        return {
            "state": "esp32_no_fw" if driver_ok else "driver_needed",
            "port": bridge_port,
            "firmware_version": None,
            "expected_version": expected_bt_version,
            "ble_connected": False,
            "ble_state": None,
            "usb_bridge": bridge_label,
            "driver_ok": driver_ok,
            "ble_name": BLE_DEVICE_NAME,
        }

    return {
        "state": "no_device",
        "port": None,
        "firmware_version": None,
        "expected_version": expected_bt_version,
        "ble_connected": False,
        "ble_state": None,
        "usb_bridge": None,
        "driver_ok": False,
        "ble_name": BLE_DEVICE_NAME,
    }


def detect_device_state(
    connected_port: str | None = None,
    firmware_version: str | None = None,
    expected_version: str = EXPECTED_FW_VERSION,
    paused: bool = False,
    device_type: str | None = None,
    ble_state: str | None = None,
    expected_bt_version: str = EXPECTED_BT_FW_VERSION,
) -> Dict[str, Any]:
    """현재 USB 연결 상태와 펌웨어 버전을 종합해 Guide/API용 상태 객체를 반환합니다."""
    devices = scan_usb_devices()
    has_hid_mouse = any(
        "VID_2341&PID_484C" in (d.get("DeviceID") or "").upper()
        and (d.get("Service") or "").lower() == "mouhid"
        for d in devices
    )
    has_hid_keyboard = any(
        "VID_2341&PID_484C" in (d.get("DeviceID") or "").upper()
        and (d.get("Service") or "").lower() == "kbdhid"
        for d in devices
    )
    dfu_dev = find_dfu_device(devices)
    stock_dev = next(
        (d for d in devices if "VID_2341&PID_0043" in (d.get("DeviceID") or "").upper()),
        None,
    )
    has_vm_device = any("VID_2341&PID_484C" in (d.get("DeviceID") or "").upper() for d in devices)
    bt_info = _build_bt_status(
        devices,
        connected_port=connected_port,
        firmware_version=firmware_version,
        device_type=device_type,
        ble_state=ble_state,
        expected_bt_version=expected_bt_version,
        paused=paused,
    )

    if connected_port and firmware_version is not None:
        if device_type == "esp32":
            return {
                "state": "bt_ready" if bt_info["ble_connected"] else "bt_advertising",
                "device_type": "esp32",
                "skip_setup": False,
                "port": connected_port,
                "firmware_version": firmware_version,
                "expected_version": expected_version,
                "hid_mouse": has_hid_mouse,
                "hid_keyboard": has_hid_keyboard,
                "bt": bt_info,
            }
        is_up_to_date = parse_semver(firmware_version) >= parse_semver(expected_version)
        return {
            "state": "ready" if is_up_to_date else "outdated",
            "device_type": "uno",
            "skip_setup": is_up_to_date,
            "port": connected_port,
            "firmware_version": firmware_version,
            "expected_version": expected_version,
            "hid_mouse": has_hid_mouse,
            "hid_keyboard": has_hid_keyboard,
            "bt": bt_info,
        }

    if paused:
        return {
            "state": "paused",
            "device_type": None,
            "skip_setup": False,
            "expected_version": expected_version,
            "hid_mouse": has_hid_mouse,
            "hid_keyboard": has_hid_keyboard,
            "bt": bt_info,
        }

    if dfu_dev is not None:
        return {
            "state": "dfu_ready",
            "device_type": None,
            "skip_setup": False,
            "dfu_driver_ok": dfu_driver_installed(dfu_dev),
            # 지금 붙어 있는 드라이버 (없으면 None). WinUSB 가 아닌 드라이버(libusb0 등)는 설치하면 WinUSB 로 바뀐다
            "dfu_driver_service": dfu_dev.get("Service") or None,
            "expected_version": expected_version,
            "bt": bt_info,
        }

    if has_vm_device:
        # 펌웨어는 설치돼 있지만 COM 포트를 열지 못함: 점퍼·설치 안내 대신 포트 점유를 알려야 한다
        return {
            "state": "port_busy",
            "device_type": None,
            "skip_setup": False,
            "expected_version": expected_version,
            "hid_mouse": has_hid_mouse,
            "hid_keyboard": has_hid_keyboard,
            "bt": bt_info,
        }

    if stock_dev is not None:
        return {
            "state": "stock_uno",
            "device_type": None,
            "skip_setup": False,
            "expected_version": expected_version,
            "bt": bt_info,
        }

    return {
        "state": "no_device",
        "device_type": None,
        "skip_setup": False,
        "expected_version": expected_version,
        "bt": bt_info,
    }
