import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import notifier
from kakao_auth import KakaoAuthError, generate_encryption_key, load_refresh_token, store_refresh_token


class KakaoAuthTests(unittest.TestCase):
    def test_encrypted_store_round_trip_does_not_contain_plaintext(self):
        with tempfile.TemporaryDirectory() as directory:
            auth_file = Path(directory) / "kakao_auth.json"
            key = generate_encryption_key()
            store_refresh_token("private-refresh-token", key, auth_file)
            self.assertEqual(load_refresh_token(key, auth_file), "private-refresh-token")
            self.assertNotIn("private-refresh-token", auth_file.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(auth_file.read_text(encoding="utf-8"))["version"], 1)

    def test_wrong_key_cannot_decrypt_token(self):
        with tempfile.TemporaryDirectory() as directory:
            auth_file = Path(directory) / "kakao_auth.json"
            store_refresh_token("private-refresh-token", generate_encryption_key(), auth_file)
            with self.assertRaises(KakaoAuthError):
                load_refresh_token(generate_encryption_key(), auth_file)

    def test_refresh_includes_client_secret_and_persists_rotation(self):
        response = Mock()
        response.json.return_value = {"access_token": "access", "refresh_token": "rotated"}
        with patch.object(notifier, "KAKAO_REST_API_KEY", "rest-key"), \
             patch.object(notifier, "KAKAO_CLIENT_SECRET", "client-secret"), \
             patch.object(notifier, "KAKAO_TOKEN_ENCRYPTION_KEY", "encryption-key"), \
             patch.object(notifier, "load_refresh_token", return_value="old-token"), \
             patch.object(notifier, "store_refresh_token") as store, \
             patch.object(notifier.requests, "post", return_value=response) as post:
            self.assertEqual(notifier.refresh_kakao_access_token(), "access")
        self.assertEqual(post.call_args.kwargs["data"]["client_secret"], "client-secret")
        store.assert_called_once_with("rotated", "encryption-key")

    def test_message_requires_success_result_code(self):
        token_response = Mock()
        token_response.json.return_value = {"access_token": "access"}
        message_response = Mock()
        message_response.json.return_value = {"result_code": 0}
        with patch.object(notifier, "KAKAO_REST_API_KEY", "rest-key"), \
             patch.object(notifier, "KAKAO_TOKEN_ENCRYPTION_KEY", "encryption-key"), \
             patch.object(notifier, "PAGE_URL", "https://owner.github.io/repo/"), \
             patch.object(notifier, "KAKAO_CARD_IMAGE_URL", "https://example.com/card.png"), \
             patch.object(notifier, "load_refresh_token", return_value="refresh"), \
             patch.object(notifier.requests, "post", side_effect=[token_response, message_response]):
            from datetime import date, timedelta
            from models import Flight
            departure = date.today() + timedelta(days=30)
            deal = Flight("ICN", "TEST", "Test", "Test", departure, departure + timedelta(days=3),
                          100000, 200000, 50, "TEST", 60, 0, "https://example.com")
            self.assertTrue(notifier.send_kakao_message([deal]))


if __name__ == "__main__":
    unittest.main()
