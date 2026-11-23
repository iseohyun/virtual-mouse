"""
VirtualMouse Local HTTP JSON API Server (v3 — System Tray & Runtime Control)

특징:
  - 콘솔(CMD) 창 없이 Windows 시스템 트레이(검정 바탕 흰 글씨 'VM' 아이콘)로 상주
  - 트레이 우클릭 메뉴: 대시보드 보기 / 종료하기
  - 내부 로그 링 버퍼(GET /logs)로 CMD 창 없이 대시보드에서 실시간 로그 확인
  - 구동 제어 API: POST /control/pause, POST /control/resume, POST /control/quit
  - 기본 주소: http://127.0.0.1:18080
"""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime
import json
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict

from device_status import EXPECTED_FW_VERSION, detect_device_state
from human_motion import HumanMouseController, enable_dpi_awareness, get_cursor_pos_safe
from keycodes import resolve_keycode
from mouse_client import VirtualMouse
from updater import (
    DEFAULT_MANIFEST_URL,
    _resource_root,
    check_for_update,
    download_and_verify_firmware,
    find_local_hex,
    flash_hex_via_dfu,
    wait_for_dfu_ready,
)


class LogBuffer:
    """스레드 안전한 서버 로그 링 버퍼 (대시보드 로그 탭에 표시)."""

    def __init__(self, maxlen: int = 250):
        self._entries: deque[str] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def add(self, message: str, level: str = "INFO") -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] [{level}] {message}"
        with self._lock:
            self._entries.append(line)
        if sys.stdout is not None:
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
        self._try_connect()

    def _try_connect(self) -> bool:
        if self.paused:
            return False
        if self.mouse is not None:
            try:
                if self.mouse.ping():
                    return True
            except Exception:
                self._disconnect_unlocked()

        try:
            vm = VirtualMouse(port=self.preferred_port)
            if vm.ping():
                self.mouse = vm
                self.human = HumanMouseController(vm)
                self.logger.add(f"Arduino 연결됨 ({vm.port})")
                return True
            vm.close()
        except Exception:
            pass
        return False

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
        with self._lock:
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

    def health(self) -> Dict[str, Any]:
        with self._lock:
            connected = self._try_connect()
            ver = self.mouse.version() if connected and self.mouse else None
            return {
                "ok": connected,
                "paused": self.paused,
                "running": not self.paused,
                "port": self.mouse.port if connected and self.mouse else None,
                "firmware_version": ver,
                "cursor": self._cursor_dict(),
            }

    def status(self) -> Dict[str, Any]:
        with self._lock:
            connected = self._try_connect()
            port = self.mouse.port if connected and self.mouse else None
            ver = self.mouse.version() if connected and self.mouse else None
            paused = self.paused
            expected = self.expected_version
        # USB PnP 조회는 락 밖에서 실행 (다른 요청 블로킹 방지)
        info = detect_device_state(
            connected_port=port,
            firmware_version=ver,
            expected_version=expected,
        )
        info["paused"] = paused
        info["running"] = not paused
        info["cursor"] = self._cursor_dict()
        return info

    def check_firmware(self, manifest_url: str | None = None) -> Dict[str, Any]:
        with self._lock:
            connected = self._try_connect()
            ver = self.mouse.version() if connected and self.mouse else None
            url = manifest_url or DEFAULT_MANIFEST_URL
            info = check_for_update(ver, manifest_url=url)
            info["ok"] = True
            self.logger.add(f"펌웨어 버전 확인: current={ver}, remote={info['remote_version']}")
            return info

    def update_firmware(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            use_local = bool(payload.get("use_local", False))
            force = bool(payload.get("force", False))
            dry_run = bool(payload.get("dry_run", False))
            manifest_url = payload.get("manifest_url") or DEFAULT_MANIFEST_URL

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
                info = check_for_update(current_ver, manifest_url=manifest_url)
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

    def execute_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            if "actions" in payload:
                actions = payload["actions"]
                if not isinstance(actions, list):
                    raise ValueError("'actions' must be a list")
                results = [self._execute_one(item) for item in actions]
                return {"ok": True, "results": results}
            result = self._execute_one(payload)
            return {"ok": True, "result": result}

    def _execute_one(self, cmd: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(cmd, dict):
            raise ValueError("Each action must be a JSON object")

        action = str(cmd.get("action", "")).strip().lower()
        human = bool(cmd.get("human", True))
        duration = cmd.get("duration")

        if action == "sleep":
            ms = max(0, int(cmd.get("ms", 100)))
            time.sleep(ms / 1000.0)
            return {"action": "sleep", "ms": ms}

        if action == "cursor":
            return {"action": "cursor", "cursor": self._cursor_dict()}

        mouse, human_ctrl = self._require_connected()
        self.logger.add(f"ACTION: {json.dumps(cmd, ensure_ascii=False)}")

        # --- Mouse actions ---
        if action == "move":
            dx = int(cmd.get("dx", 0))
            dy = int(cmd.get("dy", 0))
            if human:
                human_ctrl.move_relative_human(dx, dy, duration=duration)
            else:
                mouse.move(dx, dy)
            return {"action": "move", "cursor": self._cursor_dict()}

        if action == "move_to":
            x = int(cmd["x"])
            y = int(cmd["y"])
            cx, cy = human_ctrl.move_to_human(x, y, duration=duration)
            return {"action": "move_to", "cursor": {"x": cx, "y": cy}}

        if action == "click":
            btn = str(cmd.get("button", "L"))
            if human:
                human_ctrl.click_human(btn)
            else:
                mouse.click(btn)
            return {"action": "click", "button": btn.upper()}

        if action == "click_at":
            x = int(cmd["x"])
            y = int(cmd["y"])
            btn = str(cmd.get("button", "L"))
            cx, cy = human_ctrl.click_at_human(x, y, button=btn, duration=duration)
            return {"action": "click_at", "button": btn.upper(), "cursor": {"x": cx, "y": cy}}

        if action == "double_click":
            btn = str(cmd.get("button", "L"))
            human_ctrl.double_click_human(btn)
            return {"action": "double_click", "button": btn.upper()}

        if action == "press":
            btn = str(cmd.get("button", "L"))
            mouse.press(btn)
            return {"action": "press", "button": btn.upper()}

        if action == "release":
            btn = str(cmd.get("button", "L"))
            mouse.release(btn)
            return {"action": "release", "button": btn.upper()}

        if action == "drag":
            fx = int(cmd["from_x"])
            fy = int(cmd["from_y"])
            tx = int(cmd["to_x"])
            ty = int(cmd["to_y"])
            btn = str(cmd.get("button", "L"))
            cx, cy = human_ctrl.drag_human(fx, fy, tx, ty, button=btn, duration=duration)
            return {"action": "drag", "cursor": {"x": cx, "y": cy}}

        if action == "scroll":
            delta = int(cmd.get("delta", 0))
            if human:
                human_ctrl.scroll_human(delta)
            else:
                mouse.scroll(delta)
            return {"action": "scroll", "delta": delta}

        # --- Keyboard actions ---
        if action == "type":
            text = str(cmd.get("text", ""))
            if human:
                human_ctrl.type_human(text)
            else:
                mouse.key_write_text(text)
            return {"action": "type", "length": len(text)}

        if action == "hotkey":
            keys = cmd.get("keys")
            if not isinstance(keys, list) or not keys:
                raise ValueError("'keys' must be a non-empty list, e.g. ['ctrl', 'c']")
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

    def close(self) -> None:
        with self._lock:
            if self.mouse is not None:
                try:
                    self.mouse.release_all()
                except Exception:
                    pass
            self._disconnect_unlocked()


def make_handler(dispatcher: ActionDispatcher, on_quit_request: Callable[[], None]):
    class VirtualMouseHTTPHandler(BaseHTTPRequestHandler):
        def _send_cors_headers(self) -> None:
            origin = self.headers.get("Origin") or "*"
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")

        def _send_json(self, status: int, body: Dict[str, Any]) -> None:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._send_cors_headers()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _serve_static(self, rel_path: str) -> bool:
            web_dir = _resource_root() / "web"
            target = (web_dir / rel_path).resolve()
            if not str(target).startswith(str(web_dir.resolve())) or not target.is_file():
                return False
            mime_map = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".svg": "image/svg+xml",
                ".png": "image/png",
                ".json": "application/json; charset=utf-8",
                ".webmanifest": "application/manifest+json; charset=utf-8",
            }
            content_type = mime_map.get(target.suffix.lower(), "application/octet-stream")
            raw = target.read_bytes()
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return True

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/health":
                try:
                    self._send_json(200, dispatcher.health())
                except Exception as exc:
                    self._send_json(500, {"ok": False, "error": str(exc)})
                return
            if path == "/status":
                try:
                    self._send_json(200, dispatcher.status())
                except Exception as exc:
                    self._send_json(500, {"ok": False, "error": str(exc)})
                return
            if path == "/logs":
                self._send_json(200, {"ok": True, "lines": dispatcher.logger.list_lines()})
                return
            if path in ("/", "/guide", "/guide/"):
                if self._serve_static("index.html"):
                    return
            if path.startswith("/guide/"):
                if self._serve_static(path[len("/guide/") :]):
                    return
            if path.lstrip("/") in (
                "styles.css", "app.js", "index.html", "icon.svg",
                "icon-192.png", "icon-512.png", "manifest.webmanifest",
                "sw.js", "robots.txt", "sitemap.xml",
            ):
                if self._serve_static(path.lstrip("/")):
                    return
            self._send_json(404, {"ok": False, "error": "Not found."})

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length).decode("utf-8") if length > 0 else ""
                payload = json.loads(raw) if raw.strip() else {}

                if path in ("/", "/action"):
                    resp = dispatcher.execute_payload(payload)
                    self._send_json(200, resp)
                    return
                if path == "/firmware/check":
                    resp = dispatcher.check_firmware(payload.get("manifest_url"))
                    self._send_json(200, resp)
                    return
                if path == "/firmware/update":
                    resp = dispatcher.update_firmware(payload)
                    self._send_json(200, resp)
                    return
                if path == "/control/pause":
                    self._send_json(200, dispatcher.pause())
                    return
                if path == "/control/resume":
                    self._send_json(200, dispatcher.resume())
                    return
                if path == "/control/quit":
                    dispatcher.logger.add("대시보드에서 종료 요청 수신", "WARN")
                    self._send_json(200, {"ok": True, "quitting": True})
                    threading.Timer(0.25, on_quit_request).start()
                    return
                if path == "/logs/clear":
                    dispatcher.logger.clear()
                    dispatcher.logger.add("로그를 초기화했습니다.")
                    self._send_json(200, {"ok": True})
                    return

                self._send_json(404, {"ok": False, "error": f"Unknown endpoint: {path}"})
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                dispatcher.logger.add(f"400 {path}: {exc}", "ERROR")
                self._send_json(400, {"ok": False, "error": str(exc)})
            except Exception as exc:
                dispatcher.logger.add(f"500 {path}: {exc}", "ERROR")
                self._send_json(500, {"ok": False, "error": str(exc)})

        def log_message(self, fmt: str, *args: Any) -> None:
            msg = fmt % args
            # 폴링 요청(/status, /logs)과 CORS 프리플라이트(OPTIONS)는 로그 버퍼 도배 방지
            if any(p in msg for p in ('"GET /status ', '"GET /logs ', '"OPTIONS ')):
                return
            dispatcher.logger.add(f"HTTP {msg}")

    return VirtualMouseHTTPHandler


