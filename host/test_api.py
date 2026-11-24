"""
로컬 HTTP JSON API 서버(http://127.0.0.1:18080) 연동 수동 테스트 스크립트 (실제 Arduino 필요).
외부 프로그램처럼 JSON({})만 보내서 사람 같은 곡선 이동 및 절대 좌표 이동을 검증합니다.
API 토큰은 에이전트가 만든 토큰 파일(auth.py)에서 자동으로 읽습니다.
자동 단위 테스트는 저장소 루트의 tests/ 폴더에 있습니다.
"""

from __future__ import annotations

import json
import urllib.request

from auth import read_token

BASE_URL = "http://127.0.0.1:18080"


def _headers(extra: dict | None = None) -> dict:
    headers = dict(extra or {})
    token = read_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def post_action(payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/action",
        data=data,
        headers=_headers({"Content-Type": "application/json"}),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_health() -> dict:
    req = urllib.request.Request(f"{BASE_URL}/health", headers=_headers())
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    health = get_health()
    print("Health:", health)
    cursor = health.get("cursor")

    print("1) 상대 곡선 이동 테스트 (+220, +120)...")
    print("  ->", post_action({"action": "move", "dx": 220, "dy": 120}))

    if cursor is not None:
        print(f"2) 원래 절대 좌표({cursor['x']}, {cursor['y']})로 사람처럼 복귀 테스트...")
        print("  ->", post_action({"action": "move_to", "x": cursor["x"], "y": cursor["y"]}))
    else:
        print("2) 상대 곡선 이동으로 원위치 복귀 테스트 (-220, -120)...")
        print("  ->", post_action({"action": "move", "dx": -220, "dy": -120}))

    print("테스트 완료!")


if __name__ == "__main__":
    main()
