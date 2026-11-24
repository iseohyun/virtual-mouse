"""
VirtualMouse CLI (`vm`) — gh CLI 스타일 명령줄 제어 도구

로컬 VirtualMouse-Agent 서버(http://127.0.0.1:18080)와 통신하여
상태 조회, 로그 확인, 원격 펌웨어 업데이트, 마우스/키보드 조작, 서버 제어를 수행합니다.

사용 예:
  vm status
  vm logs --tail 20
  vm check-update
  vm update --local
  vm driver-install       # DFU 장치에 WinUSB 드라이버 설치 (UAC 확인 창이 뜸)
  vm move 120 -50
  vm click-at 800 500 L
  vm type "Hello HID!"
  vm hotkey ctrl c
  vm pause / vm resume / vm quit
  vm token                # 에이전트 API 토큰 출력 (외부 스크립트의 Authorization 헤더용)

인증: 에이전트가 만든 토큰 파일(auth.py)을 자동으로 읽어 `Authorization: Bearer` 헤더로 보낸다.
      --token 또는 환경 변수 VMOUSE_API_TOKEN 으로 바꿀 수 있다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from auth import default_token_path, read_token

DEFAULT_API = os.environ.get("VMOUSE_API_URL", "http://127.0.0.1:18080")
# 에이전트는 UAC 응답(최대 120초)과 설치(최대 180초), 확인(최대 15초)을 기다린 뒤 답한다 (driver_install.py)
DRIVER_INSTALL_TIMEOUT_SEC = 340.0


def _request(
    base: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    timeout: float = 20.0,
    token: str | None = None,
) -> Any:
    url = f"{base.rstrip('/')}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(raw)
        except Exception:
            err = {"ok": False, "status": exc.code, "error": raw}
        if exc.code == 401:
            err["hint"] = (
                f"API 토큰이 없거나 틀립니다. 토큰 파일({default_token_path()})이 있는지, "
                "또는 --token / VMOUSE_API_TOKEN 값이 맞는지 확인하세요."
            )
        print(json.dumps(err, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(3 if exc.code == 401 else 1)
    except urllib.error.URLError as exc:
        print(
            json.dumps(
                {"ok": False, "error": f"로컬 VirtualMouse 서버({base})에 연결할 수 없습니다: {exc.reason}"},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        sys.exit(2)
    except TimeoutError:
        # 응답 대기 중 시간 초과는 URLError 로 감싸지지 않는다. 에이전트는 동작을 계속하고 있을 수 있다.
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"에이전트 응답을 {timeout:.0f}초 동안 기다렸지만 끝나지 않았습니다.",
                    "hint": "동작은 에이전트에서 계속 진행 중일 수 있습니다. 다시 실행하기 전에 'vm logs'로 확인하고, "
                    "멈추려면 'vm release-all'을 실행하세요.",
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        sys.exit(4)


def typing_timeout(text: str) -> float:
    """사람처럼 타이핑하면 한 글자에 평균 약 80ms 가 걸리므로 글 길이에 맞춰 넉넉히 기다린다."""
    return 30.0 + 0.25 * len(text)


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vm", description="VirtualMouse CLI (gh-style control tool)")
    parser.add_argument("--api", default=DEFAULT_API, help=f"Local server URL (default: {DEFAULT_API})")
    parser.add_argument("--token", default=None, help="API token (default: VMOUSE_API_TOKEN or the agent's token file)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="USB 장치, 펌웨어, 구동 상태 조회")
    sub.add_parser("token", help="에이전트 API 토큰 출력 (외부 스크립트의 Authorization 헤더용)")
    sub.add_parser("health", help="PING, 포트, 커서 좌표 조회")

    p_logs = sub.add_parser("logs", help="로컬 서버 로그 조회")
    p_logs.add_argument("--tail", type=int, default=30, help="최근 N줄 출력 (default: 30)")
    p_logs.add_argument("--clear", action="store_true", help="서버 로그 초기화")

    sub.add_parser("check-update", help="원격 릴리즈 펌웨어 버전 확인")

    p_upd = sub.add_parser("update", help="펌웨어 자동 갱신 실행")
    p_upd.add_argument("--local", action="store_true", help="로컬 번들 .hex 사용")
    p_upd.add_argument("--force", action="store_true", help="동일 버전이어도 강제 플래싱")
    p_upd.add_argument("--dry-run", action="store_true", help="다운로드 및 SHA-256 검증만 수행")

    sub.add_parser(
        "driver-install",
        help="DFU 장치(03EB:2FEF)에 WinUSB 드라이버 설치 (드라이버가 없을 때만, UAC 확인 창에서 [예] 필요)",
    )

    p_move = sub.add_parser("move", help="사람처럼 상대 곡선 이동")
    p_move.add_argument("dx", type=int)
    p_move.add_argument("dy", type=int)
    p_move.add_argument("--raw", action="store_true", help="직선 즉시 이동 (human=false)")

    p_moveto = sub.add_parser("move-to", help="화면 절대 픽셀 좌표로 이동")
    p_moveto.add_argument("x", type=int)
    p_moveto.add_argument("y", type=int)

    p_click = sub.add_parser("click", help="마우스 클릭")
    p_click.add_argument("button", nargs="?", default="L", choices=["L", "R", "M", "l", "r", "m"])

    p_clickat = sub.add_parser("click-at", help="절대 좌표 이동 후 클릭")
    p_clickat.add_argument("x", type=int)
    p_clickat.add_argument("y", type=int)
    p_clickat.add_argument("button", nargs="?", default="L", choices=["L", "R", "M", "l", "r", "m"])

    p_type = sub.add_parser("type", help="물리 USB 키보드로 텍스트 타이핑")
    p_type.add_argument("text", help="입력할 ASCII 문자열")
    p_type.add_argument("--raw", action="store_true", help="랜덤 딜레이 없이 즉시 입력")

    p_hotkey = sub.add_parser("hotkey", help="단축키 조합 입력 (예: vm hotkey ctrl c)")
    p_hotkey.add_argument("keys", nargs="+")

    p_raw = sub.add_parser("action", help="원본 JSON({}) 액션을 그대로 전송")
    p_raw.add_argument("json_payload", help='JSON 문자열 (예: \'{"action":"scroll","delta":-3}\')')

    sub.add_parser("release-all", help="눌린 모든 마우스 버튼·키보드 키 비상 해제")
    sub.add_parser("pause", help="로컬 제어 서비스 일시 중지")
    sub.add_parser("resume", help="로컬 제어 서비스 재개")
    sub.add_parser("quit", help="로컬 트레이 에이전트 종료")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    api = args.api
    cmd = args.command
    token = args.token or read_token()

    def call(method: str, path: str, body: dict[str, Any] | None = None, timeout: float = 20.0) -> Any:
        return _request(api, method, path, body, timeout=timeout, token=token)

    if cmd == "token":
        if not token:
            print(
                json.dumps(
                    {"ok": False, "error": f"토큰 파일이 없습니다: {default_token_path()} (에이전트를 한 번 실행하면 만들어집니다)"},
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            sys.exit(3)
        print(token)
        return

    if cmd == "status":
        _print_json(call("GET", "/status"))
    elif cmd == "health":
        _print_json(call("GET", "/health"))
    elif cmd == "logs":
        if args.clear:
            _print_json(call("POST", "/logs/clear", {}))
            return
        data = call("GET", "/logs")
        lines = data.get("lines", [])
        for line in lines[-args.tail :]:
            print(line)
    elif cmd == "check-update":
        _print_json(call("POST", "/firmware/check", {}))
    elif cmd == "update":
        body: dict[str, Any] = {
            "use_local": args.local,
            "force": args.force,
            "dry_run": args.dry_run,
        }
        _print_json(call("POST", "/firmware/update", body, timeout=60.0))
    elif cmd == "driver-install":
        _print_json(call("POST", "/driver/install", {}, timeout=DRIVER_INSTALL_TIMEOUT_SEC))
    elif cmd == "move":
        _print_json(call("POST", "/action", {"action": "move", "dx": args.dx, "dy": args.dy, "human": not args.raw}))
    elif cmd == "move-to":
        _print_json(call("POST", "/action", {"action": "move_to", "x": args.x, "y": args.y}))
    elif cmd == "click":
        _print_json(call("POST", "/action", {"action": "click", "button": args.button.upper()}))
    elif cmd == "click-at":
        _print_json(call("POST", "/action", {"action": "click_at", "x": args.x, "y": args.y, "button": args.button.upper()}))
    elif cmd == "type":
        body = {"action": "type", "text": args.text, "human": not args.raw}
        _print_json(call("POST", "/action", body, timeout=typing_timeout(args.text)))
    elif cmd == "hotkey":
        _print_json(call("POST", "/action", {"action": "hotkey", "keys": args.keys}))
    elif cmd == "action":
        # 임의 JSON 은 연속 동작(actions)이 길 수 있으므로 넉넉히 기다린다
        _print_json(call("POST", "/action", json.loads(args.json_payload), timeout=600.0))
    elif cmd == "release-all":
        _print_json(call("POST", "/action", {"action": "release_all"}))
    elif cmd == "pause":
        _print_json(call("POST", "/control/pause", {}))
    elif cmd == "resume":
        _print_json(call("POST", "/control/resume", {}))
    elif cmd == "quit":
        _print_json(call("POST", "/control/quit", {}))


if __name__ == "__main__":
    main()
