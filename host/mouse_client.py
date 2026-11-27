"""
VirtualMouse Host Client (Python)

Arduino Uno R3 (ATmega16U2) USB HID 마우스 + 키보드 펌웨어(v1.1.0+)와
시리얼 통신으로 상호작용하는 저수준 클라이언트 모듈입니다.

펌웨어는 줄('\\n') 단위로 명령을 읽습니다. 명령 문자열에 줄바꿈이 섞이면 뒤 글자가 새 명령(예: BOOT)으로
실행되므로, 이 모듈은 장치로 보내기 전에 모든 값을 검사합니다 (버튼, 좌표 범위, 키 코드, 글자).

사용처: dispatcher.py(ActionDispatcher), human_motion.py, updater.py(CLI)
"""

from __future__ import annotations

import time
import serial
import serial.tools.list_ports

VALID_BUTTONS = ("L", "R", "M")
INT16_MIN = -32768
INT16_MAX = 32767


def normalize_button(button: object) -> str:
    """마우스 버튼 값을 'L'/'R'/'M' 중 하나로 바꾼다. 그 밖의 값(줄바꿈이 섞인 값 포함)은 거부한다."""
    value = str(button).strip().upper()
    if value not in VALID_BUTTONS:
        raise ValueError(f"'button' must be one of L, R, M (got {button!r})")
    return value


def validate_int16(name: str, value: int) -> int:
    """펌웨어가 16비트 정수로 읽는 값(이동량 등)의 범위를 확인한다. 넘치면 반대 방향으로 움직이기 때문."""
    number = int(value)
    if not INT16_MIN <= number <= INT16_MAX:
        raise ValueError(f"'{name}' must be between {INT16_MIN} and {INT16_MAX}")
    return number


def validate_raw_text(text: str) -> None:
    """raw 타이핑(KW 명령 그대로)으로 보낼 수 있는 글자인지 확인한다: 제어 문자 없는 ASCII만."""
    if not text.isascii() or any(ch < " " or ch == "\x7f" for ch in text):
        raise ValueError(
            "raw 타이핑(\"human\": false)은 제어 문자(줄바꿈·탭 포함) 없는 ASCII 글자만 보낼 수 있습니다. "
            "줄바꿈·탭이 필요하면 human 모드를 쓰세요."
        )


