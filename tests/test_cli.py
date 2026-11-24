"""cli (`vm`): 토큰을 붙여 요청하는지, `vm token` 출력 (네트워크 없이 _request 를 가짜로 바꿔 확인)."""

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from unittest import mock

from vm_test_support import TEST_TOKEN

import cli


class CliTest(unittest.TestCase):
    def run_cli(self, *argv: str) -> tuple[list[tuple], str]:
        calls: list[tuple] = []

        def fake_request(base, method, path, body=None, timeout=20.0, token=None):
            calls.append((base, method, path, body, token))
            return {"ok": True}

        out = io.StringIO()
        with mock.patch.object(cli, "_request", fake_request), mock.patch.object(
            sys, "argv", ["vm", *argv]
        ), contextlib.redirect_stdout(out):
            cli.main()
        return calls, out.getvalue()

    def test_status_sends_token_from_option(self):
        calls, _ = self.run_cli("--token", TEST_TOKEN, "status")
        self.assertEqual(calls, [("http://127.0.0.1:18080", "GET", "/status", None, TEST_TOKEN)])

    def test_token_file_is_used_by_default(self):
        with mock.patch.object(cli, "read_token", lambda: TEST_TOKEN):
            calls, _ = self.run_cli("click-at", "10", "20", "R")
        self.assertEqual(calls[0][1:3], ("POST", "/action"))
        self.assertEqual(calls[0][3], {"action": "click_at", "x": 10, "y": 20, "button": "R"})
        self.assertEqual(calls[0][4], TEST_TOKEN)

    def test_token_command_prints_token(self):
        with mock.patch.object(cli, "read_token", lambda: TEST_TOKEN):
            calls, out = self.run_cli("token")
        self.assertEqual(calls, [])
        self.assertEqual(out.strip(), TEST_TOKEN)

    def test_long_typing_gets_longer_timeout(self):
        calls: list[float] = []

        def fake_request(base, method, path, body=None, timeout=20.0, token=None):
            calls.append(timeout)
            return {"ok": True}

        with mock.patch.object(cli, "_request", fake_request), mock.patch.object(
            sys, "argv", ["vm", "--token", TEST_TOKEN, "type", "a" * 1000]
        ), contextlib.redirect_stdout(io.StringIO()):
            cli.main()
        self.assertGreaterEqual(calls[0], cli.typing_timeout("a" * 1000))
        self.assertGreater(calls[0], 200)

    def test_response_timeout_is_reported_not_traceback(self):
        """M8: 응답 대기 시간 초과는 URLError 로 감싸지지 않으므로 따로 잡아 안내한다."""

        def timeout(*args, **kwargs):
            raise TimeoutError("timed out")

        err = io.StringIO()
        with mock.patch.object(cli.urllib.request, "urlopen", timeout), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                cli._request("http://127.0.0.1:18080", "POST", "/action", {"action": "type", "text": "x"}, 1.0, TEST_TOKEN)
        self.assertEqual(ctx.exception.code, 4)
        self.assertIn("vm logs", err.getvalue())

    def test_update_has_no_manifest_option(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.run_cli("update", "--manifest", "https://evil.example/latest.json")

    def test_driver_install_waits_for_uac_and_install(self):
        """`vm driver-install` 은 에이전트가 UAC 응답·설치·확인을 모두 기다린 뒤 답할 때까지 기다린다."""
        import driver_install

        calls: list[tuple] = []

        def fake_request(base, method, path, body=None, timeout=20.0, token=None):
            calls.append((method, path, body, timeout))
            return {"ok": True, "status": "installed"}

        with mock.patch.object(cli, "_request", fake_request), mock.patch.object(
            sys, "argv", ["vm", "--token", TEST_TOKEN, "driver-install"]
        ), contextlib.redirect_stdout(io.StringIO()):
            cli.main()
        method, path, body, timeout = calls[0]
        self.assertEqual((method, path, body), ("POST", "/driver/install", {}))
        agent_wait = (
            driver_install.UAC_RESPONSE_TIMEOUT_SEC + driver_install.INSTALL_TIMEOUT_SEC + driver_install.VERIFY_TIMEOUT_SEC
        )
        self.assertGreater(timeout, agent_wait)


if __name__ == "__main__":
    unittest.main()
