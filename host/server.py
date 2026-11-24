"""
VirtualMouse Agent 진입점 (로컬 HTTP JSON API 서버 + 시스템 트레이).

  - 콘솔(CMD) 창 없이 Windows 시스템 트레이(검정 바탕 흰 글씨 'VM' 아이콘)로 상주
  - 트레이 메뉴: 대시보드 보기(토큰 자동 전달) / 비상 정지 / API 토큰 복사 / 종료하기
  - 포트를 독점으로 열어, 에이전트가 이미 실행 중이면 두 번째 실행은 안내 후 끝난다
  - 기본 주소: http://127.0.0.1:18080 (모든 API는 Bearer 토큰 필요, auth.py 참고)

구성: dispatcher.py(액션 실행·로그) · http_api.py(요청 검사·라우팅) · auth.py(토큰) · tray.py(트레이)
빌드: scripts/build_agent.ps1 이 이 파일을 진입점으로 VirtualMouse-Agent.exe 를 만든다.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler
from typing import Any

from auth import TOKEN_ENV, load_or_create_token
from dispatcher import ActionDispatcher, LogBuffer
from http_api import ExclusiveThreadingHTTPServer, make_handler

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
SHUTDOWN_DEADLINE_SEC = 3.0  # 종료가 어떤 이유로든 막혀도 이 시간 안에 프로세스를 끝낸다
FLASHING_SHUTDOWN_DEADLINE_SEC = 240.0  # 플래싱 중이면 dfu-programmer 단계 제한(60초 x 3)보다 넉넉히 기다린다


def show_error_dialog(message: str) -> None:
    """콘솔 없는 exe 에서도 사용자가 볼 수 있게 Windows 메시지 상자로 알린다."""
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "VirtualMouse Agent", 0x10)
    except Exception:
        pass


def guide_url_with_token(port: int, token: str) -> str:
    """트레이·--open-guide 가 여는 로컬 대시보드 주소. 토큰은 서버로 전송되지 않는 # 뒤에 담는다."""
    return f"http://127.0.0.1:{port}/guide#token={token}"


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

    # 포트를 먼저 독점으로 잡는다: 에이전트가 이미 실행 중이면 COM 포트를 건드리기 전에 끝낸다
    try:
        server = ExclusiveThreadingHTTPServer((args.host, args.port), BaseHTTPRequestHandler)
    except OSError as exc:
        message = (
            f"{args.port} 포트를 열 수 없습니다. VirtualMouse Agent가 이미 실행 중이거나 "
            f"다른 프로그램이 이 포트를 쓰고 있습니다.\n\n({exc})"
        )
        logger.add(message, "ERROR")
        if not args.no_tray:
            show_error_dialog(message)
        sys.exit(1)

    token = load_or_create_token()
    dispatcher = ActionDispatcher(port=args.com, logger=logger)
    dashboard_url = guide_url_with_token(args.port, token)

    tray_holder: dict[str, Any] = {"tray": None}
    shutdown_event = threading.Event()

    def request_shutdown() -> None:
        if shutdown_event.is_set():
            return
        shutdown_event.set()
        logger.add("VirtualMouse Agent 종료 중...")
        # 안전 타이머를 먼저 건다: 정리 작업이 막혀도 프로세스가 남지 않게.
        # 단, 플래싱 중에 프로세스를 끊으면 장치 펌웨어가 지워진 채 남을 수 있으므로 플래싱이 끝날 때까지 기다린다.
        deadline = SHUTDOWN_DEADLINE_SEC
        if dispatcher.is_flashing():
            deadline = FLASHING_SHUTDOWN_DEADLINE_SEC
            logger.add("펌웨어 업데이트가 끝난 뒤 종료합니다 (장치 보호).", "WARN")
        threading.Timer(deadline, lambda: os._exit(0)).start()
        if tray_holder["tray"] is not None:
            tray_holder["tray"].stop()
        try:
            dispatcher.close()  # 진행 중인 동작을 비상 정지 신호로 끊고 눌린 입력을 모두 해제
        except Exception:
            pass
        threading.Thread(target=server.shutdown, daemon=True).start()
        # Keep-alive 소켓이나 트레이 메시지 루프 지연으로 프로세스가 남지 않도록 안전 종료 보장
        threading.Timer(0.6, lambda: os._exit(0)).start()

    def emergency_stop() -> None:
        """트레이 '비상 정지': 진행 중·대기 중인 동작을 끊고 눌린 버튼·키를 모두 해제한다 (트레이 UI를 막지 않게 별도 스레드)."""

        def run() -> None:
            try:
                dispatcher.execute_payload({"action": "release_all"})
                logger.add("트레이에서 비상 정지 실행", "WARN")
            except Exception as exc:
                logger.add(f"비상 정지 실패: {exc}", "ERROR")

        threading.Thread(target=run, daemon=True).start()

    server.RequestHandlerClass = make_handler(dispatcher, request_shutdown, args.port, token=token)
    port_info = dispatcher.mouse.port if dispatcher.mouse else "대기 중 (자동 감지)"
    logger.add(f"서버 시작: http://{args.host}:{args.port} (Arduino: {port_info})")
    # 로그는 대시보드에서 복사·공유될 수 있으므로 사용자 이름이 들어간 전체 경로는 남기지 않는다
    token_source = f"환경 변수 {TOKEN_ENV}" if os.environ.get(TOKEN_ENV) else r"%LOCALAPPDATA%\VirtualMouse\api-token"
    logger.add(f"API 토큰: {token_source} (트레이 메뉴 'API 토큰 복사' 또는 'vm token')")
    if args.host not in LOOPBACK_HOSTS:
        logger.add(
            f"주의: {args.host} 에 바인딩했습니다. 같은 네트워크의 다른 기기도 접속을 시도할 수 있으니 토큰을 공유하지 마세요.",
            "WARN",
        )

    should_open = args.open_guide and not args.no_browser
    if should_open:
        threading.Timer(0.6, lambda: webbrowser.open(dashboard_url)).start()

    tray = None
    if not args.no_tray:
        try:
            from tray import TrayController

            tray = TrayController(
                dashboard_url=dashboard_url,
                on_quit=request_shutdown,
                api_token=token,
                on_emergency_stop=emergency_stop,
            )
        except Exception as exc:
            logger.add(f"트레이 초기화 실패, 콘솔 모드로 전환: {exc}", "WARN")

    if tray is not None:
        # 서버는 백그라운드 스레드에서 돌리고, 트레이 메시지 루프가 메인 스레드를 차지한다
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        tray_holder["tray"] = tray
        try:
            tray.run()
        except Exception as exc:
            # serve_forever 를 두 번 돌리지 않고, 이미 도는 서버 스레드가 끝날 때까지(종료 요청) 기다린다
            logger.add(f"트레이 실행 실패, 트레이 없이 계속 실행: {exc}", "WARN")
            try:
                server_thread.join()
            except KeyboardInterrupt:
                pass
    else:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass

    server.server_close()
    dispatcher.close()


if __name__ == "__main__":
    main()