def validate_human_text(text: str) -> str:
    """human 타이핑 전에 글 전체를 검사하고 줄바꿈을 정리한 값을 돌려준다 (일부만 입력되는 일을 막는다).

    - 줄바꿈(\\r\\n, \\r, \\n)은 Enter 키, 탭은 Tab 키로 입력된다.
    - 그 밖에는 ASCII 글자만 입력할 수 있다 (한글 등은 HID 키보드로 직접 입력하지 않는다).
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    bad = [ch for ch in normalized if ch not in "\n\t" and (not ch.isascii() or ch < " " or ch == "\x7f")]
    if bad:
        raise ValueError(
            "human 타이핑은 ASCII 글자와 줄바꿈·탭만 입력할 수 있습니다 "
            f"(지원하지 않는 글자 {len(bad)}개, 예: {bad[0]!r}). 아무것도 입력하지 않았습니다."
        )
    return normalized


def _validate_keycode(keycode: int) -> int:
    code = int(keycode)
    if not 0 <= code <= 255:
        raise ValueError(f"Keycode out of range: {keycode}")
    return code


ESP32_BRIDGE_HWIDS = (
    "VID:PID=10C4:EA60",  # Silicon Labs CP210x
    "VID:PID=1A86:7523",  # WCH CH340
    "VID:PID=1A86:55D4",  # WCH CH9102
    "VID:PID=303A:",      # Espressif native USB
)


def _open_serial_no_reset(port: str, baudrate: int, timeout: float) -> serial.Serial:
    """ESP32 는 DTR/RTS 를 기본값(True)으로 열면 자동 리셋되어 BLE 페어링이 끊긴다. 끄고 연다."""
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = baudrate
    ser.timeout = timeout
    ser.dtr = False
    ser.rts = False
    ser.open()
    return ser


def _is_esp32_hwid(hwid: str) -> bool:
    upper = (hwid or "").upper()
    return any(token in upper for token in ESP32_BRIDGE_HWIDS)


def _probe_esp32_firmware(port: str, baudrate: int = 115200, timeout: float = 0.8) -> bool:
    """CP210x/CH340 포트가 실제 VirtualMouse ESP32 펌웨어인지 리셋 없이 확인한다."""
    ser: serial.Serial | None = None
    try:
        ser = _open_serial_no_reset(port, baudrate=baudrate, timeout=timeout)
        time.sleep(0.08)
        ser.reset_input_buffer()
        ser.write(b"VER\n")
        ser.flush()
        resp = ser.readline().decode("ascii", errors="ignore").strip()
        return resp.startswith("VMOUSE_ESP32 ")
    except Exception:
        return False
    finally:
        if ser is not None and ser.is_open:
            try:
                ser.close()
            except Exception:
                pass


class VirtualMouse:
    def __init__(
        self,
        port: str | None = None,
        baudrate: int = 115200,
        timeout: float = 2.0,
        device_type: str | None = None,
    ):
        if port:
            self.port = port
            self.device_type = device_type or self._infer_device_type(port)
        else:
            found_port, found_type = self.find_device()
            self.port = found_port
            self.device_type = device_type or found_type or "uno"
        if not self.port:
            raise RuntimeError("VirtualMouse 장치(Arduino Uno 또는 ESP32 BLE) COM 포트를 찾을 수 없습니다.")
        if self.device_type == "esp32":
            self.ser = _open_serial_no_reset(self.port, baudrate=baudrate, timeout=timeout)
            time.sleep(0.1)
        else:
            self.ser = serial.Serial(self.port, baudrate=baudrate, timeout=timeout)
            time.sleep(0.3)
        self.ser.reset_input_buffer()

    @staticmethod
    def _infer_device_type(port: str) -> str:
        for p in serial.tools.list_ports.comports():
            if (p.device or "").upper() == port.upper():
                if _is_esp32_hwid(p.hwid or ""):
                    return "esp32"
                return "uno"
        return "uno"

    @staticmethod
    def find_device() -> tuple[str | None, str | None]:
        """연결된 VirtualMouse 장치(Arduino Uno 우선, 없으면 ESP32 BLE)를 자동 탐색한다."""
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            hwid = (p.hwid or "").upper()
            if "VID:PID=2341:484C" in hwid:
                return p.device, "uno"
        for p in ports:
            desc = (p.description or "").lower()
            hwid = (p.hwid or "").upper()
            if "hoodloader" in desc or "VID:PID=03EB:204A" in hwid:
                return p.device, "uno"
        for p in ports:
            if _is_esp32_hwid(p.hwid or "") and _probe_esp32_firmware(p.device):
                return p.device, "esp32"
        return None, None

    @staticmethod
    def find_device_port() -> str | None:
        """VirtualMouse (Arduino Uno 또는 ESP32 BLE) 시리얼 포트를 자동 탐색합니다."""
        port, _ = VirtualMouse.find_device()
        return port

    def _send(self, command: str) -> str:
        if "\n" in command or "\r" in command:
            raise ValueError("Device command must be a single line")
        # 앞선 명령의 늦게 도착한 응답이 남아 있으면 응답이 한 줄씩 밀리므로, 보내기 전에 비운다
        self.ser.reset_input_buffer()
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
        if resp.startswith("VMOUSE_ESP32 "):
            self.device_type = "esp32"
            return resp.split(" ", 1)[1].strip()
        if resp.startswith("VMOUSE "):
            return resp.split(" ", 1)[1].strip()
        return None

    def ble_status(self) -> str | None:
        """ESP32 BLE 연결 상태(CONNECTED / ADVERTISING)를 조회한다."""
        if getattr(self, "device_type", "uno") != "esp32":
            return None
        resp = self._send("BLE").upper()
        if resp in ("CONNECTED", "ADVERTISING"):
            return resp
        return None

    def demo(self) -> bool:
        """ESP32 BLE 마우스 사각형 이동 데모를 실행한다."""
        if getattr(self, "device_type", "uno") != "esp32":
            raise RuntimeError("BT 사각형 데모는 ESP32 BLE 장치에서만 지원됩니다.")
        resp = self._send("DEMO")
        if resp == "ERR_NOT_CONNECTED":
            # 펌웨어가 ERR_NOT_CONNECTED 뒤에 OK 를 한 줄 더 보내므로 버퍼를 비운다
            try:
                self.ser.readline()
            except Exception:
                pass
            raise RuntimeError("스마트폰과 블루투스(VirtualMouse BLE)가 연결되어 있지 않습니다. 먼저 페어링해 주세요.")
        if resp != "OK":
            raise RuntimeError(f"DEMO 명령 실패: {resp!r}")
        return True

    def enter_bootloader(self) -> bool:
        resp = self._send("BOOT")
        return resp == "BOOTING"

    # --- Mouse ---
    def move(self, dx: int, dy: int) -> None:
        self._send_ok(f"M {validate_int16('dx', dx)} {validate_int16('dy', dy)}")

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
        self._send_ok(f"C {normalize_button(button)}")

    def press(self, button: str = "L") -> None:
        self._send_ok(f"P {normalize_button(button)}")

    def release(self, button: str = "L") -> None:
        self._send_ok(f"R {normalize_button(button)}")

    def scroll(self, delta: int) -> None:
        self._send_ok(f"W {validate_int16('delta', delta)}")

    # --- Keyboard ---
    def key_press(self, keycode: int) -> None:
        self._send_ok(f"KP {_validate_keycode(keycode)}")

    def key_release(self, keycode: int) -> None:
        self._send_ok(f"KR {_validate_keycode(keycode)}")

    def key_tap(self, keycode: int) -> None:
        self._send_ok(f"KT {_validate_keycode(keycode)}")

    def key_write_text(self, text: str) -> None:
        validate_raw_text(text)
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
