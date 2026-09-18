import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import focus
import main
import notifier
import report_generator
from config import KST
from models import Flight


NOW = datetime(2026, 9, 18, 10, 0, tzinfo=KST)


def sample_flight(name="Tokyo", price=180000):
    return Flight(
        origin="ICN",
        destination="TEST",
        destination_name=name,
        destination_country="Japan",
        depart_date=date(2026, 10, 3),
        return_date=date(2026, 10, 7),
        price=price,
        average_price=300000,
        discount_percentage=40,
        airline="TEST",
        duration=120,
        stops=0,
        booking_link="https://example.com/flight",
        value_ratio=0.6,
        value_grade="TEST",
    )


class FocusConfigTests(unittest.TestCase):
    def test_disabled_config_returns_none(self):
        self.assertIsNone(
            focus.parse_focus_config({"focus_search": {"enabled": False}}, now=NOW)
        )

    def test_valid_config_builds_query_without_trip_length(self):
        config = focus.parse_focus_config(
            {
                "focus_search": {
                    "enabled": True,
                    "origin": "icn",
                    "region": "Japan",
                    "outbound_from": "2026-10-02",
                    "outbound_to": "2026-10-11",
                    "stay_min": 3,
                    "stay_max": 5,
                    "max_price": 250000,
                }
            },
            now=NOW,
        )
        self.assertIsNotNone(config)
        params = config.search_params()
        self.assertEqual(params["query"], "Japan, 3 to 5 day trip")
        self.assertEqual(params["outbound_date"], "2026-10-02,2026-10-11")
        self.assertEqual(params["max_price"], 250000)
        self.assertNotIn("trip_length", params)
        self.assertNotIn("return_date", params)

    def test_partly_past_window_is_clamped_to_today(self):
        config = focus.parse_focus_config(
            {
                "focus_search": {
                    "enabled": True,
                    "origin": "ICN",
                    "region": "Japan",
                    "outbound_from": "2026-09-01",
                    "outbound_to": "2026-10-01",
                }
            },
            now=NOW,
        )
        self.assertEqual(config.outbound_from, date(2026, 9, 18))

    def test_expired_config_restores_discovery_slot(self):
        self.assertIsNone(
            focus.parse_focus_config(
                {
                    "focus_search": {
                        "enabled": True,
                        "origin": "ICN",
                        "region": "Japan",
                        "outbound_from": "2026-08-01",
                        "outbound_to": "2026-09-17",
                    }
                },
                now=NOW,
            )
        )

    def test_invalid_enabled_config_is_disabled_by_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "user_config.json"
            path.write_text(
                json.dumps({"focus_search": {"enabled": True, "origin": "ICN"}}),
                encoding="utf-8",
            )
            self.assertIsNone(focus.load_focus_config(path, now=NOW))


class FocusSchedulingTests(unittest.TestCase):
    def test_focus_off_keeps_original_daily_slot(self):
        tasks = main.build_tasks(20, False, focus_active=False)
        self.assertEqual(len(tasks), 7)
        self.assertIn(("GMP", "near"), tasks)
        self.assertNotIn(main.FOCUS_TASK, tasks)

    def test_focus_on_replaces_gmp_near_one_for_one(self):
        tasks = main.build_tasks(20, False, focus_active=True)
        self.assertEqual(len(tasks), 7)
        self.assertNotIn(("GMP", "near"), tasks)
        self.assertEqual(tasks[-1], main.FOCUS_TASK)

    def test_focus_and_deep_keep_existing_eight_call_shape(self):
        tasks = main.build_tasks(20, True, focus_active=True)
        self.assertEqual(len(tasks), 8)
        self.assertEqual(tasks[-2], main.FOCUS_TASK)
        self.assertEqual(tasks[-1], ("ICN", "deep"))

    def test_budget_trimming_drops_focus_before_core_six(self):
        tasks = main.build_tasks(6, True, focus_active=True)
        self.assertEqual(len(tasks), 6)
        self.assertNotIn(main.FOCUS_TASK, tasks)
        self.assertNotIn(("ICN", "deep"), tasks)

    @patch("main.normalize_and_deduplicate", return_value=[])
    @patch("main.fetch_raw_flight_deals", return_value=[])
    def test_process_focus_uses_query_window_and_max_price(self, fetch, normalize):
        config = focus.parse_focus_config(
            {
                "focus_search": {
                    "enabled": True,
                    "origin": "ICN",
                    "region": "Japan",
                    "outbound_from": "2026-10-02",
                    "outbound_to": "2026-10-11",
                    "stay_min": 3,
                    "stay_max": 5,
                    "max_price": 250000,
                }
            },
            now=NOW,
        )
        main.process_focus(config)
        params = fetch.call_args.args[1]
        self.assertEqual(fetch.call_args.args[2], "ICN")
        self.assertEqual(params["query"], "Japan, 3 to 5 day trip")
        self.assertEqual(params["outbound_date"], "2026-10-02,2026-10-11")
        self.assertEqual(params["max_price"], 250000)
        self.assertNotIn("trip_length", params)
        normalize.assert_not_called()


class FocusOutputTests(unittest.TestCase):
    def test_pages_report_places_focus_section_before_discovery(self):
        focus_deal = sample_flight("Tokyo")
        discovery = sample_flight("Osaka", 160000)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(report_generator, "OUTPUT_DIR", tmp), \
             patch.object(report_generator, "OUTPUT_FILE", str(Path(tmp) / "index.html")):
            report_generator.generate_report_html(
                [discovery],
                "",
                focus_deals=[focus_deal],
                focus_label="Japan / 2026-10-02..2026-10-11 / 3-5d",
            )
            text = Path(tmp, "index.html").read_text(encoding="utf-8")
        self.assertIn("\U0001F3AF \uAD00\uC2EC\uAC80\uC0C9", text)
        self.assertLess(text.index("Tokyo"), text.index("Osaka"))
        self.assertIn("Japan / 2026-10-02..2026-10-11 / 3-5d", text)

    def test_kakao_focus_result_is_prioritized(self):
        focus_deal = sample_flight("Tokyo")
        discovery = sample_flight("Osaka", 160000)
        token_response = Mock()
        token_response.json.return_value = {"result_code": 0}
        token_response.raise_for_status.return_value = None

        with patch.object(notifier, "PAGE_URL", "https://owner.github.io/repo/"), \
             patch.object(notifier, "KAKAO_CARD_IMAGE_URL", "https://example.com/card.png"), \
             patch.object(notifier, "refresh_kakao_access_token", return_value="access"), \
             patch.object(notifier.requests, "post", return_value=token_response) as post:
            self.assertTrue(
                notifier.send_kakao_message([discovery], focus_deals=[focus_deal])
            )

        payload = json.loads(post.call_args.kwargs["data"]["template_object"])
        self.assertIn("\uAD00\uC2EC\uAC80\uC0C9 1\uAC74", payload["content"]["title"])
        self.assertTrue(payload["content"]["description"].startswith("\U0001F3AF"))
        self.assertLess(
            payload["content"]["description"].index("Tokyo"),
            payload["content"]["description"].index("Osaka"),
        )


if __name__ == "__main__":
    unittest.main()
