"""
VirtualMouse Remote Firmware Updater (Guide 없이 단독 갱신 가능)

기능:
  1. 원격 릴리즈 매니페스트(latest.json) 조회 및 버전 비교
  2. 최신 .hex 펌웨어 다운로드 및 SHA-256 무결성 검증
  3. dfu-programmer를 이용한 ATmega16U2 자동 플래싱
  4. CLI 단독 실행 지원:
       python host/updater.py --check
       python host/updater.py --update
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict

from device_status import EXPECTED_FW_VERSION, detect_device_state, parse_semver
from mouse_client import VirtualMouse

DEFAULT_MANIFEST_URL = os.environ.get(
    "VMOUSE_MANIFEST_URL",
    "https://virtual-mouse.iseohyun.com/releases/latest.json",
)


def _resource_root() -> Path:
    """개발 환경 루트 또는 PyInstaller 번들(_MEIPASS) 루트를 반환합니다."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def find_dfu_programmer() -> Path:
    root = _resource_root()
    candidates = [
        root / "tools" / "dfu-programmer" / "dfu-programmer.exe",
        root / "dfu-programmer.exe",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError("dfu-programmer.exe를 찾을 수 없습니다. scripts/setup.ps1을 실행해 주세요.")


def find_local_hex() -> Path | None:
    root = _resource_root()
    candidates = [
        root / "build" / "uno_16u2_mouse" / "uno_16u2_mouse.ino.hex",
        root / "firmware_bins" / "uno_16u2_mouse.ino.hex",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def fetch_manifest(manifest_url: str = DEFAULT_MANIFEST_URL, timeout: float = 10.0) -> Dict[str, Any]:
    req = urllib.request.Request(
        manifest_url,
        headers={"User-Agent": "VirtualMouse-Updater/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8-sig"))
    for key in ("firmware_version", "firmware_url", "sha256"):
        if key not in data:
            raise ValueError(f"Invalid manifest: missing field {key!r}")
    return data


def check_for_update(
    current_version: str | None,
    manifest_url: str = DEFAULT_MANIFEST_URL,
) -> Dict[str, Any]:
    manifest = fetch_manifest(manifest_url)
    remote_ver = str(manifest["firmware_version"])
    update_available = (
        current_version is None
        or parse_semver(remote_ver) > parse_semver(current_version)
    )
    return {
        "current_version": current_version,
        "remote_version": remote_ver,
        "update_available": update_available,
        "firmware_url": manifest["firmware_url"],
        "sha256": str(manifest["sha256"]).lower(),
        "notes": manifest.get("notes", ""),
    }


def download_and_verify_firmware(
    firmware_url: str,
    expected_sha256: str,
    dest_dir: Path | None = None,
    timeout: float = 20.0,
) -> Path:
    target_dir = dest_dir or Path(tempfile.gettempdir()) / "virtualmouse_fw"
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / "firmware_download.hex"

    req = urllib.request.Request(
        firmware_url,
        headers={"User-Agent": "VirtualMouse-Updater/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content = resp.read()

    out_path.write_bytes(content)
    actual_sha = sha256_file(out_path)
    if actual_sha != expected_sha256.strip().lower():
        out_path.unlink(missing_ok=True)
        raise ValueError(
            f"SHA-256 mismatch! expected={expected_sha256.lower()}, actual={actual_sha}"
        )
    return out_path


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def wait_for_dfu_ready(timeout: float = 8.0) -> bool:
    dfu_exe = find_dfu_programmer()
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = subprocess.run(
            [str(dfu_exe), "atmega16u2", "get", "bootloader-version"],
            capture_output=True,
            text=True,
            creationflags=_NO_WINDOW,
        )
        if res.returncode == 0:
            return True
        time.sleep(0.5)
    return False


def flash_hex_via_dfu(hex_path: Path) -> Dict[str, Any]:
    dfu_exe = find_dfu_programmer()
    if not hex_path.exists():
        raise FileNotFoundError(f"HEX file not found: {hex_path}")

    steps = [
        ("erase", [str(dfu_exe), "atmega16u2", "erase", "--force"]),
        ("flash", [str(dfu_exe), "atmega16u2", "flash", str(hex_path)]),
        ("launch", [str(dfu_exe), "atmega16u2", "launch"]),
    ]
    logs: Dict[str, str] = {}
    for name, cmd in steps:
        res = subprocess.run(cmd, capture_output=True, text=True, creationflags=_NO_WINDOW)
        logs[name] = (res.stdout + "\n" + res.stderr).strip()
        if res.returncode != 0:
            raise RuntimeError(f"DFU {name} failed (code {res.returncode}): {logs[name]}")

    return {"ok": True, "hex": str(hex_path), "needs_replug": True, "logs": logs}


def run_cli() -> None:
    parser = argparse.ArgumentParser(description="VirtualMouse Standalone Firmware Updater")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST_URL, help="Remote latest.json URL")
    parser.add_argument("--check", action="store_true", help="Only check for updates")
    parser.add_argument("--update", action="store_true", help="Download and flash if newer")
    parser.add_argument("--force", action="store_true", help="Flash even if already up to date")
    args = parser.parse_args()

    current_ver: str | None = None
    vm: VirtualMouse | None = None
    try:
        vm = VirtualMouse()
        if vm.ping():
            current_ver = vm.version()
    except Exception:
        vm = None

    info = check_for_update(current_ver, manifest_url=args.manifest)
    print(json.dumps(info, ensure_ascii=False, indent=2))

    if args.check and not args.update:
        if vm:
            vm.close()
        return

    if args.update:
        if not info["update_available"] and not args.force:
            print("Already up to date.")
            if vm:
                vm.close()
            return

        hex_path = download_and_verify_firmware(info["firmware_url"], info["sha256"])
        print(f"Verified firmware downloaded: {hex_path}")

        if vm is not None:
            print("Entering DFU mode via software BOOT command...")
            vm.enter_bootloader()
            vm.close()
            if not wait_for_dfu_ready(timeout=8.0):
                raise RuntimeError("DFU mode did not appear after BOOT command.")
        else:
            state = detect_device_state(expected_version=EXPECTED_FW_VERSION)
            if state["state"] != "dfu_ready":
                raise RuntimeError(
                    f"Device state is {state['state']!r}. Enter DFU mode (jumper 1s) first."
                )

        result = flash_hex_via_dfu(hex_path)
        print("Flash succeeded! Please unplug and replug your Arduino Uno USB cable.")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run_cli()
