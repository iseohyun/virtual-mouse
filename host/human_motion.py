"""
Human-like Mouse Motion & Timing Engine

외부 호출자는 목표 좌표나 동작만 전달하면, 이 모듈이 내부적으로:
1. 3차 베지어 곡선(Cubic Bezier) 경로 생성
2. 가속/감속 속도 프로파일 (Minimum-Jerk / Ease-in-out)
3. 미세 손떨림(Micro-Jitter) 및 긴 거리 이동 시 자연스러운 미세 오버슈트
4. Windows GetCursorPos 기반 실시간 피드백 보정 (DPI/마우스 가속과 무관하게 정확한 픽셀 도달)
5. 사람 같은 클릭 유지 시간(Dwell/Hold) 랜덤화
을 자동으로 처리합니다.
"""

from __future__ import annotations

import ctypes
import math
import random
import time
from dataclasses import dataclass
from typing import Iterable, Tuple

from keycodes import resolve_keycode
from mouse_client import VirtualMouse


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def enable_dpi_awareness() -> None:
    """고해상도 DPI 배율 환경에서도 실제 물리 픽셀 좌표를 얻도록 DPI Awareness를 활성화합니다."""
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def get_cursor_pos() -> Tuple[int, int]:
    """현재 Windows 화면 커서의 절대 픽셀 좌표를 반환합니다."""
    pt = _POINT()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
        raise OSError(
            "GetCursorPos failed (비대화형 세션에서는 커서 좌표를 읽을 수 없습니다. 일반 사용자 터미널에서 서버를 실행해 주세요.)"
        )
    return int(pt.x), int(pt.y)


def get_cursor_pos_safe() -> Tuple[int, int] | None:
    """커서 좌표를 조회하되, 비대화형 세션 등 조회 불가 환경에서는 None을 반환합니다."""
    try:
        return get_cursor_pos()
    except OSError:
        return None


def _minimum_jerk(t: float) -> float:
    """인간의 팔/손 움직임에 가장 가까운 최소 저크(Minimum-Jerk) 보간 함수 (0..1 -> 0..1)."""
    return (10.0 * t**3) - (15.0 * t**4) + (6.0 * t**5)


def _cubic_bezier(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
    t: float,
) -> Tuple[float, float]:
    u = 1.0 - t
    x = (u**3) * p0[0] + 3 * (u**2) * t * p1[0] + 3 * u * (t**2) * p2[0] + (t**3) * p3[0]
    y = (u**3) * p0[1] + 3 * (u**2) * t * p1[1] + 3 * u * (t**2) * p2[1] + (t**3) * p3[1]
    return x, y


@dataclass
class HumanProfile:
    min_duration: float = 0.14
    max_duration: float = 0.75
    speed_px_per_sec: float = 1100.0
    curve_variance: float = 0.18
    jitter_px: float = 0.8
    overshoot_chance: float = 0.30
    overshoot_min_dist: float = 180.0
    click_hold_range: Tuple[float, float] = (0.045, 0.095)
    pre_click_dwell_range: Tuple[float, float] = (0.035, 0.085)
    double_click_gap_range: Tuple[float, float] = (0.065, 0.125)
    type_interval_range: Tuple[float, float] = (0.038, 0.115)
    key_hold_range: Tuple[float, float] = (0.035, 0.080)


