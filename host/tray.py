"""
VirtualMouse System Tray Icon (pystray + Pillow)

- 검정 바탕 둥근 사각형(RoundRect) + 흰 글씨 'VM' 아이콘 생성
- 우클릭 메뉴:
    * 대시보드 보기 (http://127.0.0.1:18080/guide)
    * 종료하기 (로컬 서버 안전 종료 후 트레이 종료)
"""

from __future__ import annotations

import threading
import webbrowser
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont
import pystray


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
    def __init__(self, dashboard_url: str, on_quit: Callable[[], None]):
        self.dashboard_url = dashboard_url
        self.on_quit = on_quit
        self._icon: pystray.Icon | None = None
        self._stopped = threading.Event()

    def _open_dashboard(self, icon=None, item=None) -> None:
        webbrowser.open(self.dashboard_url)

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
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("종료하기", self._quit_clicked),
        )
        self._icon = pystray.Icon("VirtualMouse", image, "VirtualMouse Agent", menu)
        self._icon.run()
