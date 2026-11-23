"""
VirtualMouse Host Client (Python)

Arduino Uno R3 (ATmega16U2) USB HID 마우스 + 키보드 펌웨어(v1.1.0+)와
시리얼 통신으로 상호작용하는 저수준 클라이언트 모듈입니다.
"""

from __future__ import annotations

import time
import serial
import serial.tools.list_ports


class VirtualMouse:
    def __init__(self, port: str | None = None, baudrate: int = 115200, timeout: float = 2.0):
        self.port = port or self.find_device_port()
        if not self.port:
            raise RuntimeError("VirtualMouse (VID_2341&PID_484C) COM 포트를 찾을 수 없습니다.")
        self.ser = serial.Serial(self.port, baudrate=baudrate, timeout=timeout)
        time.sleep(0.3)
        self.ser.reset_input_buffer()

    @staticmethod
    def find_device_port() -> str | None:
        """VirtualMouse (VID:PID=2341:484C) 시리얼 포트를 자동 탐색합니다."""
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            hwid = (p.hwid or "").upper()
            if "VID:PID=2341:484C" in hwid:
                return p.device
        for p in ports:
            desc = (p.description or "").lower()
            hwid = (p.hwid or "").upper()
            if "hoodloader" in desc or "VID:PID=03EB:204A" in hwid:
                return p.device
        return None

    def _send(self, command: str) -> str:
        self.ser.write((command + "\n").encode("ascii"))
        self.ser.flush()
        return self.ser.readline().decode("ascii", errors="ignore").strip()

    def _send_ok(self, command: str) -> None:
        resp = self._send(command)
        if resp != "OK":
            raise RuntimeError(f"Command {command!r} failed: {resp!r}")

    def ping(self) -> bool:
        return self._send("PING") == "PONG"

    def version(self) -> str | None:
        resp = self._send("VER")
        if resp.startswith("VMOUSE "):
            return resp.split(" ", 1)[1].strip()
        return None

    def enter_bootloader(self) -> bool:
        resp = self._send("BOOT")
        return resp == "BOOTING"

    # --- Mouse ---
    def move(self, dx: int, dy: int) -> None:
        self._send_ok(f"M {int(dx)} {int(dy)}")

    def move_smooth(self, dx: int, dy: int, steps: int = 20, duration: float = 0.2) -> None:
        if steps <= 1:
            self.move(dx, dy)
            return
        sent_x = 0
        sent_y = 0
        delay = duration / steps
        for i in range(1, steps + 1):
            target_x = round(dx * i / steps)
            target_y = round(dy * i / steps)
            step_x = target_x - sent_x
            step_y = target_y - sent_y
            if step_x != 0 or step_y != 0:
                self.move(step_x, step_y)
                sent_x += step_x
                sent_y += step_y
            time.sleep(delay)

    def click(self, button: str = "L") -> None:
        self._send_ok(f"C {button.upper()}")

    def press(self, button: str = "L") -> None:
        self._send_ok(f"P {button.upper()}")

    def release(self, button: str = "L") -> None:
        self._send_ok(f"R {button.upper()}")

    def scroll(self, delta: int) -> None:
        self._send_ok(f"W {int(delta)}")

    # --- Keyboard ---
    def key_press(self, keycode: int) -> None:
        self._send_ok(f"KP {int(keycode)}")

    def key_release(self, keycode: int) -> None:
        self._send_ok(f"KR {int(keycode)}")

    def key_tap(self, keycode: int) -> None:
        self._send_ok(f"KT {int(keycode)}")

    def key_write_text(self, text: str) -> None:
        # 펌웨어는 줄 단위로 명령을 읽는다. 줄바꿈이 섞이면 뒤 글자가 새 명령(예: BOOT)으로 실행되므로 막는다.
        # 줄바꿈·탭은 human 모드(type_human)가 enter/tab 키로 바꿔 보낸다.
        if not text.isascii() or any(ch < " " or ch == "\x7f" for ch in text):
            raise ValueError("raw 타이핑은 제어 문자(줄바꿈 포함) 없는 ASCII만 보낼 수 있습니다. human 모드를 쓰세요.")
        # Firmware buffer is 48 bytes; send safely in chunks <= 32 chars
        for i in range(0, len(text), 32):
            chunk = text[i : i + 32]
            self._send_ok(f"KW {chunk}")

    def key_release_all(self) -> None:
        self._send_ok("KA")

    def release_all(self) -> None:
        self._send("X")

    def close(self) -> None:
        if self.ser and self.ser.is_open:
            self.ser.close()

    def __enter__(self) -> "VirtualMouse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.release_all()
        finally:
            self.close()
