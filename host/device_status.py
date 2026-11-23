"""
Arduino Uno R3 USB 상태 자동 판별 모듈.

반환 상태(state):
  - ready      : VirtualMouse 펌웨어 연결 및 최신 버전 일치 (1·2단계 스킵 가능)
  - outdated   : VirtualMouse 펌웨어 연결되었으나 버전이 낮음 (업데이트 필요)
  - dfu_ready  : ATmega16U2 DFU 모드 진입됨 (플래싱 대기 중)
  - stock_uno  : 순정 Arduino Uno R3 연결됨 (최초 1회 점퍼 리셋 필요)
  - no_device  : Arduino 장치가 감지되지 않음
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Dict, Tuple

EXPECTED_FW_VERSION = "1.1.0"


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


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def scan_usb_devices() -> list[Dict[str, Any]]:
    """Windows PnP 장치 목록에서 Arduino / Atmel DFU 관련 USB 장치를 조회합니다."""
    ps_cmd = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "Get-CimInstance Win32_PnPEntity | "
        "Where-Object { $_.DeviceID -match 'VID_2341|VID_03EB' } | "
        "Select-Object Name, DeviceID, Service, Status | ConvertTo-Json -Compress"
    )
    try:
        out = subprocess.check_output(
            ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_cmd],
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
            timeout=5,
        ).strip()
        if not out:
            return []
        parsed = json.loads(out)
        return parsed if isinstance(parsed, list) else [parsed]
    except Exception:
        return []


def detect_device_state(
    connected_port: str | None = None,
    firmware_version: str | None = None,
    expected_version: str = EXPECTED_FW_VERSION,
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
    dfu_dev = next(
        (d for d in devices if "VID_03EB&PID_2FEF" in (d.get("DeviceID") or "").upper()),
        None,
    )
    stock_dev = next(
        (d for d in devices if "VID_2341&PID_0043" in (d.get("DeviceID") or "").upper()),
        None,
    )

    if connected_port and firmware_version is not None:
        is_up_to_date = parse_semver(firmware_version) >= parse_semver(expected_version)
        return {
            "state": "ready" if is_up_to_date else "outdated",
            "skip_setup": is_up_to_date,
            "port": connected_port,
            "firmware_version": firmware_version,
            "expected_version": expected_version,
            "hid_mouse": has_hid_mouse,
            "hid_keyboard": has_hid_keyboard,
        }

    if dfu_dev is not None:
        winusb_ok = (dfu_dev.get("Service") or "").lower() == "winusb" and (dfu_dev.get("Status") or "") == "OK"
        return {
            "state": "dfu_ready",
            "skip_setup": False,
            "dfu_driver_ok": winusb_ok,
            "expected_version": expected_version,
        }

    if stock_dev is not None:
        return {
            "state": "stock_uno",
            "skip_setup": False,
            "expected_version": expected_version,
        }

    return {
        "state": "no_device",
        "skip_setup": False,
        "expected_version": expected_version,
    }
