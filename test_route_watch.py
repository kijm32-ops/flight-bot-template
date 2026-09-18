import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import main
import notifier
import report_generator
import route_watch
import search
from config import KST
from focus import parse_focus_config
from models import Flight


NOW = datetime(2026, 9, 18, 10, 0, tzinfo=KST)


def route_payload(price=240000):
    return {
        "search_metadata": {
            "google_flights_url": "https://www.google.com/travel/flights/example"
        },
        "price_insights": {
            "typical_price_range": [260000, 340000]
        },
        "best_flights": [
            {
                "price": price,
                "total_duration": 145,
                "departure_token": "RETURN_SELECTION_TOKEN",
                "flights": [
                    {
                        "airline": "Test Air",
                        "departure_airport": {"id": "ICN", "name": "Incheon"},
                        "arrival_airport": {
                            "id": "NRT",
                            "name": "Narita International Airport",
                        },
                    }
                ],
            }
        ],
        "other_flights": [
            {
                "price": price + 50000,
                "total_duration": 155,
                "flights": [
                    {
                        "airline": "Other Air",
                        "departure_airport": {"id": "ICN", "name": "Incheon"},
                        "arrival_airport": {"id": "NRT", "name": "Narita"},
                    }
                ],
            }
        ],
    }


def sample_flight(name="Narita", price=240000):
    return Flight(
        origin="ICN",
        destination="NRT",
        destination_name=name,
        destination_country="",
        depart_date=date(2026, 10, 3),
        return_date=date(2026, 10, 6),
        price=price,
        average_price=300000,
        discount_percentage=20,
        airline="Test Air",
        duration=145,
        stops=0,
        booking_link="https://example.com/flight",
        value_ratio=0.8,
        value_grade="TEST",
    )


def valid_payload():
    return {
        "route_watch": {
            "enabled": True,
            "origin": "icn",
            "destination": "nrt",
            "outbound_date": "2026-10-03",
            "return_date": "2026-10-06",
            "max_price": 300000,
            "nonstop_only": True,
        }
    }


class RouteWatchConfigTests(unittest.TestCase):
    def test_disabled_route_watch_returns_none(self):
        self.assertIsNone(
            route_watch.parse_route_watch_config(
                {"route_watch": {"enabled": False}},
                now=NOW,
            )
        )

    def test_valid_route_watch_builds_exact_google_flights_params(self):
        config = route_watch.parse_route_watch_config(valid_payload(), now=NOW)
        params = config.search_params()
        self.assertEqual(params["engine"], "google_flights")
        self.assertEqual(params["type"], 1)
        self.assertEqual(params["departure_id"], "ICN")
        self.assertEqual(params["arrival_id"], "NRT")
        self.assertEqual(params["outbound_date"], "2026-10-03")
        self.assertEqual(params["return_date"], "2026-10-06")
        self.assertEqual(params["max_price"], 300000)
        self.assertEqual(params["stops"], 1)
        self.assertNotIn("departure_token", params)
        self.assertNotIn("booking_token", params)

    def test_expired_route_watch_returns_none(self):
        payload = valid_payload()
        payload["route_watch"]["outbound_date"] = "2026-09-17"
        payload["route_watch"]["return_date"] = "2026-09-20"
        self.assertIsNone(
            route_watch.parse_route_watch_config(payload, now=NOW)
        )

    def test_invalid_airport_disables_loader_only(self):
        payload = valid_payload()
        payload["route_watch"]["destination"] = "TOKYO"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "user_config.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertIsNone(
                route_watch.load_route_watch_config(path=path, now=NOW)
            )


class RouteWatchSlotTests(unittest.TestCase):
    def setUp(self):
        self.focus = parse_focus_config(
            {
                "focus_search": {
                    "enabled": True,
                    "origin": "ICN",
                    "region": "Japan",
                    "outbound_from": "2026-10-01",
                    "outbound_to": "2026-10-10",
                }
            },
            now=NOW,
        )
        self.route = route_watch.parse_route_watch_config(valid_payload(), now=NOW)

    def test_route_first_selects_route(self):
        self.assertEqual(
            route_watch.choose_user_intent(
                self.focus, self.route, "route_first", now=NOW
            ),
            "route",
        )

    def test_region_first_selects_focus(self):
        self.assertEqual(
            route_watch.choose_user_intent(
                self.focus, self.route, "region_first", now=NOW
            ),
            "focus",
        )

    def test_alternate_switches_on_adjacent_days(self):
        first = route_watch.choose_user_intent(
            self.focus, self.route, "alternate", now=NOW
        )
        second = route_watch.choose_user_intent(
            self.focus, self.route, "alternate", now=NOW + timedelta(days=1)
        )
        self.assertNotEqual(first, second)
        self.assertEqual({first, second}, {"focus", "route"})

    def test_route_only_uses_existing_single_focus_slot(self):
        tasks = main.build_tasks(20, False, focus_active=True)
        self.assertEqual(len(tasks), 7)
        self.assertEqual(tasks[-1], main.FOCUS_TASK)
        self.assertNotIn(("GMP", "near"), tasks)

    def test_deep_day_still_has_only_eight_planned_calls(self):
        tasks = main.build_tasks(20, True, focus_active=True)
        self.assertEqual(len(tasks), 8)
        self.assertEqual(tasks[-2], main.FOCUS_TASK)
        self.assertEqual(tasks[-1], ("ICN", "deep"))


