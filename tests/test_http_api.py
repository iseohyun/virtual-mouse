"""http_api: 출처(Origin·Host) 검사, 토큰 인증, 요청 크기, 정적 파일, CORS."""

from __future__ import annotations

import json
import unittest

from vm_test_support import TEST_TOKEN, ApiServer, FakeDispatcher

from http_api import MAX_BODY_BYTES, PUBLIC_DASHBOARD_ORIGIN

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}
JSON = {"Content-Type": "application/json"}


class HttpApiSecurityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dispatcher = FakeDispatcher()
        self.server = ApiServer(self.dispatcher)
        self.addCleanup(self.server.close)

    def post_action(self, payload: dict, headers: dict | None = None):
        all_headers = {**JSON, **AUTH, **(headers or {})}
        return self.server.request("POST", "/action", json.dumps(payload), all_headers)

    # --- 출처 검사 ---
    def test_rejects_foreign_host_header(self):
        status, _, _ = self.server.request("GET", "/status", headers=AUTH, host="attacker.example:18080")
        self.assertEqual(status, 421)

    def test_rejects_foreign_origin_without_cors_headers(self):
        status, headers, _ = self.post_action({"action": "cursor"}, {"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        self.assertNotIn("access-control-allow-origin", headers)
        self.assertEqual(self.dispatcher.calls, [])

    def test_rejects_cross_site_request_without_origin(self):
        status, _, _ = self.server.request("GET", "/status", headers={**AUTH, "Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 403)

    def test_rejects_text_plain_post(self):
        status, _, _ = self.server.request(
            "POST", "/action", '{"action": "cursor"}', {**AUTH, "Content-Type": "text/plain"}
        )
        self.assertEqual(status, 415)
        self.assertEqual(self.dispatcher.calls, [])

    def test_rejects_oversized_body(self):
        body = json.dumps({"action": "cursor", "pad": "a" * (MAX_BODY_BYTES + 10)})
        status, _, _ = self.server.request("POST", "/action", body, {**JSON, **AUTH})
        self.assertEqual(status, 413)

    # --- 토큰 인증 ---
    def test_api_requires_token(self):
        status, headers, data = self.server.request("GET", "/status")
        self.assertEqual(status, 401)
        self.assertIn("bearer", headers.get("www-authenticate", "").lower())
        self.assertTrue(json.loads(data)["auth_required"])
        self.assertEqual(self.dispatcher.calls, [])

    def test_wrong_token_is_rejected(self):
        status, _, _ = self.server.request("GET", "/status", headers={"Authorization": "Bearer wrong-token"})
        self.assertEqual(status, 401)

    def test_post_without_token_does_not_run_action(self):
        status, _, _ = self.server.request("POST", "/action", json.dumps({"action": "click"}), JSON)
        self.assertEqual(status, 401)
        self.assertEqual(self.dispatcher.calls, [])

    def test_valid_token_runs_action(self):
        status, _, data = self.post_action({"action": "cursor"})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(data)["ok"])
        self.assertEqual(self.dispatcher.calls, [("action", {"action": "cursor"})])

    def test_auth_error_is_readable_by_dashboard(self):
        """대시보드가 '토큰 필요'를 알 수 있게 401에도 허용 출처의 CORS 헤더를 붙인다."""
        status, headers, _ = self.server.request("GET", "/status", headers={"Origin": PUBLIC_DASHBOARD_ORIGIN})
        self.assertEqual(status, 401)
        self.assertEqual(headers.get("access-control-allow-origin"), PUBLIC_DASHBOARD_ORIGIN)

    # --- CORS 프리플라이트 ---
    def test_preflight_from_dashboard_needs_no_token(self):
        status, headers, _ = self.server.request(
            "OPTIONS",
            "/action",
            headers={
                "Origin": PUBLIC_DASHBOARD_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("access-control-allow-origin"), PUBLIC_DASHBOARD_ORIGIN)
        self.assertIn("Authorization", headers.get("access-control-allow-headers", ""))
        self.assertEqual(headers.get("access-control-allow-private-network"), "true")
        self.assertTrue(int(headers.get("access-control-max-age", "0")) > 0)

    def test_local_guide_origin_is_allowed(self):
        origin = f"http://localhost:{self.server.port}"
        status, headers, _ = self.post_action({"action": "cursor"}, {"Origin": origin})
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("access-control-allow-origin"), origin)

    # --- 정적 파일 ---
    def test_dashboard_page_is_served_without_token(self):
        status, headers, data = self.server.request("GET", "/guide")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("content-type", ""))
        self.assertIn(b"Virtual Mouse", data)

    def test_guide_path_does_not_serve_other_files(self):
        status, _, _ = self.server.request("GET", "/guide/../host/server.py")
        self.assertEqual(status, 404)
        status, _, _ = self.server.request("GET", "/guide/releases/latest.json")
        self.assertEqual(status, 404)

    # --- 엔드포인트 ---
    def test_firmware_check_takes_no_manifest_from_request(self):
        status, _, _ = self.server.request(
            "POST", "/firmware/check", json.dumps({"manifest_url": "https://evil.example/latest.json"}), {**JSON, **AUTH}
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.dispatcher.calls, ["check_firmware"])

    def test_quit_requires_token(self):
        status, _, _ = self.server.request("POST", "/control/quit", "{}", JSON)
        self.assertEqual(status, 401)
        self.assertEqual(self.server.quit_requests, 0)


class ExclusiveBindTest(unittest.TestCase):
    """M4: 같은 포트에 두 번째 서버(에이전트 중복 실행 등)가 바인드되지 않는다."""

    def test_second_server_on_same_port_fails(self):
        from http.server import BaseHTTPRequestHandler

        from http_api import ExclusiveThreadingHTTPServer

        first = ExclusiveThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        self.addCleanup(first.server_close)
        port = first.server_address[1]
        with self.assertRaises(OSError):
            second = ExclusiveThreadingHTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
            second.server_close()


class UpdateInProgressTest(unittest.TestCase):
    def test_concurrent_update_returns_409(self):
        from dispatcher import UpdateInProgress

        class BusyDispatcher(FakeDispatcher):
            def update_firmware(self, payload: dict) -> dict:
                raise UpdateInProgress("이미 펌웨어 업데이트가 진행 중입니다.")

        server = ApiServer(BusyDispatcher())
        self.addCleanup(server.close)
        status, _, data = server.request("POST", "/firmware/update", "{}", {**JSON, **AUTH})
        self.assertEqual(status, 409)
        self.assertTrue(json.loads(data)["busy"])


class HttpApiNoTokenModeTest(unittest.TestCase):
    """token=None 은 테스트 전용 모드: 인증만 끄고 출처 검사는 그대로다."""

    def test_origin_checks_still_apply(self):
        server = ApiServer(FakeDispatcher(), token=None)
        self.addCleanup(server.close)
        status, _, _ = server.request("GET", "/status", headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        status, _, _ = server.request("GET", "/status")
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
