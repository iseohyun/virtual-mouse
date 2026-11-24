"""
테스트 공용 도구 (실제 Arduino·USB·화면 커서에는 절대 접근하지 않는다).

- host/ 폴더를 import 경로에 넣는다.
- FakeVirtualMouse: mouse_client.VirtualMouse 대역. 보낸 명령만 기록한다.
- make_fake_dispatcher(): 가짜 장치로 연결된 실제 ActionDispatcher 를 만든다.
- ApiServer: http_api.make_handler 로 만든 서버를 임의 포트에 띄우고 요청을 보낸다.

실행: python -m unittest discover -s tests -v   (저장소 루트에서)
"""

from __future__ import annotations

import http.client
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
HOST_DIR = REPO_ROOT / "host"
if str(HOST_DIR) not in sys.path:
    sys.path.insert(0, str(HOST_DIR))

import dispatcher as dispatcher_mod  # noqa: E402
import human_motion  # noqa: E402
from mouse_client import normalize_button, validate_int16, validate_raw_text  # noqa: E402

TEST_TOKEN = "test-token-0123456789abcdefghijklmnopqrstuv"


class FakeVirtualMouse:
    """실제 시리얼 포트를 열지 않는 VirtualMouse 대역.

    - 실제 클라이언트와 같은 값 검사(버튼, 16비트 범위, raw 글자)를 거친다.
    - 펌웨어는 줄 단위로 명령을 읽으므로, 줄바꿈이 섞인 명령이 장치에 닿으면 테스트를 실패시킨다.
    - 상대 이동을 가짜 커서(FakeVirtualMouse.cursor)에 반영해 move_to/click_at 도 실제 커서 없이 동작한다.
    - ping_script 에 값을 넣으면 ping() 이 그 순서대로 결과를 돌려준다 (연결 끊김 흉내).
    """

    cursor = [100, 200]
    ping_script: list = []
    instances: list = []

    def __init__(self, port: str | None = None, *args: Any, **kwargs: Any):
        self.port = port or "FAKE0"
        self.commands: list[str] = []
        self.closed = False
        FakeVirtualMouse.instances.append(self)

    def _record(self, command: str) -> None:
        if "\n" in command or "\r" in command:
            raise AssertionError(f"newline reached the device: {command!r}")
        if self.closed:
            raise AssertionError("command sent to a closed port")
        self.commands.append(command)

    def ping(self) -> bool:
        if FakeVirtualMouse.ping_script:
            return FakeVirtualMouse.ping_script.pop(0)
        return not self.closed

    def version(self) -> str:
        return "1.1.0"

    def close(self) -> None:
        self.closed = True

    def enter_bootloader(self) -> bool:
        self._record("BOOT")
        return True

    def move(self, dx: int, dy: int) -> None:
        dx, dy = validate_int16("dx", dx), validate_int16("dy", dy)
        FakeVirtualMouse.cursor[0] += dx
        FakeVirtualMouse.cursor[1] += dy
        self._record(f"M {dx} {dy}")

    def click(self, button: str = "L") -> None:
        self._record(f"C {normalize_button(button)}")

    def press(self, button: str = "L") -> None:
        self._record(f"P {normalize_button(button)}")

    def release(self, button: str = "L") -> None:
        self._record(f"R {normalize_button(button)}")

    def scroll(self, delta: int) -> None:
        self._record(f"W {validate_int16('delta', delta)}")

    def key_press(self, code: int) -> None:
        self._record(f"KP {int(code)}")

    def key_release(self, code: int) -> None:
        self._record(f"KR {int(code)}")

    def key_tap(self, code: int) -> None:
        self._record(f"KT {int(code)}")

    def key_write_text(self, text: str) -> None:
        validate_raw_text(text)  # 실제 클라이언트와 같은 검사
        self._record(f"KW {text}")

    def key_release_all(self) -> None:
        self._record("KA")

    def release_all(self) -> None:
        self._record("X")


def _fake_cursor() -> tuple[int, int]:
    return FakeVirtualMouse.cursor[0], FakeVirtualMouse.cursor[1]


def make_fake_dispatcher(testcase) -> "dispatcher_mod.ActionDispatcher":
    """가짜 장치·가짜 커서로 동작하는 ActionDispatcher. 패치는 테스트가 끝나면 자동으로 되돌린다."""
    FakeVirtualMouse.cursor = [100, 200]
    FakeVirtualMouse.ping_script = []
    FakeVirtualMouse.instances = []
    patches = [
        mock.patch.object(dispatcher_mod, "VirtualMouse", FakeVirtualMouse),
        mock.patch.object(dispatcher_mod, "enable_dpi_awareness", lambda: None),
        mock.patch.object(dispatcher_mod, "get_cursor_pos_safe", _fake_cursor),
        # 실제 화면 커서를 절대 읽지 않게 human_motion 쪽도 바꾼다
        mock.patch.object(human_motion, "get_cursor_pos", _fake_cursor),
    ]
    for p in patches:
        p.start()
        testcase.addCleanup(p.stop)
    return dispatcher_mod.ActionDispatcher(port="FAKE0", logger=dispatcher_mod.LogBuffer(echo=False))


class FakeDispatcher:
    """HTTP 계층 테스트용: 호출만 기록한다."""

    def __init__(self) -> None:
        self.logger = dispatcher_mod.LogBuffer(echo=False)
        self.calls: list[Any] = []

    def health(self) -> dict:
        self.calls.append("health")
        return {"ok": True}

    def status(self) -> dict:
        self.calls.append("status")
        return {"state": "ready", "paused": False}

    def execute_payload(self, payload: dict) -> dict:
        self.calls.append(("action", payload))
        return {"ok": True, "result": payload}

    def check_firmware(self) -> dict:
        self.calls.append("check_firmware")
        return {"ok": True}

    def update_firmware(self, payload: dict) -> dict:
        self.calls.append(("update_firmware", payload))
        return {"ok": True, "updated": False}

    def pause(self) -> dict:
        self.calls.append("pause")
        return {"ok": True, "paused": True}

    def resume(self) -> dict:
        self.calls.append("resume")
        return {"ok": True, "paused": False}


class ApiServer:
    """http_api 처리기를 임의 포트에 띄운다 (127.0.0.1 전용)."""

    def __init__(self, dispatcher: Any, token: str | None = TEST_TOKEN):
        from http_api import make_handler

        self.quit_requests = 0
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        self.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = make_handler(dispatcher, self._on_quit, self.port, token=token)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def _on_quit(self) -> None:
        self.quit_requests += 1

    def request(
        self,
        method: str,
        path: str,
        body: bytes | str | None = None,
        headers: dict[str, str] | None = None,
        host: str | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        all_headers = {"Host": host or f"127.0.0.1:{self.port}"}
        all_headers.update(headers or {})
        conn.request(method, path, body=body, headers=all_headers)
        resp = conn.getresponse()
        data = resp.read()
        result_headers = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, result_headers, data

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
