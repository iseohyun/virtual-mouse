"""
VirtualMouse System Tray Icon (pystray + Pillow)

- 검정 바탕 둥근 사각형(RoundRect) + 흰 글씨 'VM' 아이콘 생성
- 우클릭 메뉴:
    * 대시보드 보기 (http://127.0.0.1:18080/guide, API 토큰을 # 뒤에 담아 자동 로그인)
    * 비상 정지 (진행 중·대기 중인 동작을 끊고 눌린 버튼·키를 모두 해제)
    * API 토큰 복사 (공개 대시보드·외부 스크립트에 붙여 넣기용)
    * 종료하기 (로컬 서버 안전 종료 후 트레이 종료)
"""

from __future__ import annotations

import os
import subprocess
import threading
import webbrowser
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont
import pystray

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _clip_exe() -> str:
    """이름만으로 실행하면 exe 옆(다운로드 폴더 등)에 심어 둔 같은 이름의 파일이 먼저 실행될 수 있어 시스템 경로를 쓴다."""
    path = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "clip.exe")
    return path if os.path.isfile(path) else "clip"


def copy_to_clipboard(text: str) -> bool:
    """Windows 기본 clip.exe 로 클립보드에 복사한다 (토큰은 ASCII라 인코딩 문제가 없다)."""
    try:
        subprocess.run([_clip_exe()], input=text, text=True, check=True, creationflags=_NO_WINDOW, timeout=5)
        return True
    except Exception:
        return False


def create_vm_icon_image(size: int = 64) -> Image.Image:
    """검정 바탕 RoundRect에 흰색 'VM' 글자가 들어간 아이콘 이미지를 생성합니다."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = max(2, size // 16)
    radius = max(8, size // 4)
    draw.rounded_rectangle(
        [(pad, pad), (size - pad - 1, size - pad - 1)],
        radius=radius,
        fill=(11, 17, 32, 255),
        outline=(56, 189, 248, 220),
        width=max(2, size // 24),
    )

    text = "VM"
    font = None
    font_size = int(size * 0.44)
    for font_name in ("segoeuib.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            font = ImageFont.truetype(font_name, font_size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (size - tw) / 2 - bbox[0]
    ty = (size - th) / 2 - bbox[1]
    draw.text((tx, ty), text, fill=(255, 255, 255, 255), font=font)
    return img


def save_vm_ico(dest: Path) -> Path:
    """PyInstaller --icon용 .ico 파일을 생성합니다."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    base = create_vm_icon_image(256)
    base.save(dest, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return dest


class TrayController:
    def __init__(
        self,
        dashboard_url: str,
        on_quit: Callable[[], None],
        api_token: str | None = None,
        on_emergency_stop: Callable[[], None] | None = None,
    ):
        self.dashboard_url = dashboard_url
        self.on_quit = on_quit
        self.api_token = api_token
        self.on_emergency_stop = on_emergency_stop
        self._icon: pystray.Icon | None = None
        self._stopped = threading.Event()

    def _open_dashboard(self, icon=None, item=None) -> None:
        webbrowser.open(self.dashboard_url)

    def _emergency_stop(self, icon=None, item=None) -> None:
        if self.on_emergency_stop is not None:
            self.on_emergency_stop()

    def _copy_token(self, icon=None, item=None) -> None:
        if not self.api_token:
            return
        ok = copy_to_clipboard(self.api_token)
        if self._icon is not None:
            try:
                self._icon.notify(
                    "API 토큰을 클립보드에 복사했습니다." if ok else "토큰 복사에 실패했습니다. 'vm token'으로 확인하세요.",
                    "VirtualMouse",
                )
            except Exception:
                pass

    def _quit_clicked(self, icon=None, item=None) -> None:
        self.stop()
        self.on_quit()

    def stop(self) -> None:
        if not self._stopped.is_set():
            self._stopped.set()
            if self._icon is not None:
                try:
                    self._icon.stop()
                except Exception:
                    pass

    def run(self) -> None:
        image = create_vm_icon_image(64)
        menu = pystray.Menu(
            pystray.MenuItem("대시보드 보기", self._open_dashboard, default=True),
            pystray.MenuItem("비상 정지 (입력 모두 해제)", self._emergency_stop, enabled=self.on_emergency_stop is not None),
            pystray.MenuItem("API 토큰 복사", self._copy_token, enabled=bool(self.api_token)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("종료하기", self._quit_clicked),
        )
        self._icon = pystray.Icon("VirtualMouse", image, "VirtualMouse Agent", menu)
        self._icon.run()