def main() -> None:
    parser = argparse.ArgumentParser(description="VirtualMouse Local HTTP JSON API Server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=18080, help="Bind port (default: 18080)")
    parser.add_argument("--com", default=None, help="Arduino COM port (auto-detect if omitted)")
    parser.add_argument("--open-guide", action="store_true", help="Open dashboard in browser on startup")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser on startup")
    parser.add_argument("--no-tray", action="store_true", help="Run without system tray icon (headless/CLI mode)")
    args = parser.parse_args()

    logger = LogBuffer()
    dispatcher = ActionDispatcher(port=args.com, logger=logger)
    guide_url = f"http://{args.host}:{args.port}/guide"

    tray_holder: dict[str, Any] = {"tray": None}
    shutdown_event = threading.Event()

    def request_shutdown() -> None:
        if shutdown_event.is_set():
            return
        shutdown_event.set()
        logger.add("VirtualMouse Agent 종료 중...")
        if tray_holder["tray"] is not None:
            tray_holder["tray"].stop()
        try:
            dispatcher.close()
        except Exception:
            pass
        threading.Thread(target=server.shutdown, daemon=True).start()
        # Keep-alive 소켓이나 트레이 메시지 루프 지연으로 프로세스가 남지 않도록 안전 종료 보장
        threading.Timer(0.6, lambda: os._exit(0)).start()

    server = ThreadingHTTPServer((args.host, args.port), make_handler(dispatcher, request_shutdown))
    port_info = dispatcher.mouse.port if dispatcher.mouse else "대기 중 (자동 감지)"
    logger.add(f"서버 시작: http://{args.host}:{args.port} (Arduino: {port_info})")

    should_open = args.open_guide and not args.no_browser
    if should_open:
        threading.Timer(0.6, lambda: webbrowser.open(guide_url)).start()

    use_tray = not args.no_tray
    if use_tray:
        try:
            from tray import TrayController

            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            tray = TrayController(dashboard_url=guide_url, on_quit=request_shutdown)
            tray_holder["tray"] = tray
            tray.run()
        except Exception as exc:
            logger.add(f"트레이 초기화 실패, 콘솔 모드로 전환: {exc}", "WARN")
            use_tray = False

    if not use_tray:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass

    server.server_close()
    dispatcher.close()


if __name__ == "__main__":
    main()
