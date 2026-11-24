"""dispatcher: 요청 상한, 비상 정지, 로그 가리기, 매니페스트 고정 (가짜 장치 사용)."""

from __future__ import annotations

import threading
import time
import unittest
from unittest import mock

from vm_test_support import FakeVirtualMouse, dispatcher_mod, make_fake_dispatcher

from dispatcher import (
    MAX_ACTIONS_PER_REQUEST,
    MAX_HOTKEY_KEYS,
    MAX_MOVE_DURATION_SEC,
    MAX_SCROLL_TICKS,
    MAX_SLEEP_MS,
    MAX_TYPE_CHARS,
    ActionAborted,
    UpdateInProgress,
    redact_action_for_log,
)
from updater import DEFAULT_MANIFEST_URL


def run_in_thread(func, *args) -> dict:
    """func(*args) 를 별도 스레드에서 실행하고 결과·예외를 outcome 에 담는다."""
    outcome: dict = {}

    def worker() -> None:
        try:
            outcome["result"] = func(*args)
        except Exception as exc:  # noqa: BLE001 - 결과를 확인하려고 모두 잡는다
            outcome["error"] = exc

    thread = threading.Thread(target=worker)
    thread.start()
    outcome["thread"] = thread
    return outcome


class LimitsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.d = make_fake_dispatcher(self)

    def test_sleep_limit(self):
        with self.assertRaises(ValueError):
            self.d.execute_payload({"action": "sleep", "ms": MAX_SLEEP_MS + 1})
        with self.assertRaises(ValueError):
            self.d.execute_payload({"action": "sleep", "ms": -1})
        self.assertTrue(self.d.execute_payload({"action": "sleep", "ms": 0})["ok"])

    def test_actions_count_limit(self):
        too_many = {"actions": [{"action": "cursor"}] * (MAX_ACTIONS_PER_REQUEST + 1)}
        with self.assertRaises(ValueError):
            self.d.execute_payload(too_many)
        ok = {"actions": [{"action": "cursor"}] * MAX_ACTIONS_PER_REQUEST}
        self.assertEqual(len(self.d.execute_payload(ok)["results"]), MAX_ACTIONS_PER_REQUEST)

    def test_text_length_limit(self):
        with self.assertRaises(ValueError):
            self.d.execute_payload({"action": "type", "text": "a" * (MAX_TYPE_CHARS + 1), "human": False})

    def test_scroll_limit(self):
        with self.assertRaises(ValueError):
            self.d.execute_payload({"action": "scroll", "delta": MAX_SCROLL_TICKS + 1})
        self.d.execute_payload({"action": "scroll", "delta": -3, "human": False})
        self.assertIn("W -3", self.d.mouse.commands)

    def test_duration_limit(self):
        for bad in (0, -1, MAX_MOVE_DURATION_SEC + 0.1):
            with self.assertRaises(ValueError):
                self.d.execute_payload({"action": "move", "dx": 5, "dy": 5, "duration": bad})

    def test_raw_text_with_newline_never_reaches_device(self):
        with self.assertRaises(ValueError):
            self.d.execute_payload({"action": "type", "text": "a\nBOOT", "human": False})
        self.assertFalse(any(cmd.startswith("KW") for cmd in self.d.mouse.commands))

    def test_body_must_be_object(self):
        with self.assertRaises(ValueError):
            self.d.execute_payload(["not", "an", "object"])  # type: ignore[arg-type]


