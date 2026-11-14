import unittest
from unittest.mock import patch

import requests

import search

KEY = "secret+key/123"


def _failing_get(url, params=None, timeout=None):
    prepared = requests.Request("GET", url, params=params).prepare()
    raise requests.exceptions.HTTPError(
        f"401 Client Error: Unauthorized for url: {prepared.url}"
    )


class ApiKeyRedactionTests(unittest.TestCase):
    def _assert_no_key(self, call):
        with patch.object(search.requests, "get", side_effect=_failing_get), \
                self.assertLogs(level="ERROR") as logs, \
                self.assertRaises(search.APIFetchError) as raised:
            call()
        text = " ".join(logs.output) + str(raised.exception)
        self.assertNotIn(KEY, text)
        self.assertNotIn("secret%2Bkey%2F123", text)
        self.assertIn("api_key=***", text)
        self.assertIsNone(raised.exception.__cause__)
        self.assertTrue(raised.exception.__suppress_context__)

    def test_deals_error_hides_key(self):
        self._assert_no_key(
            lambda: search.fetch_raw_flight_deals.__wrapped__(KEY, {"engine": "x"}, "ICN")
        )

    def test_route_error_hides_key(self):
        self._assert_no_key(
            lambda: search.fetch_google_flights.__wrapped__(
                KEY, {"departure_id": "ICN", "arrival_id": "KIX"}
            )
        )

    def test_success_returns_deals(self):
        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"deals": [{"id": 1}]}

        with patch.object(search.requests, "get", return_value=Response()):
            self.assertEqual(
                search.fetch_raw_flight_deals.__wrapped__(KEY, {}, "ICN"), [{"id": 1}]
            )


if __name__ == "__main__":
    unittest.main()