class RouteWatchParserTests(unittest.TestCase):
    def test_initial_response_price_is_enough_without_return_lookup(self):
        config = route_watch.parse_route_watch_config(valid_payload(), now=NOW)
        flight = route_watch.route_watch_flight(config, route_payload())
        self.assertIsNotNone(flight)
        self.assertEqual(flight.origin, "ICN")
        self.assertEqual(flight.destination, "NRT")
        self.assertEqual(flight.price, 240000)
        self.assertEqual(flight.depart_date, date(2026, 10, 3))
        self.assertEqual(flight.return_date, date(2026, 10, 6))
        self.assertEqual(
            flight.booking_link,
            "https://www.google.com/travel/flights/example",
        )

    def test_max_price_filters_initial_options(self):
        payload = valid_payload()
        payload["route_watch"]["max_price"] = 200000
        config = route_watch.parse_route_watch_config(payload, now=NOW)
        self.assertIsNone(
            route_watch.route_watch_flight(config, route_payload(price=240000))
        )

    @patch("main.fetch_google_flights")
    def test_process_route_watch_makes_one_google_flights_fetch(self, fetch):
        fetch.return_value = route_payload()
        config = route_watch.parse_route_watch_config(valid_payload(), now=NOW)
        result = main.process_route_watch(config)
        self.assertEqual(len(result), 1)
        fetch.assert_called_once_with(main.SERPAPI_KEY, config.search_params())

    @patch("search.requests.get")
    def test_fetch_google_flights_sends_no_follow_up_token(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = route_payload()
        get.return_value = response

        params = route_watch.parse_route_watch_config(
            valid_payload(), now=NOW
        ).search_params()
        result = search.fetch_google_flights("secret-key", params)

        self.assertIn("best_flights", result)
        get.assert_called_once()
        sent = get.call_args.kwargs["params"]
        self.assertEqual(sent["api_key"], "secret-key")
        self.assertNotIn("departure_token", sent)
        self.assertNotIn("booking_token", sent)


class RouteWatchOutputTests(unittest.TestCase):
    def test_pages_places_route_before_focus_and_discovery(self):
        route_deal = sample_flight("Narita")
        focus_deal = sample_flight("Tokyo", 220000)
        discovery = sample_flight("Osaka", 180000)

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(report_generator, "OUTPUT_DIR", tmp), \
             patch.object(
                 report_generator,
                 "OUTPUT_FILE",
                 str(Path(tmp) / "index.html"),
             ):
            report_generator.generate_report_html(
                [discovery],
                "",
                focus_deals=[focus_deal],
                focus_label="Japan / 2026-10-01..2026-10-10",
                route_watch_deals=[route_deal],
                route_watch_label="ICN->NRT / 2026-10-03..2026-10-06",
            )
            text = Path(tmp, "index.html").read_text(encoding="utf-8")

        self.assertIn("\U0001F4CD \uB178\uC120\uAC10\uC2DC", text)
        self.assertLess(text.index("Narita"), text.index("Tokyo"))
        self.assertLess(text.index("Tokyo"), text.index("Osaka"))

    def test_kakao_places_route_before_focus_and_discovery(self):
        route_deal = sample_flight("Narita")
        focus_deal = sample_flight("Tokyo", 220000)
        discovery = sample_flight("Osaka", 180000)
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"result_code": 0}

        with patch.object(
            notifier,
            "PAGE_URL",
            "https://owner.github.io/repo/",
        ), patch.object(
            notifier,
            "KAKAO_CARD_IMAGE_URL",
            "https://example.com/card.png",
        ), patch.object(
            notifier,
            "refresh_kakao_access_token",
            return_value="access",
        ), patch.object(
            notifier.requests,
            "post",
            return_value=response,
        ) as post:
            self.assertTrue(
                notifier.send_kakao_message(
                    [discovery],
                    focus_deals=[focus_deal],
                    route_watch_deals=[route_deal],
                )
            )

        payload = json.loads(
            post.call_args.kwargs["data"]["template_object"]
        )
        description = payload["content"]["description"]
        self.assertIn("\uB178\uC120\uAC10\uC2DC 1\uAC74", payload["content"]["title"])
        self.assertTrue(description.startswith("\U0001F4CD"))
        self.assertLess(description.index("Narita"), description.index("Tokyo"))
        self.assertLess(description.index("Tokyo"), description.index("Osaka"))


if __name__ == "__main__":
    unittest.main()