class HumanMouseController:
    """VirtualMouse 위에 사람과 유사한 움직임/클릭 물리 엔진을 씌운 컨트롤러."""

    def __init__(self, mouse: VirtualMouse, profile: HumanProfile | None = None):
        self.mouse = mouse
        self.profile = profile or HumanProfile()

    def _compute_duration(self, dist: float, duration: float | None) -> float:
        if duration is not None and duration > 0:
            return float(duration)
        # Fitts's Law 스타일: 거리가 멀수록 천천히 늘어나며 약간의 랜덤 변동 추가
        base = (dist / self.profile.speed_px_per_sec) + 0.12 * math.log1p(dist / 40.0)
        randomized = base * random.uniform(0.85, 1.18)
        return max(self.profile.min_duration, min(self.profile.max_duration, randomized))

    def move_relative_human(self, dx: int, dy: int, duration: float | None = None) -> None:
        """현재 위치에서 (dx, dy)만큼 사람처럼 곡선·가감속으로 상대 이동합니다."""
        dx = int(round(dx))
        dy = int(round(dy))
        dist = math.hypot(dx, dy)
        if dist < 1.0:
            return

        total_dur = self._compute_duration(dist, duration)
        steps = max(10, min(90, int(total_dur / 0.008)))

        # 직선 벡터와 수직(법선) 벡터 계산 -> 베지어 제어점 생성
        nx = -dy / dist
        ny = dx / dist
        curve_sign = random.choice([-1.0, 1.0])
        arc_mag = dist * random.uniform(0.05, self.profile.curve_variance) * curve_sign

        p0 = (0.0, 0.0)
        p1 = (
            dx * random.uniform(0.22, 0.38) + nx * arc_mag * random.uniform(0.6, 1.1),
            dy * random.uniform(0.22, 0.38) + ny * arc_mag * random.uniform(0.6, 1.1),
        )
        p2 = (
            dx * random.uniform(0.62, 0.80) + nx * arc_mag * random.uniform(0.3, 0.9),
            dy * random.uniform(0.62, 0.80) + ny * arc_mag * random.uniform(0.3, 0.9),
        )
        p3 = (float(dx), float(dy))

        sent_x = 0
        sent_y = 0
        start_time = time.perf_counter()

        for i in range(1, steps + 1):
            progress = i / steps
            eased = _minimum_jerk(progress)
            bx, by = _cubic_bezier(p0, p1, p2, p3, eased)

            # 중간 구간에만 아주 미세한 손떨림 추가 (시작/끝점에서는 0으로 수렴)
            if 0.1 < progress < 0.9 and self.profile.jitter_px > 0:
                envelope = math.sin(progress * math.pi)
                bx += random.uniform(-self.profile.jitter_px, self.profile.jitter_px) * envelope
                by += random.uniform(-self.profile.jitter_px, self.profile.jitter_px) * envelope

            target_x = int(round(bx))
            target_y = int(round(by))
            step_x = target_x - sent_x
            step_y = target_y - sent_y

            if step_x != 0 or step_y != 0:
                self.mouse.move(step_x, step_y)
                sent_x += step_x
                sent_y += step_y

            target_time = start_time + total_dur * progress
            remaining = target_time - time.perf_counter()
            if remaining > 0:
                time.sleep(remaining)

        # 반올림 잔여 오차 정리
        rem_x = dx - sent_x
        rem_y = dy - sent_y
        if rem_x != 0 or rem_y != 0:
            self.mouse.move(rem_x, rem_y)

    def move_to_human(
        self,
        target_x: int,
        target_y: int,
        duration: float | None = None,
        tolerance: int = 1,
    ) -> Tuple[int, int]:
        """
        Windows 화면의 절대 픽셀 좌표 (target_x, target_y)로 사람처럼 자연스럽게 이동합니다.
        DPI/마우스 가속 설정이 켜져 있어도 GetCursorPos 피드백으로 정확히 목표에 안착합니다.
        """
        target_x = int(round(target_x))
        target_y = int(round(target_y))
        cur_x, cur_y = get_cursor_pos()
        dx = target_x - cur_x
        dy = target_y - cur_y
        dist = math.hypot(dx, dy)

        if dist <= tolerance:
            return cur_x, cur_y

        # 긴 거리 이동 시 가끔 자연스러운 미세 오버슈트 적용
        if dist >= self.profile.overshoot_min_dist and random.random() < self.profile.overshoot_chance:
            over_px = random.uniform(3.0, 8.0)
            ux, uy = dx / dist, dy / dist
            over_dx = int(round(dx + ux * over_px + random.uniform(-2.0, 2.0)))
            over_dy = int(round(dy + uy * over_px + random.uniform(-2.0, 2.0)))
            self.move_relative_human(over_dx, over_dy, duration=duration)
            time.sleep(random.uniform(0.025, 0.06))
        else:
            self.move_relative_human(dx, dy, duration=duration)

        # Windows 포인터 가속/DPI 차이로 남은 오차를 자연스럽게 미세 보정 (최대 6회)
        for _ in range(6):
            cur_x, cur_y = get_cursor_pos()
            err_x = target_x - cur_x
            err_y = target_y - cur_y
            if abs(err_x) <= tolerance and abs(err_y) <= tolerance:
                break

            # 과보정 방지를 위해 오차가 크면 0.75배로 감쇠하며 접근
            err_dist = math.hypot(err_x, err_y)
            scale = 0.75 if err_dist > 12 else 1.0
            step_dx = int(round(err_x * scale))
            step_dy = int(round(err_y * scale))
            if step_dx == 0 and err_x != 0:
                step_dx = 1 if err_x > 0 else -1
            if step_dy == 0 and err_y != 0:
                step_dy = 1 if err_y > 0 else -1

            if err_dist > 25:
                self.move_relative_human(step_dx, step_dy, duration=random.uniform(0.06, 0.12))
            else:
                self.mouse.move(step_dx, step_dy)
                time.sleep(random.uniform(0.012, 0.028))

        return get_cursor_pos()

    def click_human(self, button: str = "L") -> None:
        """사람처럼 자연스러운 누름 유지 시간(45~95ms)을 두고 클릭합니다."""
        self.mouse.press(button)
        time.sleep(random.uniform(*self.profile.click_hold_range))
        self.mouse.release(button)

    def double_click_human(self, button: str = "L") -> None:
        self.click_human(button)
        time.sleep(random.uniform(*self.profile.double_click_gap_range))
        self.click_human(button)

    def click_at_human(
        self,
        x: int,
        y: int,
        button: str = "L",
        duration: float | None = None,
    ) -> Tuple[int, int]:
        pos = self.move_to_human(x, y, duration=duration)
        time.sleep(random.uniform(*self.profile.pre_click_dwell_range))
        self.click_human(button)
        return pos

    def drag_human(
        self,
        from_x: int,
        from_y: int,
        to_x: int,
        to_y: int,
        button: str = "L",
        duration: float | None = None,
    ) -> Tuple[int, int]:
        self.move_to_human(from_x, from_y)
        time.sleep(random.uniform(*self.profile.pre_click_dwell_range))
        self.mouse.press(button)
        time.sleep(random.uniform(0.04, 0.09))
        try:
            pos = self.move_to_human(to_x, to_y, duration=duration)
            time.sleep(random.uniform(0.03, 0.07))
        finally:
            self.mouse.release(button)
        return pos

    def scroll_human(self, delta: int) -> None:
        """휠 스크롤을 1~2틱씩 사람처럼 자연스러운 간격으로 보냅니다."""
        remaining = int(delta)
        direction = 1 if remaining > 0 else -1
        remaining = abs(remaining)
        while remaining > 0:
            step = min(remaining, random.choice([1, 1, 2]))
            self.mouse.scroll(direction * step)
            remaining -= step
            if remaining > 0:
                time.sleep(random.uniform(0.035, 0.095))

    def type_human(self, text: str) -> None:
        """ASCII 문자열을 한 글자씩 사람처럼 자연스러운 랜덤 간격으로 타이핑합니다."""
        for ch in text:
            if ch == "\n":
                self.key_tap_human("enter")
                time.sleep(random.uniform(0.07, 0.16))
            elif ch == "\t":
                self.key_tap_human("tab")
                time.sleep(random.uniform(0.05, 0.12))
            else:
                self.mouse.key_write_text(ch)
                delay = random.uniform(*self.profile.type_interval_range)
                if ch == " ":
                    delay += random.uniform(0.015, 0.05)
                time.sleep(delay)

    def key_tap_human(self, key: str | int) -> None:
        code = resolve_keycode(key)
        self.mouse.key_press(code)
        time.sleep(random.uniform(*self.profile.key_hold_range))
        self.mouse.key_release(code)

    def hotkey_human(self, keys: Iterable[str | int]) -> None:
        """단축키 조합(예: ['ctrl', 'c'])을 사람처럼 순차 누름 -> 짧은 유지 -> 역순 해제합니다."""
        codes = [resolve_keycode(k) for k in keys]
        if not codes:
            return
        pressed: list[int] = []
        try:
            for code in codes:
                self.mouse.key_press(code)
                pressed.append(code)
                time.sleep(random.uniform(0.025, 0.055))
            time.sleep(random.uniform(0.04, 0.085))
        finally:
            for code in reversed(pressed):
                self.mouse.key_release(code)
                time.sleep(random.uniform(0.015, 0.035))
