"""
VirtualMouse 로컬 API 접근 토큰.

- 에이전트가 처음 실행될 때 무작위 토큰(256비트)을 만들어 사용자 프로필 폴더에 저장하고, 이후에는 같은 값을 쓴다.
  기본 위치: %LOCALAPPDATA%\\VirtualMouse\\api-token (Windows), ~/.virtualmouse/api-token (그 밖)
- 모든 API 요청은 `Authorization: Bearer <토큰>` 헤더가 있어야 한다 (http_api.py가 검사).
- 환경 변수 VMOUSE_API_TOKEN이 있으면 파일 대신 그 값을 쓴다 (CI·고급 사용자용).
- 토큰을 바꾸려면 파일을 지우고 에이전트를 다시 시작한다.

사용처: server.py(토큰 준비), http_api.py(검사), cli.py·tray.py(토큰 읽기/복사)
"""

from __future__ import annotations

import hmac
import os
import re
import secrets
from pathlib import Path

TOKEN_ENV = "VMOUSE_API_TOKEN"
TOKEN_FILE_ENV = "VMOUSE_TOKEN_FILE"
MIN_TOKEN_LENGTH = 32
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]{%d,256}$" % MIN_TOKEN_LENGTH)


def default_token_path() -> Path:
    """토큰 파일 위치. VMOUSE_TOKEN_FILE로 바꿀 수 있다 (테스트용)."""
    override = os.environ.get(TOKEN_FILE_ENV)
    if override:
        return Path(override)
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "VirtualMouse" / "api-token"
    return Path.home() / ".virtualmouse" / "api-token"


def is_valid_token(value: str | None) -> bool:
    return bool(value) and bool(_TOKEN_RE.match(value))


def read_token(path: Path | None = None) -> str | None:
    """저장된 토큰을 읽는다. 없거나 형식이 틀리면 None (새로 만들지 않는다)."""
    env_value = os.environ.get(TOKEN_ENV, "").strip()
    if env_value:
        return env_value if is_valid_token(env_value) else None
    token_path = path or default_token_path()
    try:
        value = token_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value if is_valid_token(value) else None


def load_or_create_token(path: Path | None = None) -> str:
    """저장된 토큰을 돌려주고, 없으면 새로 만들어 저장한다."""
    env_value = os.environ.get(TOKEN_ENV, "").strip()
    if env_value:
        if not is_valid_token(env_value):
            raise ValueError(
                f"{TOKEN_ENV} must be at least {MIN_TOKEN_LENGTH} URL-safe characters (A-Z, a-z, 0-9, '-', '_')."
            )
        return env_value

    token_path = path or default_token_path()
    existing = read_token(token_path)
    if existing:
        return existing

    token = secrets.token_urlsafe(32)  # 43자, 256비트
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(token, encoding="utf-8")
    return token


def tokens_match(expected: str, provided: str | None) -> bool:
    """타이밍 공격을 피하는 비교."""
    if not provided:
        return False
    return hmac.compare_digest(expected.encode("utf-8"), provided.encode("utf-8"))


def parse_bearer(header_value: str | None) -> str | None:
    """`Authorization: Bearer <토큰>` 헤더에서 토큰만 꺼낸다."""
    if not header_value:
        return None
    scheme, _, value = header_value.strip().partition(" ")
    if scheme.lower() != "bearer":
        return None
    value = value.strip()
    return value or None
