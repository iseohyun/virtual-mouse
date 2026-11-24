"""
VirtualMouse 로컬 HTTP JSON API (요청 검사·라우팅).

보안 규칙 (다른 웹사이트·다른 사용자가 이 PC의 마우스·키보드를 조작하지 못하게):
  1. Host 헤더는 루프백 이름만 허용 (DNS rebinding 차단)
  2. 브라우저 Origin은 공식 대시보드와 이 서버가 서빙하는 로컬 가이드만 허용
  3. Origin 없이 다른 사이트에서 온 요청(Sec-Fetch-Site: cross-site) 거부
  4. POST는 application/json만 허용 (text/plain 단순 요청 CSRF 차단), 본문 64KB 상한
  5. 모든 API는 `Authorization: Bearer <토큰>` 필요 (auth.py). 정적 파일과 CORS 프리플라이트만 예외

엔드포인트: GET /health /status /logs, POST /action /firmware/check /firmware/update /driver/install
            /control/pause /control/resume /control/quit /logs/clear, 정적 파일 / /guide
사용처: server.py
의존: dispatcher(ActionDispatcher), auth, updater(_resource_root)
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict

from auth import parse_bearer, tokens_match
from dispatcher import ActionAborted, ActionDispatcher, UpdateInProgress
from updater import _resource_root

__all__ = [
    "ExclusiveThreadingHTTPServer",
    "MAX_BODY_BYTES",
    "PUBLIC_DASHBOARD_ORIGIN",
    "allowed_hosts",
    "allowed_origins",
    "make_handler",
]


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    """같은 포트를 다른 프로세스(두 번째 에이전트, 다른 계정의 프로그램)가 함께 열지 못하게 독점 바인드한다.

    표준 HTTPServer 는 SO_REUSEADDR 를 켜기 때문에 Windows 에서는 같은 포트에 두 번째 서버가 바인드될 수 있다.
    """

    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self) -> None:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()


PUBLIC_DASHBOARD_ORIGIN = "https://virtual-mouse.iseohyun.com"
MAX_BODY_BYTES = 64 * 1024


def allowed_origins(port: int) -> set[str]:
    """이 API를 브라우저에서 부를 수 있는 출처: 공식 대시보드와 이 서버가 직접 서빙하는 로컬 가이드."""
    return {
        PUBLIC_DASHBOARD_ORIGIN,
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
    }


def allowed_hosts(port: int) -> set[str]:
    """DNS rebinding 방지: Host 헤더는 루프백 이름만 허용한다."""
    return {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}


# 토큰 없이 열 수 있는 정적 파일 (대시보드 화면 자체)
STATIC_FILES = (
    "styles.css", "app.js", "index.html", "icon.svg",
    "icon-192.png", "icon-512.png", "manifest.webmanifest",
    "sw.js", "robots.txt", "sitemap.xml",
)
CORS_MAX_AGE_SEC = 600
MAX_DRAIN_BYTES = 1024 * 1024  # 거부한 요청의 본문을 이만큼까지는 읽어 버려 연결이 깔끔하게 닫히게 한다


def make_handler(
    dispatcher: ActionDispatcher,
    on_quit_request: Callable[[], None],
    port: int = 18080,
    token: str | None = None,
):
    """요청 처리기 클래스를 만든다. token이 None이면 인증을 끈다 (테스트 전용, server.py는 항상 토큰을 넘긴다)."""
    origins = allowed_origins(port)
    hosts = allowed_hosts(port)

    class VirtualMouseHTTPHandler(BaseHTTPRequestHandler):
        # 느리거나 멈춘 연결이 처리 스레드를 붙잡지 않게 소켓 읽기·쓰기에 시간 제한을 둔다 (처리 시간과는 무관)
        timeout = 10
        _body_consumed = False

        def _drain_unread_body(self) -> None:
            """본문을 읽기 전에 거부(401·403·413·415 등)할 때, 남은 본문을 읽어 버린다.

            본문을 남긴 채 연결을 닫으면 Windows 가 연결을 RST 로 끊어, 클라이언트가 오류 응답 대신
            'connection aborted' 를 받을 수 있다. 너무 큰 본문(MAX_DRAIN_BYTES 초과)은 읽지 않는다.
            """
            if self._body_consumed or self.command != "POST":
                return
            self._body_consumed = True
            try:
                remaining = min(int(self.headers.get("Content-Length") or 0), MAX_DRAIN_BYTES)
            except ValueError:
                return
            try:
                while remaining > 0:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
            except OSError:
                pass

        def _origin_allowed(self) -> bool:
            origin = self.headers.get("Origin")
            return origin is None or origin in origins

        def _guard(self) -> bool:
            """다른 사이트가 이 PC의 마우스·키보드를 조작하지 못하게 요청 출처를 검사한다.

            - Host 헤더가 루프백이 아니면 거부 (DNS rebinding)
            - Origin이 허용 목록 밖이면 거부 (외부 웹페이지의 fetch)
            - Origin 없이 다른 사이트에서 온 요청(Sec-Fetch-Site: cross-site)도 거부
            - POST는 application/json만 허용 (text/plain 단순 요청을 이용한 CSRF 차단)
            Origin을 보내지 않는 외부 프로그램(Python, curl, AHK, vm CLI)은 그대로 쓸 수 있다.
            """
            host = (self.headers.get("Host") or "").strip().lower()
            if host not in hosts:
                self._send_json(421, {"ok": False, "error": "Host not allowed."}, cors=False)
                return False
            if not self._origin_allowed():
                self._send_json(403, {"ok": False, "error": "Origin not allowed."}, cors=False)
                return False
            if self.headers.get("Origin") is None and self.headers.get("Sec-Fetch-Site") == "cross-site":
                self._send_json(403, {"ok": False, "error": "Cross-site request not allowed."}, cors=False)
                return False
            if self.command == "POST":
                ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
                if ctype != "application/json":
                    self._send_json(415, {"ok": False, "error": "Content-Type must be application/json."})
                    return False
            return True

        def _authorized(self) -> bool:
            """API 요청에 올바른 Bearer 토큰이 있는지 확인하고, 없으면 401로 답한다."""
            if token is None:
                return True
            if tokens_match(token, parse_bearer(self.headers.get("Authorization"))):
                return True
            body = {
                "ok": False,
                "auth_required": True,
                "error": "API token required. Send 'Authorization: Bearer <token>' "
                "(tray menu > API 토큰 복사, or 'vm token').",
            }
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self._drain_unread_body()
            self.send_response(401)
            self._send_cors_headers()
            self.send_header("WWW-Authenticate", 'Bearer realm="VirtualMouse"')
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return False

        def _send_cors_headers(self) -> None:
            origin = self.headers.get("Origin")
            if origin is None or origin not in origins:
                return
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Max-Age", str(CORS_MAX_AGE_SEC))

        def _send_json(self, status: int, body: Dict[str, Any], cors: bool = True) -> None:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self._drain_unread_body()
            self.send_response(status)
            if cors:
                self._send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_OPTIONS(self) -> None:
            if not self._guard():
                return
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
            if not self._guard():
                return
            path = self.path.split("?", 1)[0]

            # 정적 파일(대시보드 화면)은 토큰 없이 연다
            if path in ("/", "/guide", "/guide/"):
                if self._serve_static("index.html"):
                    return
            if path.startswith("/guide/") and path[len("/guide/") :] in STATIC_FILES:
                if self._serve_static(path[len("/guide/") :]):
                    return
            if path.lstrip("/") in STATIC_FILES:
                if self._serve_static(path.lstrip("/")):
                    return

            if path not in ("/health", "/status", "/logs"):
                self._send_json(404, {"ok": False, "error": "Not found."})
                return
            if not self._authorized():
                return
            try:
                if path == "/health":
                    self._send_json(200, dispatcher.health())
                elif path == "/status":
                    self._send_json(200, dispatcher.status())
                else:
                    self._send_json(200, {"ok": True, "lines": dispatcher.logger.list_lines()})
            except OSError as exc:
                self._send_json(503, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})

        def do_POST(self) -> None:
            if not self._guard():
                return
            if not self._authorized():
                return
            path = self.path.split("?", 1)[0]
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > MAX_BODY_BYTES:
                    self._send_json(413, {"ok": False, "error": f"Request body too large (max {MAX_BODY_BYTES} bytes)."})
                    return
                body_bytes = self.rfile.read(length) if length > 0 else b""
                self._body_consumed = True
                raw = body_bytes.decode("utf-8")
                payload = json.loads(raw) if raw.strip() else {}

                if path in ("/", "/action"):
                    resp = dispatcher.execute_payload(payload)
                    self._send_json(200, resp)
                    return
                if path == "/firmware/check":
                    # 매니페스트 주소는 요청으로 바꿀 수 없다 (임의 펌웨어 플래싱 방지)
                    resp = dispatcher.check_firmware()
                    self._send_json(200, resp)
                    return
                if path == "/firmware/update":
                    resp = dispatcher.update_firmware(payload)
                    self._send_json(200, resp)
                    return
                if path == "/driver/install":
                    # 사용자가 버튼·명령으로 요청할 때만 설치한다 (UAC 확인 창이 뜬다). 결과는 status 로 구분한다
                    self._send_json(200, dispatcher.install_driver())
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
            except ActionAborted as exc:
                dispatcher.logger.add(f"409 {path}: {exc}", "WARN")
                self._send_json(409, {"ok": False, "aborted": True, "error": str(exc)})
            except UpdateInProgress as exc:
                self._send_json(409, {"ok": False, "busy": True, "error": str(exc)})
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                dispatcher.logger.add(f"400 {path}: {exc}", "ERROR")
                self._send_json(400, {"ok": False, "error": str(exc)})
            except OSError as exc:
                # 커서 좌표를 읽을 수 없는 세션(원격·비대화형) 등 이 PC 환경 문제
                dispatcher.logger.add(f"503 {path}: {exc}", "ERROR")
                self._send_json(503, {"ok": False, "error": str(exc)})
            except Exception as exc:
                dispatcher.logger.add(f"500 {path}: {exc}", "ERROR")
                self._send_json(500, {"ok": False, "error": str(exc)})

        def log_message(self, fmt: str, *args: Any) -> None:
            msg = fmt % args
            # 폴링 요청(/status, /logs), CORS 프리플라이트(OPTIONS), 화면 파일 요청은 로그 버퍼 도배 방지
            quiet = ('"GET /status ', '"GET /logs ', '"OPTIONS ', '"GET / ', '"GET /guide')
            if any(p in msg for p in quiet) or any(f'"GET /{name} ' in msg for name in STATIC_FILES):
                return
            dispatcher.logger.add(f"HTTP {msg}")

    return VirtualMouseHTTPHandler
