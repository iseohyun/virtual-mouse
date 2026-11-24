"""auth: 토큰 생성·재사용·환경 변수·Bearer 파싱."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import vm_test_support  # noqa: F401 - host/ 경로 추가

import auth


class TokenStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "VirtualMouse" / "api-token"
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(auth.TOKEN_ENV, None)
        os.environ.pop(auth.TOKEN_FILE_ENV, None)

    def test_creates_strong_token_once_and_reuses_it(self):
        first = auth.load_or_create_token(self.path)
        self.assertTrue(auth.is_valid_token(first))
        self.assertGreaterEqual(len(first), auth.MIN_TOKEN_LENGTH)
        self.assertTrue(self.path.is_file())
        self.assertEqual(auth.load_or_create_token(self.path), first)
        self.assertEqual(auth.read_token(self.path), first)

    def test_invalid_file_is_replaced(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("short", encoding="utf-8")
        self.assertIsNone(auth.read_token(self.path))
        token = auth.load_or_create_token(self.path)
        self.assertTrue(auth.is_valid_token(token))

    def test_environment_variable_overrides_file(self):
        value = "env-token-abcdefghijklmnopqrstuvwxyz012345"
        os.environ[auth.TOKEN_ENV] = value
        self.assertEqual(auth.load_or_create_token(self.path), value)
        self.assertFalse(self.path.exists())
        self.assertEqual(auth.read_token(self.path), value)

    def test_weak_environment_token_is_rejected(self):
        os.environ[auth.TOKEN_ENV] = "too-short"
        with self.assertRaises(ValueError):
            auth.load_or_create_token(self.path)

    def test_token_file_env_changes_default_path(self):
        os.environ[auth.TOKEN_FILE_ENV] = str(self.path)
        self.assertEqual(auth.default_token_path(), self.path)


class BearerTest(unittest.TestCase):
    def test_parse_bearer(self):
        self.assertEqual(auth.parse_bearer("Bearer abc"), "abc")
        self.assertEqual(auth.parse_bearer("bearer   abc  "), "abc")
        self.assertIsNone(auth.parse_bearer("Basic abc"))
        self.assertIsNone(auth.parse_bearer("Bearer"))
        self.assertIsNone(auth.parse_bearer(None))

    def test_tokens_match(self):
        self.assertTrue(auth.tokens_match("same-token", "same-token"))
        self.assertFalse(auth.tokens_match("same-token", "other-token"))
        self.assertFalse(auth.tokens_match("same-token", None))


if __name__ == "__main__":
    unittest.main()