class EmergencyStopTest(unittest.TestCase):
    def setUp(self) -> None:
        self.d = make_fake_dispatcher(self)

    def _run_in_thread(self, payload: dict) -> dict:
        outcome: dict = {}

        def worker() -> None:
            try:
                outcome["result"] = self.d.execute_payload(payload)
            except Exception as exc:  # noqa: BLE001 - 결과를 확인하려고 모두 잡는다
                outcome["error"] = exc

        thread = threading.Thread(target=worker)
        thread.start()
        outcome["thread"] = thread
        return outcome

    def test_release_all_interrupts_sleep(self):
        outcome = self._run_in_thread({"action": "sleep", "ms": 8000})
        time.sleep(0.2)
        started = time.monotonic()
        result = self.d.execute_payload({"action": "release_all"})
        elapsed = time.monotonic() - started
        outcome["thread"].join(timeout=5)
        self.assertTrue(result["ok"])
        self.assertLess(elapsed, 2.0)
        self.assertIsInstance(outcome.get("error"), ActionAborted)
        self.assertIn("X", self.d.mouse.commands)

    def test_release_all_interrupts_human_typing(self):
        outcome = self._run_in_thread({"action": "type", "text": "a" * 300})
        time.sleep(0.3)
        started = time.monotonic()
        self.d.execute_payload({"action": "release_all"})
        self.assertLess(time.monotonic() - started, 2.0)
        outcome["thread"].join(timeout=5)
        self.assertIsInstance(outcome.get("error"), ActionAborted)
        typed = sum(1 for cmd in self.d.mouse.commands if cmd.startswith("KW"))
        self.assertLess(typed, 300)

    def test_release_all_cancels_remaining_batch(self):
        outcome = self._run_in_thread({"actions": [{"action": "sleep", "ms": 3000}, {"action": "click"}]})
        time.sleep(0.2)
        self.d.execute_payload({"action": "release_all"})
        outcome["thread"].join(timeout=5)
        self.assertIsInstance(outcome.get("error"), ActionAborted)
        self.assertNotIn("P L", self.d.mouse.commands)

    def test_next_request_runs_normally_after_abort(self):
        outcome = self._run_in_thread({"action": "sleep", "ms": 3000})
        time.sleep(0.2)
        self.d.execute_payload({"action": "release_all"})
        outcome["thread"].join(timeout=5)
        self.assertTrue(self.d.execute_payload({"action": "sleep", "ms": 10})["ok"])


class LogRedactionTest(unittest.TestCase):
    def test_typed_text_is_not_logged(self):
        d = make_fake_dispatcher(self)
        d.execute_payload({"action": "type", "text": "secret-pw-123", "human": False})
        log_text = "\n".join(d.logger.list_lines())
        self.assertNotIn("secret-pw-123", log_text)
        self.assertIn("<13 chars>", log_text)

    def test_redact_rules(self):
        self.assertEqual(redact_action_for_log({"action": "key_tap", "key": "p"})["key"], "<char>")
        self.assertEqual(redact_action_for_log({"action": "key_tap", "key": "enter"})["key"], "enter")
        self.assertEqual(redact_action_for_log({"action": "key_press", "key": 4})["key"], "<char>")
        self.assertEqual(redact_action_for_log({"action": "hotkey", "keys": ["ctrl", "c"]})["keys"], ["ctrl", "c"])
        self.assertEqual(redact_action_for_log({"action": "hotkey", "keys": ["shift", "a"]})["keys"], ["shift", "<char>"])
        self.assertEqual(redact_action_for_log("oops")["action"], "<invalid>")  # type: ignore[arg-type]


class FirmwareManifestTest(unittest.TestCase):
    def test_request_manifest_url_is_ignored(self):
        d = make_fake_dispatcher(self)
        seen: dict = {}

        def fake_check(current_version, manifest_url=DEFAULT_MANIFEST_URL):
            seen["url"] = manifest_url
            return {
                "current_version": current_version,
                "remote_version": "1.1.0",
                "update_available": False,
                "firmware_url": "https://example.invalid/fw.hex",
                "sha256": "0" * 64,
                "notes": "",
            }

        with mock.patch.object(dispatcher_mod, "check_for_update", fake_check):
            result = d.update_firmware({"manifest_url": "https://evil.example/latest.json"})
        self.assertEqual(seen["url"], DEFAULT_MANIFEST_URL)
        self.assertFalse(result["updated"])
        self.assertNotIn("BOOT", d.mouse.commands)


