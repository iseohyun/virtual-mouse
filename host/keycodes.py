"""
HID-Project KeyboardKeycode (USB HID Usage ID) 매핑 테이블.
Arduino Uno 16U2 펌웨어의 KP/KR/KT 명령은 USB HID Usage ID (uint8)를 받습니다.
"""

from __future__ import annotations

KEYCODES: dict[str, int] = {
    # Letters (a-z: 4..29)
    **{chr(ord("a") + i): 4 + i for i in range(26)},
    # Numbers (1-9: 30..38, 0: 39)
    "1": 30, "2": 31, "3": 32, "4": 33, "5": 34,
    "6": 35, "7": 36, "8": 37, "9": 38, "0": 39,
    # Control & navigation
    "enter": 40, "return": 40,
    "esc": 41, "escape": 41,
    "backspace": 42, "bs": 42,
    "tab": 43,
    "space": 44, " ": 44,
    "-": 45, "=": 46, "[": 47, "]": 48, "\\": 49,
    ";": 51, "'": 52, "`": 53, ",": 54, ".": 55, "/": 56,
    "capslock": 57,
    # Function keys (F1-F12: 58..69)
    **{f"f{i}": 57 + i for i in range(1, 13)},
    "printscreen": 70, "scrolllock": 71, "pause": 72,
    "insert": 73, "home": 74, "pageup": 75, "pgup": 75,
    "delete": 76, "del": 76, "end": 77, "pagedown": 78, "pgdn": 78,
    "right": 79, "left": 80, "down": 81, "up": 82,
    # Modifiers (0xE0..0xE7)
    "ctrl": 224, "lctrl": 224, "left_ctrl": 224,
    "shift": 225, "lshift": 225, "left_shift": 225,
    "alt": 226, "lalt": 226, "left_alt": 226,
    "win": 227, "gui": 227, "meta": 227, "cmd": 227, "lwin": 227,
    "rctrl": 228, "right_ctrl": 228,
    "rshift": 229, "right_shift": 229,
    "ralt": 230, "right_alt": 230, "hangul": 230,
    "rwin": 231, "rgui": 231,
}


def resolve_keycode(key: str | int) -> int:
    """키 이름(예: 'ctrl', 'enter', 'a') 또는 정수 HID Usage ID를 uint8 코드로 변환합니다."""
    if isinstance(key, int):
        if 0 <= key <= 255:
            return key
        raise ValueError(f"Keycode out of range: {key}")
    name = str(key).strip().lower()
    if name in KEYCODES:
        return KEYCODES[name]
    raise ValueError(f"Unknown key name: {key!r}")
