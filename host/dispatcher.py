"""
VirtualMouse 액션 실행기 (ActionDispatcher) 와 서버 로그 버퍼 (LogBuffer).

- Arduino COM 포트를 한 번에 한 요청만 쓰도록 잠그고, 끊기면 자동으로 다시 연결한다.
- JSON 액션(move, click_at, type, hotkey 등)을 사람 움직임 엔진(human_motion)으로 실행한다.
- 한 요청이 에이전트를 오래 붙잡지 못하게 상한을 두고, release_all 은 진행 중인 동작을 끊고 즉시 실행한다.
- 로그에는 타이핑한 글자를 남기지 않는다 (redact_action_for_log).

사용처: server.py(생성), http_api.py(요청 처리)
의존: mouse_client, human_motion, keycodes, device_status, updater
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
import json
import sys
import threading
from typing import Any, Dict

from device_status import EXPECTED_FW_VERSION, detect_device_state
from human_motion import ActionAborted, HumanMouseController, enable_dpi_awareness, get_cursor_pos_safe
from keycodes import resolve_keycode
from mouse_client import VirtualMouse, normalize_button, validate_int16
from updater import (
    DEFAULT_MANIFEST_URL,
    check_for_update,
    download_and_verify_firmware,
    find_local_hex,
    flash_hex_via_dfu,
    wait_for_dfu_ready,
)

__all__ = [
    "ActionAborted",
    "ActionDispatcher",
    "EMERGENCY_ACTIONS",
    "LogBuffer",
    "MAX_ACTIONS_PER_REQUEST",
    "MAX_MOVE_DURATION_SEC",
    "MAX_SCROLL_TICKS",
    "MAX_SLEEP_MS",
    "MAX_TYPE_CHARS",
    "UpdateInProgress",
    "redact_action_for_log",
]


# 한 요청이 에이전트를 오래 붙잡지 못하게 하는 상한
MAX_SLEEP_MS = 10_000
MAX_ACTIONS_PER_REQUEST = 200
MAX_TYPE_CHARS = 2_000
MAX_SCROLL_TICKS = 100
MAX_MOVE_DURATION_SEC = 5.0
MAX_HOTKEY_KEYS = 8
STATUS_LOCK_WAIT_SEC = 0.5  # /status·/health 가 긴 동작을 기다리는 최대 시간
EMERGENCY_ACTIONS = {"release_all", "key_release_all"}

# 로그에 그대로 남겨도 되는 키 이름 (한 글자 키는 타이핑 내용이 드러나므로 가린다)
_KEY_ACTIONS = {"key_tap", "key_press", "key_release"}
# Ctrl·Alt·Win이 들어간 조합은 단축키(ctrl+c 등)이므로 로그에 그대로 남긴다. Shift+글자는 타이핑으로 보고 가린다.
_SHORTCUT_MODIFIERS = {
    "ctrl", "lctrl", "left_ctrl", "rctrl", "right_ctrl",
    "alt", "lalt", "left_alt", "ralt", "right_alt",
    "win", "gui", "meta", "cmd", "lwin", "rwin", "rgui",
}


def _redact_key(key: Any) -> Any:
    if isinstance(key, str) and len(key.strip()) == 1:
        return "<char>"
    if isinstance(key, int) and 4 <= key <= 56:  # HID 문자·숫자·기호 키
        return "<char>"
    return key


def redact_action_for_log(cmd: Dict[str, Any]) -> Dict[str, Any]:
    """서버 로그(대시보드 로그 탭·로그 복사)에 비밀번호 같은 입력 내용이 남지 않게 가린 사본을 만든다."""
    if not isinstance(cmd, dict):
        return {"action": "<invalid>"}
    safe = dict(cmd)
    action = str(safe.get("action", "")).strip().lower()
    if "text" in safe:
        safe["text"] = f"<{len(str(safe['text']))} chars>"
    if action in _KEY_ACTIONS and "key" in safe:
        safe["key"] = _redact_key(safe["key"])
    if action == "hotkey" and isinstance(safe.get("keys"), list):
        keys = safe["keys"]
        is_shortcut = any(str(k).strip().lower() in _SHORTCUT_MODIFIERS for k in keys)
        safe["keys"] = list(keys) if is_shortcut else [_redact_key(k) for k in keys]
    return safe


class UpdateInProgress(RuntimeError):
    """펌웨어 업데이트가 이미 진행 중이라 새 요청을 받지 않음 (HTTP 409)."""


class LogBuffer:
    """스레드 안전한 서버 로그 링 버퍼 (대시보드 로그 탭에 표시)."""

    def __init__(self, maxlen: int = 250, echo: bool = True):
        self._entries: deque[str] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._echo = echo  # 콘솔(--no-tray) 실행 시 화면에도 출력. --noconsole exe 에서는 stdout 이 없어 건너뛴다

    def add(self, message: str, level: str = "INFO") -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] [{level}] {message}"
        with self._lock:
            self._entries.append(line)
        if self._echo and sys.stdout is not None:
            try:
                print(line, flush=True)
            except Exception:
                pass

    def list_lines(self) -> list[str]:
        with self._lock:
            return list(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class ActionDispatcher:
    """COM 포트에 대한 스레드 안전한 단일 접근, 자동 재연결, 일시 중지 및 JSON 액션 실행기."""

    def __init__(
        self,
        port: str | None = None,
        expected_version: str = EXPECTED_FW_VERSION,
        logger: LogBuffer | None = None,
    ):
        enable_dpi_awareness()
        self.preferred_port = port
        self.expected_version = expected_version
        self.logger = logger or LogBuffer()
        self.mouse: VirtualMouse | None = None
        self.human: HumanMouseController | None = None
        self.paused: bool = False
        self._lock = threading.Lock()
        # 비상 정지: 진행 중인 동작 루프가 이 신호를 보고 중단한 뒤 잠금을 놓는다
        self._abort = threading.Event()
        # 정지 세대 번호: 정지(비상 정지·일시 중지·종료·플래싱) 전에 줄 서 있던 요청을 취소하는 데 쓴다.
        # 잠금 순서: _lock -> _stop_lock (반대로 잡지 않는다)
        self._stop_lock = threading.Lock()
        self._stop_generation = 0
        self._update_lock = threading.Lock()
        self._closed = False  # 종료 중: 아직 플래싱을 시작하지 않은 업데이트는 취소한다
        self._last_status: Dict[str, Any] | None = None
        self._last_connect_error: str | None = None
        self._try_connect()

    # --- 정지 제어 ---
    def _request_stop(self) -> None:
        """진행 중인 동작을 끊고, 이 시점 전에 들어와 기다리던 요청도 모두 취소되게 한다."""
        with self._stop_lock:
            self._stop_generation += 1
            self._abort.set()

    def _current_generation(self) -> int:
        with self._stop_lock:
            return self._stop_generation

    def _begin_request(self, generation: int) -> None:
        """잠금을 얻은 직후 호출한다. 기다리는 동안 정지 요청이 있었으면 실행하지 않는다."""
        with self._stop_lock:
            if generation != self._stop_generation:
                raise ActionAborted("비상 정지(또는 일시 중지) 전에 들어온 요청이라 실행하지 않았습니다.")
            self._abort.clear()

    def _clear_stop_signal(self) -> None:
        with self._stop_lock:
            self._abort.clear()

    def _try_connect(self) -> bool:
        if self.paused:
            return False
        if self.mouse is not None:
            try:
                if self.mouse.ping():
                    return True
            except Exception:
                pass
            # ping 실패(시간 초과·응답 밀림 포함): 옛 핸들을 닫아야 같은 COM 포트를 다시 열 수 있다
            self._disconnect_unlocked()

        try:
            vm = VirtualMouse(port=self.preferred_port)
        except Exception as exc:
            self._note_connect_error(exc)
            return False
        try:
            if vm.ping():
                self.mouse = vm
                self.human = HumanMouseController(vm, abort_event=self._abort)
                self._last_connect_error = None
                self.logger.add(f"Arduino 연결됨 ({vm.port})")
                return True
            self._note_connect_error("PING 응답 없음")
        except Exception as exc:
            self._note_connect_error(exc)
        try:
            vm.close()
        except Exception:
            pass
        return False

    def _note_connect_error(self, exc: object) -> None:
        """연결 실패 원인을 기록한다 (같은 원인은 한 번만 로그에 남겨 폴링마다 쌓이지 않게)."""
        message = str(exc) or exc.__class__.__name__
        if message != self._last_connect_error:
            self._last_connect_error = message
            self.logger.add(f"Arduino 연결 실패: {message}", "WARN")

    def _disconnect_unlocked(self) -> None:
        if self.mouse is not None:
            port = self.mouse.port
            try:
                self.mouse.close()
            except Exception:
                pass
            self.logger.add(f"Arduino 연결 해제됨 ({port})")
        self.mouse = None
        self.human = None

    def pause(self) -> Dict[str, Any]:
        self._request_stop()  # 진행 중·대기 중인 동작을 먼저 끊는다
        with self._lock:
            self._clear_stop_signal()
            self.paused = True
            if self.mouse is not None:
                try:
                    self.mouse.release_all()
                except Exception:
                    pass
            self._disconnect_unlocked()
            self.logger.add("로컬 제어 서비스 일시 중지됨", "WARN")
            return {"ok": True, "paused": True, "running": False}

    def resume(self) -> Dict[str, Any]:
        with self._lock:
            self.paused = False
            connected = self._try_connect()
            self.logger.add(f"로컬 제어 서비스 재개됨 (connected={connected})")
            return {"ok": True, "paused": False, "running": True, "connected": connected}

    def _require_connected(self) -> tuple[VirtualMouse, HumanMouseController]:
        if self.paused:
            raise RuntimeError("서비스가 일시 중지 상태입니다. 대시보드 [구동/로그] 탭에서 시작해 주세요.")
        if not self._try_connect() or self.mouse is None or self.human is None:
            raise RuntimeError("VirtualMouse 장치가 연결되어 있지 않습니다. /status로 장치 상태를 확인하세요.")
        return self.mouse, self.human

    @staticmethod
    def _cursor_dict() -> Dict[str, int] | None:
        pos = get_cursor_pos_safe()
        return {"x": pos[0], "y": pos[1]} if pos is not None else None

    def _busy_snapshot(self) -> Dict[str, Any]:
        """다른 동작이 장치를 쓰는 중일 때 돌려주는 마지막 상태 (커서 좌표는 장치 없이 읽는다)."""
        snapshot = dict(self._last_status or {"state": "busy"})
        snapshot.update({"busy": True, "paused": self.paused, "running": not self.paused, "cursor": self._cursor_dict()})
        return snapshot

    def health(self) -> Dict[str, Any]:
        if not self._lock.acquire(timeout=STATUS_LOCK_WAIT_SEC):
            snapshot = self._busy_snapshot()
            return {
                "ok": True,
                "busy": True,
                "paused": snapshot["paused"],
                "running": snapshot["running"],
                "port": snapshot.get("port"),
                "firmware_version": snapshot.get("firmware_version"),
                "cursor": snapshot["cursor"],
            }
        try:
            connected = self._try_connect()
            ver = self.mouse.version() if connected and self.mouse else None
            return {
                "ok": connected,
                "busy": False,
                "paused": self.paused,
                "running": not self.paused,
                "port": self.mouse.port if connected and self.mouse else None,
                "firmware_version": ver,
                "cursor": self._cursor_dict(),
            }
        finally:
            self._lock.release()

    def status(self) -> Dict[str, Any]:
        # 긴 동작(타이핑·플래싱) 중에는 잠금을 잠깐만 기다리고, 못 얻으면 마지막 상태를 busy 로 돌려준다
        if not self._lock.acquire(timeout=STATUS_LOCK_WAIT_SEC):
            return self._busy_snapshot()
        try:
            connected = self._try_connect()
            port = self.mouse.port if connected and self.mouse else None
            ver = self.mouse.version() if connected and self.mouse else None
            paused = self.paused
            expected = self.expected_version
            connect_error = None if connected else self._last_connect_error
        finally:
            self._lock.release()
        # USB PnP 조회는 락 밖에서 실행 (다른 요청 블로킹 방지)
        info = detect_device_state(
            connected_port=port,
            firmware_version=ver,
            expected_version=expected,
            paused=paused,
        )
        info["paused"] = paused
        info["running"] = not paused
        info["busy"] = False
        info["connect_error"] = connect_error
        self._last_status = dict(info)
        info["cursor"] = self._cursor_dict()
        return info

    def check_firmware(self) -> Dict[str, Any]:
        with self._lock:
            connected = self._try_connect()
            ver = self.mouse.version() if connected and self.mouse else None
        # 네트워크 조회는 잠금 밖에서: 느린 네트워크가 마우스·키보드 동작과 비상 정지를 막지 않게
        info = check_for_update(ver, manifest_url=DEFAULT_MANIFEST_URL)
        info["ok"] = True
        self.logger.add(f"펌웨어 버전 확인: current={ver}, remote={info['remote_version']}")
        return info

    def update_firmware(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """펌웨어를 받아(또는 번들 .hex) 검증한 뒤 DFU 로 플래싱한다.

        - 동시에 두 번 실행하지 않는다 (UpdateInProgress -> HTTP 409).
        - 매니페스트 조회·다운로드는 잠금 밖에서, 플래싱만 장치를 독점한 채 잠금 안에서 한다.
        - 요청의 manifest_url 은 무시한다: 공격자가 자기 매니페스트·해시로 임의 펌웨어를 심을 수 있기 때문.
          다른 릴리즈 서버가 필요하면 에이전트 실행 환경의 VMOUSE_MANIFEST_URL 로만 바꾼다.
        """
        if not self._update_lock.acquire(blocking=False):
            raise UpdateInProgress("이미 펌웨어 업데이트가 진행 중입니다.")
        try:
            use_local = bool(payload.get("use_local", False))
            force = bool(payload.get("force", False))
            dry_run = bool(payload.get("dry_run", False))

            with self._lock:
                connected = self._try_connect()
                current_ver = self.mouse.version() if connected and self.mouse else None

            if use_local:
                hex_path = find_local_hex()
                if hex_path is None:
                    raise FileNotFoundError("로컬 펌웨어 .hex 파일을 찾을 수 없습니다.")
                target_ver = self.expected_version
                if dry_run:
                    return {
                        "ok": True,
                        "dry_run": True,
                        "source": "local",
                        "hex": str(hex_path),
                        "target_version": target_ver,
                    }
            else:
                info = check_for_update(current_ver, manifest_url=DEFAULT_MANIFEST_URL)
                target_ver = info["remote_version"]
                if not info["update_available"] and not force:
                    return {
                        "ok": True,
                        "updated": False,
                        "message": "Already up to date",
                        "current_version": current_ver,
                        "remote_version": target_ver,
                    }
                hex_path = download_and_verify_firmware(info["firmware_url"], info["sha256"])
                if dry_run:
                    return {
                        "ok": True,
                        "dry_run": True,
                        "verified_sha256": info["sha256"],
                        "hex": str(hex_path),
                        "current_version": current_ver,
                        "target_version": target_ver,
                    }

            # 플래싱은 장치를 독점한다: 진행 중·대기 중인 동작을 먼저 멈춘다
            self._request_stop()
            with self._lock:
                self._clear_stop_signal()
                if self._closed:
                    raise RuntimeError("에이전트 종료 중이라 펌웨어 업데이트를 취소했습니다 (장치는 바뀌지 않았습니다).")
                connected = self._try_connect()
                self.logger.add(f"펌웨어 플래싱 시작 (target={target_ver})")
                if connected and self.mouse is not None:
                    self.mouse.enter_bootloader()
                    self._disconnect_unlocked()
                    if not wait_for_dfu_ready(timeout=8.0):
                        raise RuntimeError("BOOT 명령 후 DFU 장치가 감지되지 않았습니다.")
                else:
                    if not wait_for_dfu_ready(timeout=2.0):
                        raise RuntimeError("DFU 모드가 아닙니다. 점퍼 2핀을 1초간 접촉해 DFU 모드로 진입해 주세요.")

                result = flash_hex_via_dfu(hex_path)
                result["updated"] = True
                result["target_version"] = target_ver
                self.logger.add("펌웨어 플래싱 성공! USB 재연결 대기 중")
                return result
        finally:
            self._update_lock.release()

    @staticmethod
    def _is_emergency(payload: Dict[str, Any]) -> bool:
        return str(payload.get("action", "")).strip().lower() in EMERGENCY_ACTIONS and "actions" not in payload

    def execute_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        if self._is_emergency(payload):
            # 진행 중인 긴 동작(타이핑·스크롤·대기)을 끊고, 그 전에 줄 서 있던 요청도 취소한 뒤
            # 잠금을 얻는 즉시 모든 입력을 해제한다
            self._request_stop()
            with self._lock:
                self._clear_stop_signal()
                return {"ok": True, "result": self._execute_one(payload)}

        generation = self._current_generation()
        with self._lock:
            self._begin_request(generation)
            if "actions" in payload:
                actions = payload["actions"]
                if not isinstance(actions, list):
                    raise ValueError("'actions' must be a list")
                if len(actions) > MAX_ACTIONS_PER_REQUEST:
                    raise ValueError(f"'actions' may contain at most {MAX_ACTIONS_PER_REQUEST} items")
                results = []
                for item in actions:
                    if self._abort.is_set():
                        raise ActionAborted("비상 정지 요청으로 남은 동작을 취소했습니다.")
                    results.append(self._execute_one(item))
                return {"ok": True, "results": results}
            result = self._execute_one(payload)
            return {"ok": True, "result": result}

    def _interruptible_sleep(self, seconds: float) -> None:
        if self._abort.wait(seconds):
            raise ActionAborted("비상 정지 요청으로 대기를 중단했습니다.")

    def _execute_one(self, cmd: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(cmd, dict):
            raise ValueError("Each action must be a JSON object")

        action = str(cmd.get("action", "")).strip().lower()
        human = bool(cmd.get("human", True))
        duration = cmd.get("duration")
        if duration is not None:
            duration = float(duration)
            if not 0 < duration <= MAX_MOVE_DURATION_SEC:
                raise ValueError(f"'duration' must be between 0 and {MAX_MOVE_DURATION_SEC} seconds")

        if action == "sleep":
            ms = int(cmd.get("ms", 100))
            if not 0 <= ms <= MAX_SLEEP_MS:
                raise ValueError(f"'ms' must be between 0 and {MAX_SLEEP_MS}")
            self._interruptible_sleep(ms / 1000.0)
            return {"action": "sleep", "ms": ms}

        if action == "cursor":
            return {"action": "cursor", "cursor": self._cursor_dict()}

        mouse, human_ctrl = self._require_connected()
        self.logger.add(f"ACTION: {json.dumps(redact_action_for_log(cmd), ensure_ascii=False)}")

        # --- Mouse actions ---
        if action == "move":
            dx = validate_int16("dx", cmd.get("dx", 0))
            dy = validate_int16("dy", cmd.get("dy", 0))
            if human:
                human_ctrl.move_relative_human(dx, dy, duration=duration)
            else:
                mouse.move(dx, dy)
            return {"action": "move", "cursor": self._cursor_dict()}

        if action == "move_to":
            x = validate_int16("x", cmd["x"])
            y = validate_int16("y", cmd["y"])
            cx, cy = human_ctrl.move_to_human(x, y, duration=duration)
            return {"action": "move_to", "cursor": {"x": cx, "y": cy}}

        if action == "click":
            btn = normalize_button(cmd.get("button", "L"))
            if human:
                human_ctrl.click_human(btn)
            else:
                mouse.click(btn)
            return {"action": "click", "button": btn}

        if action == "click_at":
            x = validate_int16("x", cmd["x"])
            y = validate_int16("y", cmd["y"])
            btn = normalize_button(cmd.get("button", "L"))
            cx, cy = human_ctrl.click_at_human(x, y, button=btn, duration=duration)
            return {"action": "click_at", "button": btn, "cursor": {"x": cx, "y": cy}}

        if action == "double_click":
            btn = normalize_button(cmd.get("button", "L"))
            human_ctrl.double_click_human(btn)
            return {"action": "double_click", "button": btn}

        if action == "press":
            btn = normalize_button(cmd.get("button", "L"))
            mouse.press(btn)
            return {"action": "press", "button": btn}

        if action == "release":
            btn = normalize_button(cmd.get("button", "L"))
            mouse.release(btn)
            return {"action": "release", "button": btn}

        if action == "drag":
            fx = validate_int16("from_x", cmd["from_x"])
            fy = validate_int16("from_y", cmd["from_y"])
            tx = validate_int16("to_x", cmd["to_x"])
            ty = validate_int16("to_y", cmd["to_y"])
            btn = normalize_button(cmd.get("button", "L"))
            cx, cy = human_ctrl.drag_human(fx, fy, tx, ty, button=btn, duration=duration)
            return {"action": "drag", "cursor": {"x": cx, "y": cy}}

        if action == "scroll":
            delta = int(cmd.get("delta", 0))
            if abs(delta) > MAX_SCROLL_TICKS:
                raise ValueError(f"'delta' must be between -{MAX_SCROLL_TICKS} and {MAX_SCROLL_TICKS}")
            if human:
                human_ctrl.scroll_human(delta)
            else:
                mouse.scroll(delta)
            return {"action": "scroll", "delta": delta}

        # --- Keyboard actions ---
        if action == "type":
            text = str(cmd.get("text", ""))
            if len(text) > MAX_TYPE_CHARS:
                raise ValueError(f"'text' may contain at most {MAX_TYPE_CHARS} characters")
            if human:
                human_ctrl.type_human(text)
            else:
                mouse.key_write_text(text)
            return {"action": "type", "length": len(text)}

        if action == "hotkey":
            keys = cmd.get("keys")
            if not isinstance(keys, list) or not keys:
                raise ValueError("'keys' must be a non-empty list, e.g. ['ctrl', 'c']")
            if len(keys) > MAX_HOTKEY_KEYS:
                raise ValueError(f"'keys' may contain at most {MAX_HOTKEY_KEYS} keys")
            human_ctrl.hotkey_human(keys)
            return {"action": "hotkey", "keys": keys}

        if action == "key_tap":
            key = cmd["key"]
            if human:
                human_ctrl.key_tap_human(key)
            else:
                mouse.key_tap(resolve_keycode(key))
            return {"action": "key_tap", "key": key}

        if action == "key_press":
            key = cmd["key"]
            mouse.key_press(resolve_keycode(key))
            return {"action": "key_press", "key": key}

        if action == "key_release":
            key = cmd["key"]
            mouse.key_release(resolve_keycode(key))
            return {"action": "key_release", "key": key}

        if action == "key_release_all":
            mouse.key_release_all()
            return {"action": "key_release_all"}

        if action == "release_all":
            mouse.release_all()
            return {"action": "release_all"}

        raise ValueError(f"Unsupported action: {action!r}")

    def is_flashing(self) -> bool:
        """펌웨어 업데이트가 진행 중인지 (종료가 플래싱을 중간에 끊지 않게 server.py 가 확인한다)."""
        return self._update_lock.locked()

    def close(self) -> None:
        self._closed = True
        self._request_stop()  # 종료가 진행 중인 긴 동작을 기다리지 않게 먼저 끊는다 (플래싱은 끝까지 기다린다)
        with self._lock:
            self._clear_stop_signal()
            if self.mouse is not None:
                try:
                    self.mouse.release_all()
                except Exception:
                    pass
            self._disconnect_unlocked()
