"""
VirtualMouse CLI (`vm`) — gh CLI 스타일 명령줄 제어 도구

로컬 VirtualMouse-Agent 서버(http://127.0.0.1:18080)와 통신하여
상태 조회, 로그 확인, 원격 펌웨어 업데이트, 마우스/키보드 조작, 서버 제어를 수행합니다.

사용 예:
  vm status
  vm logs --tail 20
  vm check-update
  vm update --local
  vm move 120 -50
  vm click-at 800 500 L
  vm type "Hello HID!"
  vm hotkey ctrl c
  vm pause / vm resume / vm quit
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_API = os.environ.get("VMOUSE_API_URL", "http://127.0.0.1:18080")


def _request(base: str, method: str, path: str, body: dict[str, Any] | None = None, timeout: float = 20.0) -> Any:
    url = f"{base.rstrip('/')}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
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
        print(json.dumps(err, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
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


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vm", description="VirtualMouse CLI (gh-style control tool)")
    parser.add_argument("--api", default=DEFAULT_API, help=f"Local server URL (default: {DEFAULT_API})")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="USB 장치, 펌웨어, 구동 상태 조회")
    sub.add_parser("health", help="PING, 포트, 커서 좌표 조회")

    p_logs = sub.add_parser("logs", help="로컬 서버 로그 조회")
    p_logs.add_argument("--tail", type=int, default=30, help="최근 N줄 출력 (default: 30)")
    p_logs.add_argument("--clear", action="store_true", help="서버 로그 초기화")

    p_check = sub.add_parser("check-update", help="원격 릴리즈 펌웨어 버전 확인")
    p_check.add_argument("--manifest", default=None, help="커스텀 latest.json URL")

    p_upd = sub.add_parser("update", help="펌웨어 자동 갱신 실행")
    p_upd.add_argument("--manifest", default=None, help="커스텀 latest.json URL")
    p_upd.add_argument("--local", action="store_true", help="로컬 번들 .hex 사용")
    p_upd.add_argument("--force", action="store_true", help="동일 버전이어도 강제 플래싱")
    p_upd.add_argument("--dry-run", action="store_true", help="다운로드 및 SHA-256 검증만 수행")

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

    if cmd == "status":
        _print_json(_request(api, "GET", "/status"))
    elif cmd == "health":
        _print_json(_request(api, "GET", "/health"))
    elif cmd == "logs":
        if args.clear:
            _print_json(_request(api, "POST", "/logs/clear", {}))
            return
        data = _request(api, "GET", "/logs")
        lines = data.get("lines", [])
        for line in lines[-args.tail :]:
            print(line)
    elif cmd == "check-update":
        body = {"manifest_url": args.manifest} if args.manifest else {}
        _print_json(_request(api, "POST", "/firmware/check", body))
    elif cmd == "update":
        body: dict[str, Any] = {
            "use_local": args.local,
            "force": args.force,
            "dry_run": args.dry_run,
        }
        if args.manifest:
            body["manifest_url"] = args.manifest
        _print_json(_request(api, "POST", "/firmware/update", body, timeout=60.0))
    elif cmd == "move":
        _print_json(_request(api, "POST", "/action", {"action": "move", "dx": args.dx, "dy": args.dy, "human": not args.raw}))
    elif cmd == "move-to":
        _print_json(_request(api, "POST", "/action", {"action": "move_to", "x": args.x, "y": args.y}))
    elif cmd == "click":
        _print_json(_request(api, "POST", "/action", {"action": "click", "button": args.button.upper()}))
    elif cmd == "click-at":
        _print_json(_request(api, "POST", "/action", {"action": "click_at", "x": args.x, "y": args.y, "button": args.button.upper()}))
    elif cmd == "type":
        _print_json(_request(api, "POST", "/action", {"action": "type", "text": args.text, "human": not args.raw}))
    elif cmd == "hotkey":
        _print_json(_request(api, "POST", "/action", {"action": "hotkey", "keys": args.keys}))
    elif cmd == "action":
        _print_json(_request(api, "POST", "/action", json.loads(args.json_payload)))
    elif cmd == "release-all":
        _print_json(_request(api, "POST", "/action", {"action": "release_all"}))
    elif cmd == "pause":
        _print_json(_request(api, "POST", "/control/pause", {}))
    elif cmd == "resume":
        _print_json(_request(api, "POST", "/control/resume", {}))
    elif cmd == "quit":
        _print_json(_request(api, "POST", "/control/quit", {}))


if __name__ == "__main__":
    main()
