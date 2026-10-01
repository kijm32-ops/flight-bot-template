import tempfile
import unittest
import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch

from config import KST
import config
from manage_trip_settings import (
    SettingsError,
    resolve_guided_inputs,
    resolve_issue_event_inputs,
    save_settings,
    update_settings,
)
from models import Flight
import notifier
import report_generator


NOW = datetime(2026, 9, 22, 12, 0, tzinfo=KST)


def base():
    return {
        "focus_slot": {"mode": "alternate"},
        "focus_search": {"enabled": False},
        "route_watch": {"enabled": False},
        "route_watches": [],
    }


def issue_event(sender="owner", custom_response="_No response_"):
    body = (
        "### \uc791\uc5c5\n\n1. \uc815\ud655\ud55c \uc5ec\ud589 \uc77c\uc815 \ucd94\uac00\n\n"
        "### \ucd9c\ubc1c \uacf5\ud56d\n\nICN\n\n"
        "### \ubaa9\uc801\uc9c0/\uc9c0\uc5ed\n\n\uc624\uc0ac\uce74 (KIX)\n\n"
        "### \uc5ec\ud589 \uc2dc\uae30\n\n2\uac1c\uc6d4 \ud6c4 (next_2)\n\n"
        "### \uc219\ubc15\n\n4\ubc15 (4)\n\n"
        "### \ucd9c\ubc1c \uc8fc\ucc28\n\n\ub458\uc9f8 \uc8fc (week_2)\n\n"
        "### \uc608\uc0b0\n\n30\ub9cc\uc6d0 (300000)\n\n"
        "### \uc9c1\ud56d \uc5ec\ubd80\n\n\uc608 (true)\n\n"
        f"### \uc9c1\uc811 \ubaa9\uc801\uc9c0\n\n{custom_response}\n\n"
        "### \uc9c1\uc811 \uc2dc\uc791\uc77c\n\n_No response_\n\n"
        "### \uc9c1\uc811 \uc885\ub8cc\uc77c\n\n_No response_\n"
    )
    return {
        "repository": {"owner": {"login": "owner"}},
        "sender": {"login": sender},
        "issue": {
            "title": "[PTIS \uc124\uc815] mobile",
            "body": body,
        },
    }


