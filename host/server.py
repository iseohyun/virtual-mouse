"""
VirtualMouse Local HTTP JSON API Server (v2)

외부 프로그램 및 웹 가이드(https://virtual-mouse.iseohyun.com)에서
COM 포트나 사람 움직임 알고리즘을 신경 쓰지 않고 JSON({})만으로
물리 USB 마우스 + 키보드를 제어할 수 있는 로컬 서버입니다.

기본 주소: http://127.0.0.1:18080

Endpoints:
  GET     /health  -> 서버 및 아두이노 PING / 버전 / 커서 상태 확인
  GET     /status  -> USB 장치 자동 판별 (ready / outdated / dfu_ready / stock_uno / no_device)
  POST    /action  -> JSON 객체({}) 또는 배열({"actions": [...]})로 마우스/키보드 제어
  OPTIONS /*       -> CORS 및 Chrome Private Network Access 프리플라이트 응답
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

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


class ActionDispatcher:
    """COM 포트에 대한 스레드 안전한 단일 접근, 자동 재연결, JSON 액션 실행기."""

    def __init__(self, port: str | None = None, expected_version: str = EXPECTED_FW_VERSION):
        enable_dpi_awareness()
        self.preferred_port = port
        self.expected_version = expected_version
        self.mouse: VirtualMouse | None = None
        self.human: HumanMouseController | None = None
        self._lock = threading.Lock()
        self._try_connect()

    def _try_connect(self) -> bool:
        """VirtualMouse COM 포트 연결을 시도합니다. 장치가 없어도 예외를 발생시키지 않습니다."""
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
                return True
            vm.close()
        except Exception:
            pass
        return False

    def _disconnect_unlocked(self) -> None:
        if self.mouse is not None:
            try:
                self.mouse.close()
            except Exception:
                pass
        self.mouse = None
        self.human = None

    def _require_connected(self) -> tuple[VirtualMouse, HumanMouseController]:
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
                "port": self.mouse.port if connected and self.mouse else None,
                "firmware_version": ver,
                "cursor": self._cursor_dict(),
            }

    def status(self) -> Dict[str, Any]:
        with self._lock:
            connected = self._try_connect()
            port = self.mouse.port if connected and self.mouse else None
            ver = self.mouse.version() if connected and self.mouse else None
            info = detect_device_state(
                connected_port=port,
                firmware_version=ver,
                expected_version=self.expected_version,
            )
            info["cursor"] = self._cursor_dict()
            return info

    def check_firmware(self, manifest_url: str | None = None) -> Dict[str, Any]:
        with self._lock:
            connected = self._try_connect()
            ver = self.mouse.version() if connected and self.mouse else None
            url = manifest_url or DEFAULT_MANIFEST_URL
            info = check_for_update(ver, manifest_url=url)
            info["ok"] = True
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

        # 장치 연결 없이도 처리 가능한 유틸 액션
        if action == "sleep":
            ms = max(0, int(cmd.get("ms", 100)))
            time.sleep(ms / 1000.0)
            return {"action": "sleep", "ms": ms}

        if action == "cursor":
            return {"action": "cursor", "cursor": self._cursor_dict()}

        mouse, human_ctrl = self._require_connected()

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


def make_handler(dispatcher: ActionDispatcher):
    class VirtualMouseHTTPHandler(BaseHTTPRequestHandler):
        def _send_cors_headers(self) -> None:
            origin = self.headers.get("Origin") or "*"
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            # Chrome Private Network Access (HTTPS -> http://127.0.0.1)
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
                ".json": "application/json; charset=utf-8",
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
            if path in ("/", "/guide", "/guide/"):
                if self._serve_static("index.html"):
                    return
            if path.startswith("/guide/"):
                if self._serve_static(path[len("/guide/") :]):
                    return
            if path.lstrip("/") in ("styles.css", "app.js", "index.html", "icon.svg", "robots.txt", "sitemap.xml"):
                if self._serve_static(path.lstrip("/")):
                    return
            self._send_json(404, {"ok": False, "error": "Not found. Use GET /guide, GET /health, GET /status, or POST /action"})

        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length).decode("utf-8") if length > 0 else ""
                payload = json.loads(raw) if raw.strip() else {}

                if self.path in ("/", "/action"):
                    resp = dispatcher.execute_payload(payload)
                    self._send_json(200, resp)
                    return
                if self.path == "/firmware/check":
                    resp = dispatcher.check_firmware(payload.get("manifest_url"))
                    self._send_json(200, resp)
                    return
                if self.path == "/firmware/update":
                    resp = dispatcher.update_firmware(payload)
                    self._send_json(200, resp)
                    return

                self._send_json(
                    404,
                    {"ok": False, "error": "Not found. Use POST /action, /firmware/check, or /firmware/update"},
                )
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[VirtualMouseAPI] {self.address_string()} - {fmt % args}", flush=True)

    return VirtualMouseHTTPHandler


def main() -> None:
    parser = argparse.ArgumentParser(description="VirtualMouse Local HTTP JSON API Server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=18080, help="Bind port (default: 18080)")
    parser.add_argument("--com", default=None, help="Arduino COM port (auto-detect if omitted)")
    parser.add_argument("--open-guide", action="store_true", help="Open guide page in browser on startup")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser even in frozen .exe mode")
    args = parser.parse_args()

    dispatcher = ActionDispatcher(port=args.com)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(dispatcher))
    port_info = dispatcher.mouse.port if dispatcher.mouse else "Not connected yet (auto-detect enabled)"
    guide_url = f"http://{args.host}:{args.port}/guide"
    print(f"VirtualMouse Local API Server running at http://{args.host}:{args.port} (Arduino: {port_info})", flush=True)
    print(f"Guide UI: {guide_url}", flush=True)

    should_open = (args.open_guide or getattr(sys, "frozen", False)) and not args.no_browser
    if should_open:
        threading.Timer(0.8, lambda: webbrowser.open(guide_url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...", flush=True)
    finally:
        server.server_close()
        dispatcher.close()


if __name__ == "__main__":
    main()