class StopCancelsQueuedRequestsTest(unittest.TestCase):
    """H1: 비상 정지·일시 중지·종료는 진행 중인 동작과 그 전에 줄 서 있던 요청을 모두 멈춘다."""

    def setUp(self) -> None:
        self.d = make_fake_dispatcher(self)

    def test_queued_request_is_cancelled_by_emergency_stop(self):
        running = run_in_thread(self.d.execute_payload, {"action": "sleep", "ms": 3000})
        time.sleep(0.2)  # running 이 잠금을 쥔다
        queued = run_in_thread(self.d.execute_payload, {"action": "type", "text": "should-not-type", "human": False})
        time.sleep(0.2)  # queued 가 잠금을 기다린다
        started = time.monotonic()
        result = self.d.execute_payload({"action": "release_all"})
        running["thread"].join(timeout=5)
        queued["thread"].join(timeout=5)
        self.assertTrue(result["ok"])
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertIsInstance(running.get("error"), ActionAborted)
        self.assertIsInstance(queued.get("error"), ActionAborted)
        self.assertFalse(any(cmd.startswith("KW") for cmd in self.d.mouse.commands))

    def test_request_after_stop_runs_normally(self):
        self.d.execute_payload({"action": "release_all"})
        self.assertTrue(self.d.execute_payload({"action": "sleep", "ms": 10})["ok"])

    def test_pause_interrupts_running_action(self):
        running = run_in_thread(self.d.execute_payload, {"action": "sleep", "ms": 5000})
        time.sleep(0.2)
        started = time.monotonic()
        result = self.d.pause()
        running["thread"].join(timeout=5)
        self.assertTrue(result["paused"])
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertIsInstance(running.get("error"), ActionAborted)
        with self.assertRaises(RuntimeError):
            self.d.execute_payload({"action": "click"})

    def test_close_interrupts_running_typing(self):
        running = run_in_thread(self.d.execute_payload, {"action": "type", "text": "a" * 300})
        time.sleep(0.3)
        mouse = self.d.mouse
        started = time.monotonic()
        self.d.close()
        running["thread"].join(timeout=5)
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertIsInstance(running.get("error"), ActionAborted)
        self.assertIn("X", mouse.commands)


class DeviceCommandValidationTest(unittest.TestCase):
    """M1·M2·L1: 장치로 가기 전에 값과 글 전체를 검사한다."""

    def setUp(self) -> None:
        self.d = make_fake_dispatcher(self)

    def test_button_injection_is_rejected(self):
        for action in ("click", "press", "release", "double_click"):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.d.execute_payload({"action": action, "button": "L\nBOOT"})
        with self.assertRaises(ValueError):
            self.d.execute_payload({"action": "click_at", "x": 10, "y": 10, "button": "L\nBOOT"})
        self.assertNotIn("BOOT", self.d.mouse.commands)

    def test_valid_buttons_are_normalized(self):
        result = self.d.execute_payload({"action": "click", "button": "r", "human": False})
        self.assertEqual(result["result"]["button"], "R")
        self.assertIn("C R", self.d.mouse.commands)

    def test_move_out_of_int16_range_is_rejected(self):
        with self.assertRaises(ValueError):
            self.d.execute_payload({"action": "move", "dx": 40000, "dy": 0, "human": False})
        with self.assertRaises(ValueError):
            self.d.execute_payload({"action": "move_to", "x": 99999, "y": 0})
        self.assertFalse(any(cmd.startswith("M ") for cmd in self.d.mouse.commands))

    def test_click_at_uses_fake_cursor_only(self):
        result = self.d.execute_payload({"action": "click_at", "x": 400, "y": 300, "button": "L", "duration": 0.05})
        self.assertEqual(result["result"]["cursor"], {"x": 400, "y": 300})

    def test_human_typing_rejects_whole_text_before_typing(self):
        with self.assertRaises(ValueError):
            self.d.execute_payload({"action": "type", "text": "password 한글"})
        self.assertFalse(any(cmd.startswith("KW") for cmd in self.d.mouse.commands))

    def test_human_typing_converts_windows_newlines(self):
        self.d.execute_payload({"action": "type", "text": "ab\r\ncd"})
        typed = [cmd for cmd in self.d.mouse.commands if cmd.startswith("KW")]
        self.assertEqual(typed, ["KW a", "KW b", "KW c", "KW d"])
        self.assertIn("KP 40", self.d.mouse.commands)  # Enter

    def test_hotkey_key_count_limit(self):
        with self.assertRaises(ValueError):
            self.d.execute_payload({"action": "hotkey", "keys": ["a"] * (MAX_HOTKEY_KEYS + 1)})