class ManageTripSettingsTests(unittest.TestCase):
    def sample_flight(self):
        return Flight(
            origin="ICN", destination="KIX", destination_name="Osaka",
            destination_country="Japan", depart_date=date(2026, 11, 6),
            return_date=date(2026, 11, 8), price=200000,
            average_price=300000, discount_percentage=33, airline="XX",
            duration=120, stops=0, booking_link="https://example.test",
        )

    def test_add_exact_route_preserves_existing_settings(self):
        payload = base()
        payload["custom"] = {"keep": True}
        result = update_settings(
            payload, "exact_add", "Osaka", "icn", "kix",
            "2026-11-06", "2026-11-08", max_price="280000",
            nonstop_only=True, now=NOW,
        )
        self.assertTrue(result["custom"]["keep"])
        self.assertEqual("KIX", result["route_watches"][0]["destination"])
        self.assertTrue(result["route_watches"][0]["nonstop_only"])

    def test_guided_exact_choice_generates_dates_and_name(self):
        guided = resolve_guided_inputs(
            "exact_add", "\uc624\uc0ac\uce74 (KIX)", "2\uac1c\uc6d4 \ud6c4 (next_2)",
            "\ub458\uc9f8 \uc8fc (week_2)", "4\ubc15 (4)",
            "30\ub9cc\uc6d0 (300000)", now=NOW,
        )
        self.assertEqual("KIX", guided["destination_or_region"])
        self.assertEqual("\uc624\uc0ac\uce74", guided["name"])
        self.assertEqual("2026-11-13", guided["outbound_from"])
        self.assertEqual("2026-11-17", guided["outbound_to"])
        self.assertEqual("300000", guided["max_price"])

    def test_guided_focus_choice_uses_whole_month(self):
        guided = resolve_guided_inputs(
            "focus_set", "\uc77c\ubcf8 \uc804\uccb4 (Japan)", "next_1", "week_2", "3",
            "\uc81c\ud55c \uc5c6\uc74c (0)", now=NOW,
        )
        self.assertEqual("Japan", guided["destination_or_region"])
        self.assertEqual("2026-10-01", guided["outbound_from"])
        self.assertEqual("2026-10-31", guided["outbound_to"])
        self.assertEqual("3", guided["stay_min"])
        self.assertEqual("5", guided["stay_max"])

    def test_custom_guided_values_override_choices(self):
        guided = resolve_guided_inputs(
            "exact_add", "\uc624\uc0ac\uce74 (KIX)", "next_1", "week_2", "3", "0",
            custom_destination="CDG", custom_outbound="2026-12-20",
            custom_return="2026-12-28", now=NOW,
        )
        self.assertEqual("CDG", guided["destination_or_region"])
        self.assertEqual("2026-12-20", guided["outbound_from"])
        self.assertEqual("2026-12-28", guided["outbound_to"])

    def test_issue_form_owner_event_parses_guided_inputs(self):
        parsed = resolve_issue_event_inputs(issue_event())
        self.assertEqual("exact_add", parsed["operation"])
        self.assertEqual("ICN", parsed["origin"])
        self.assertEqual("\uc624\uc0ac\uce74 (KIX)", parsed["destination_choice"])
        self.assertEqual("next_2", parsed["travel_month"].split("(")[1].rstrip(")"))
        self.assertTrue(parsed["nonstop_only"])
        self.assertEqual("", parsed["custom_destination"])

    def test_issue_form_custom_destination_is_preserved(self):
        parsed = resolve_issue_event_inputs(issue_event(custom_response="CDG"))
        self.assertEqual("CDG", parsed["custom_destination"])

    def test_issue_form_rejects_non_owner(self):
        with self.assertRaises(SettingsError):
            resolve_issue_event_inputs(issue_event(sender="visitor"))

    def test_replace_exact_routes_only_replaces_routes(self):
        payload = base()
        payload["focus_search"] = {
            "enabled": True, "origin": "ICN", "region": "Japan",
            "outbound_from": "2026-10-01", "outbound_to": "2026-12-01",
            "stay_min": 3, "stay_max": 7,
        }
        payload["route_watches"] = [{"enabled": False, "name": "old"}]
        result = update_settings(
            payload, "exact_replace", "Tokyo", "ICN", "NRT",
            "2026-12-02", "2026-12-06", now=NOW,
        )
        self.assertTrue(result["focus_search"]["enabled"])
        self.assertEqual(["Tokyo"], [item["name"] for item in result["route_watches"]])

    def test_set_focus_uses_range_stay_and_budget(self):
        result = update_settings(
            base(), "focus_set", origin="CJJ",
            destination_or_region="Japan", outbound_from="2026-10-01",
            outbound_to="2026-11-30", stay_min="3", stay_max="6",
            max_price="250000", now=NOW,
        )
        self.assertEqual("Japan", result["focus_search"]["region"])
        self.assertEqual(250000, result["focus_search"]["max_price"])

    def test_pause_all_preserves_entries_but_disables_them(self):
        payload = base()
        payload["focus_search"] = {"enabled": True}
        payload["route_watch"] = {"enabled": True}
        payload["route_watches"] = [{"enabled": True, "name": "keep"}]
        result = update_settings(payload, "pause_all", now=NOW)
        self.assertFalse(result["focus_search"]["enabled"])
        self.assertFalse(result["route_watch"]["enabled"])
        self.assertEqual("keep", result["route_watches"][0]["name"])
        self.assertFalse(result["route_watches"][0]["enabled"])

    def test_invalid_input_does_not_write_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "user_config.json"
            save_settings(path, base())
            before = path.read_bytes()
            with self.assertRaises(SettingsError):
                update_settings(
                    base(), "exact_add", origin="ICN",
                    destination_or_region="NOT-AIRPORT",
                    outbound_from="2026-11-06", outbound_to="2026-11-08",
                    now=NOW,
                )
            self.assertEqual(before, path.read_bytes())

    def test_repository_settings_url_is_automatic(self):
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "owner/repo"}):
            self.assertEqual(
                "https://github.com/owner/repo/issues/new?template=trip-settings.yml",
                config._trip_settings_url(),
            )

    def test_pages_and_kakao_include_settings_button(self):
        settings_url = "https://github.com/owner/repo/issues/new?template=trip-settings.yml"
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(report_generator, "OUTPUT_DIR", directory), \
             patch.object(report_generator, "OUTPUT_FILE", str(Path(directory) / "index.html")), \
             patch.object(report_generator, "TRIP_SETTINGS_URL", settings_url):
            report_generator.generate_report_html([], "")
            html = Path(directory, "index.html").read_text(encoding="utf-8")
            self.assertIn(settings_url, html)
            self.assertIn("\uc5ec\ud589 \uc870\uac74 \uc124\uc815", html)

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"result_code": 0}
        with patch.object(notifier, "PAGE_URL", "https://owner.github.io/repo/"), \
             patch.object(notifier, "KAKAO_CARD_IMAGE_URL", "https://example.test/card.png"), \
             patch.object(notifier, "TRIP_SETTINGS_URL", settings_url), \
             patch.object(notifier, "refresh_kakao_access_token", return_value="token"), \
             patch.object(notifier.requests, "post", return_value=response) as post:
            self.assertTrue(notifier.send_kakao_message([self.sample_flight()]))
        payload = json.loads(post.call_args.kwargs["data"]["template_object"])
        self.assertEqual(settings_url, payload["buttons"][1]["link"]["mobile_web_url"])


if __name__ == "__main__":
    unittest.main()
