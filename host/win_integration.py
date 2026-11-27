"""
Windows 통합 기능: 커스텀 URI 프로토콜(virtualmouse://) 등록 및 로그인 시 자동 실행.

- 모두 현재 사용자 레지스트리(HKCU)만 사용하므로 관리자 권한(UAC)이 필요 없다.
- 보안: virtualmouse:// 핸들러 명령에는 "%1"(외부 웹페이지가 보낸 URI 인수)을 넘기지 않는다.
  따라서 어떤 사이트가 virtualmouse://... 를 호출해도 임의 인수 주입이 불가능하며,
  오직 기본 루프백(127.0.0.1:18080, 토큰 인증 필수) 에이전트만 실행된다.
- 단위 테스트에서는 RegistryStore 대역을 주입해 실제 Windows 레지스트리를 건드리지 않는다.

사용처: server.py(시작 시 프로토콜 등록), dispatcher.py(/status, /control/autostart), tray.py(자동 실행 메뉴)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Protocol

try:
    import winreg
except ImportError:  # Linux/macOS CI 환경
    winreg = None  # type: ignore[assignment]

PROTOCOL_SCHEME = "virtualmouse"
PROTOCOL_KEY = rf"Software\Classes\{PROTOCOL_SCHEME}"
PROTOCOL_COMMAND_KEY = rf"{PROTOCOL_KEY}\shell\open\command"
PROTOCOL_ICON_KEY = rf"{PROTOCOL_KEY}\DefaultIcon"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "VirtualMouseAgent"


class RegistryBackend(Protocol):
    """테스트에서 실제 레지스트리 대신 주입할 최소 인터페이스."""

    def get_value(self, subkey: str, name: str) -> str | None: ...
    def set_value(self, subkey: str, name: str, value: str) -> None: ...
    def delete_value(self, subkey: str, name: str) -> None: ...


class _WinRegBackend:
    """Windows HKCU 전용 레지스트리 백엔드."""

    def get_value(self, subkey: str, name: str) -> str | None:
        if winreg is None:
            return None
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return str(value) if value is not None else None
        except OSError:
            return None

    def set_value(self, subkey: str, name: str, value: str) -> None:
        if winreg is None:
            raise OSError("Windows 레지스트리를 사용할 수 없는 환경입니다.")
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def delete_value(self, subkey: str, name: str) -> None:
        if winreg is None:
            return
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            return


def _default_backend() -> RegistryBackend:
    return _WinRegBackend()


def is_windows_supported() -> bool:
    return sys.platform == "win32" and winreg is not None


def _resolve_pythonw(executable: str) -> str:
    """개발 환경에서 python.exe 대신 콘솔 없는 pythonw.exe 가 옆에 있으면 그것을 쓴다."""
    exe_path = Path(executable)
    if exe_path.name.lower() == "python.exe":
        candidate = exe_path.with_name("pythonw.exe")
        if candidate.is_file():
            return str(candidate)
    return str(exe_path)


def build_launch_command(
    *,
    extra_args: tuple[str, ...] = (),
    frozen: bool | None = None,
    executable: str | None = None,
    script_path: Path | None = None,
) -> str:
    """에이전트를 안전하게 실행할 고정 명령줄 문자열을 만든다 (외부 %1 인수는 절대 포함하지 않음)."""
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    exe = executable or sys.executable
    args_str = (" " + " ".join(extra_args)) if extra_args else ""
    if is_frozen:
        return f'"{exe}"{args_str}'
    launcher = _resolve_pythonw(exe)
    target_script = script_path or (Path(__file__).resolve().parent / "server.py")
    return f'"{launcher}" "{target_script}"{args_str}'


def _extract_command_exe(command: str) -> str | None:
    text = command.strip()
    if not text:
        return None
    if text.startswith('"'):
        end = text.find('"', 1)
        return text[1:end] if end > 1 else None
    return text.split(" ", 1)[0]


def register_protocol_handler(
    *,
    backend: RegistryBackend | None = None,
    frozen: bool | None = None,
    executable: str | None = None,
    script_path: Path | None = None,
) -> dict[str, Any]:
    """HKCU\\Software\\Classes\\virtualmouse 프로토콜을 등록한다 (UAC 불필요).

    대시보드에서 virtualmouse://start 를 호출하면 --from-uri 플래그로 에이전트를 기동한다.
    """
    if backend is None and not is_windows_supported():
        return {"ok": False, "supported": False, "scheme": PROTOCOL_SCHEME}

    reg = backend or _default_backend()
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    exe = executable or sys.executable
    command = build_launch_command(
        extra_args=("--from-uri",),
        frozen=is_frozen,
        executable=exe,
        script_path=script_path,
    )
    reg.set_value(PROTOCOL_KEY, "", "URL:VirtualMouse Agent Protocol")
    reg.set_value(PROTOCOL_KEY, "URL Protocol", "")
    if is_frozen:
        reg.set_value(PROTOCOL_ICON_KEY, "", f'"{exe}",0')
    reg.set_value(PROTOCOL_COMMAND_KEY, "", command)
    return {"ok": True, "supported": True, "scheme": PROTOCOL_SCHEME, "command": command}


def is_protocol_registered(
    *,
    backend: RegistryBackend | None = None,
    check_exists: bool | None = None,
) -> bool:
    """virtualmouse:// 프로토콜이 등록되어 있고 실행 대상이 유효한지 확인한다."""
    if backend is None and not is_windows_supported():
        return False
    reg = backend or _default_backend()
    if reg.get_value(PROTOCOL_KEY, "URL Protocol") is None:
        return False
    command = reg.get_value(PROTOCOL_COMMAND_KEY, "")
    if not command:
        return False
    exe = _extract_command_exe(command)
    if not exe:
        return False
    verify_disk = (backend is None) if check_exists is None else check_exists
    return os.path.isfile(exe) if verify_disk else True


def get_autostart(*, backend: RegistryBackend | None = None) -> bool:
    """Windows 로그인 시 자동 실행(HKCU\\...\\Run)이 켜져 있는지 확인한다."""
    if backend is None and not is_windows_supported():
        return False
    reg = backend or _default_backend()
    value = reg.get_value(RUN_KEY, RUN_VALUE_NAME)
    return bool(value and value.strip())


def set_autostart(
    enabled: bool,
    *,
    backend: RegistryBackend | None = None,
    frozen: bool | None = None,
    executable: str | None = None,
    script_path: Path | None = None,
) -> dict[str, Any]:
    """Windows 로그인 시 자동 실행(HKCU\\...\\Run)을 켜거나 끈다."""
    if backend is None and not is_windows_supported():
        raise OSError("Windows 시작 프로그램 등록은 Windows 환경에서만 지원됩니다.")
    reg = backend or _default_backend()
    if enabled:
        command = build_launch_command(
            extra_args=("--no-browser",),
            frozen=frozen,
            executable=executable,
            script_path=script_path,
        )
        reg.set_value(RUN_KEY, RUN_VALUE_NAME, command)
        return {"ok": True, "autostart_enabled": True, "command": command}
    try:
        reg.delete_value(RUN_KEY, RUN_VALUE_NAME)
    except FileNotFoundError:
        pass
    return {"ok": True, "autostart_enabled": False}
