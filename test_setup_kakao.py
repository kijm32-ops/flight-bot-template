import unittest
from unittest.mock import Mock, patch

import setup_kakao
from kakao_auth import KakaoAuthError


class TokenErrorTests(unittest.TestCase):
    @patch("setup_kakao.requests.post")
    def test_token_error_exposes_safe_kakao_diagnostics_without_request_secrets(self, post):
        response = Mock()
        response.ok = False
        response.status_code = 401
        response.json.return_value = {
            "error": "invalid_client",
            "error_description": "Bad client credentials",
            "error_code": "KOE010",
            "access_token": "must-not-leak",
        }
        post.return_value = response

        with self.assertRaises(KakaoAuthError) as raised:
            setup_kakao._exchange_code(
                "authorization-code-secret",
                "rest-api-key-secret",
                "http://127.0.0.1:8765/callback",
                "client-secret-value",
            )

        message = str(raised.exception)
        self.assertIn("HTTP 401", message)
        self.assertIn("invalid_client", message)
        self.assertIn("KOE010", message)
        self.assertNotIn("authorization-code-secret", message)
        self.assertNotIn("rest-api-key-secret", message)
        self.assertNotIn("client-secret-value", message)
        self.assertNotIn("must-not-leak", message)


if __name__ == "__main__":
    unittest.main()
