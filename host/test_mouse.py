"""
VirtualMouse 기본 동작 테스트 스크립트.
실행 시 PING 확인 후 마우스 커서를 작은 사각형 경로로 이동시킵니다.
"""

import sys
import time
from mouse_client import VirtualMouse


def main() -> None:
    port = sys.argv[1] if len(sys.argv) > 1 else None
    with VirtualMouse(port=port) as vm:
        print(f"Connected to {vm.port}")
        if not vm.ping():
            raise RuntimeError("PING failed: 펌웨어 응답이 없습니다.")
        print("PING -> PONG (정상)")

        print("사각형 경로로 커서를 부드럽게 이동합니다...")
        for dx, dy in [(120, 0), (0, 120), (-120, 0), (0, -120)]:
            vm.move_smooth(dx, dy, steps=15, duration=0.2)
            time.sleep(0.1)

        print("테스트 완료!")


if __name__ == "__main__":
    main()