class ReconnectTest(unittest.TestCase):
    """M3: ping 이 (예외 없이) 실패하면 옛 핸들을 닫고 다시 연결한다."""

    def test_reconnects_after_failed_ping(self):
        d = make_fake_dispatcher(self)
        old = d.mouse
        FakeVirtualMouse.ping_script = [False]  # 다음 ping 한 번만 실패
        self.assertTrue(d.execute_payload({"action": "click", "human": False})["ok"])
        self.assertTrue(old.closed)
        self.assertIsNot(d.mouse, old)
        self.assertIn("C L", d.mouse.commands)

    def test_connect_error_is_logged_once(self):
        d = make_fake_dispatcher(self)
        d._disconnect_unlocked()
        with mock.patch.object(dispatcher_mod, "VirtualMouse", side_effect=RuntimeError("COM9 access denied")):
            for _ in range(3):
                d.execute_payload({"action": "cursor"})
                with self.assertRaises(RuntimeError):
                    d.execute_payload({"action": "click"})
        failures = [line for line in d.logger.list_lines() if "COM9 access denied" in line]
        self.assertEqual(len(failures), 1)


class LockScopeTest(unittest.TestCase):
    """M6: 긴 동작 중에도 상태 조회가 멈추지 않고, 네트워크 조회는 잠금 밖에서 한다."""

    def setUp(self) -> None:
        self.d = make_fake_dispatcher(self)
        patcher = mock.patch.object(dispatcher_mod, "detect_device_state", lambda **kw: {"state": "ready"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_status_returns_busy_snapshot_during_long_action(self):
        self.d.status()  # 마지막 상태 기록
        running = run_in_thread(self.d.execute_payload, {"action": "sleep", "ms": 3000})
        time.sleep(0.2)
        started = time.monotonic()
        status = self.d.status()
        health = self.d.health()
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertTrue(status["busy"])
        self.assertEqual(status["state"], "ready")
        self.assertTrue(health["busy"])
        self.d.execute_payload({"action": "release_all"})
        running["thread"].join(timeout=5)

    def test_firmware_check_runs_network_outside_lock(self):
        seen = {}

        def fake_check(current_version, manifest_url=DEFAULT_MANIFEST_URL):
            seen["locked"] = self.d._lock.locked()
            return {"remote_version": "1.1.0", "update_available": False, "firmware_url": "", "sha256": "", "notes": ""}

        with mock.patch.object(dispatcher_mod, "check_for_update", fake_check):
            self.d.check_firmware()
        self.assertFalse(seen["locked"])

    def test_close_during_download_cancels_update_before_flashing(self):
        """종료 요청이 다운로드 도중에 오면 플래싱을 시작하지 않는다 (펌웨어가 지워진 채 끝나는 일 방지)."""
        info = {
            "remote_version": "9.9.9",
            "update_available": True,
            "firmware_url": "https://example.invalid/fw.hex",
            "sha256": "0" * 64,
            "notes": "",
        }

        def slow_download(url, sha):
            time.sleep(0.4)
            return "fw.hex"

        flashed = []
        patches = [
            mock.patch.object(dispatcher_mod, "check_for_update", lambda current, manifest_url=None: info),
            mock.patch.object(dispatcher_mod, "download_and_verify_firmware", slow_download),
            mock.patch.object(dispatcher_mod, "flash_hex_via_dfu", lambda path: flashed.append(path)),
            mock.patch.object(dispatcher_mod, "wait_for_dfu_ready", lambda timeout=0: True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        update = run_in_thread(self.d.update_firmware, {})
        time.sleep(0.1)
        self.assertTrue(self.d.is_flashing())
        self.d.close()
        update["thread"].join(timeout=5)
        self.assertIsInstance(update.get("error"), RuntimeError)
        self.assertEqual(flashed, [])
        self.assertFalse(self.d.is_flashing())

    def test_concurrent_firmware_update_is_rejected(self):
        self.assertTrue(self.d._update_lock.acquire(blocking=False))
        try:
            with self.assertRaises(UpdateInProgress):
                self.d.update_firmware({})
        finally:
            self.d._update_lock.release()


if __name__ == "__main__":
    unittest.main()
