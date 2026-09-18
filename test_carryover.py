import copy
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, Mock

from config import KST
from models import Flight
from carryover import select_with_carryover
from state import refresh_carryover_pool
from selection import apply_quota, apply_caps, sort_by_score, strict_collapse, assign_grades
from exposure import apply_exposure_penalty

NOW = datetime(2026, 9, 13, 7, tzinfo=KST)


def flight(name="A", destination="FUK", price=100000, **kwargs):
    f = Flight("ICN", destination, name, "Japan", NOW.date() + timedelta(days=30),
               NOW.date() + timedelta(days=34), price, 200000, 50, "XX", 120, 0,
               "https://example.com/flight")
    return replace(f, **kwargs)


def carried(name="Old", **kwargs):
    return flight(name, is_carryover=True, last_confirmed_at=NOW - timedelta(days=1), **kwargs)


class CarryoverTests(unittest.TestCase):
    def test_legacy_state_and_no_history_mutation(self):
        state = {"route_history": {"route": [{"date": "2026-09-12", "price": 99}]}}
        before = copy.deepcopy(state["route_history"])
        self.assertEqual(refresh_carryover_pool(state, [flight()], NOW), [])
        self.assertEqual(state["route_history"], before)
        json.dumps(state)

    def test_ttl_boundary_and_no_extension_across_runs(self):
        state = {}
        refresh_carryover_pool(state, [flight()], NOW)
        stamp = state["carryover_pool"][0]["last_confirmed_at"]
        for hours in (24, 48):
            old = refresh_carryover_pool(state, [], NOW + timedelta(hours=hours))
            self.assertEqual(len(old), 1)
            self.assertEqual(state["carryover_pool"][0]["last_confirmed_at"], stamp)
        self.assertEqual(refresh_carryover_pool(state, [], NOW + timedelta(hours=48, seconds=1)), [])
        self.assertEqual(state["carryover_pool"], [])

    def test_rediscovery_replaces_price_and_timestamp(self):
        state = {}
        refresh_carryover_pool(state, [flight(price=80000)], NOW)
        self.assertEqual(refresh_carryover_pool(state, [flight(price=150000)], NOW + timedelta(days=1)), [])
        item = state["carryover_pool"][0]
        self.assertEqual(item["price"], 150000)
        self.assertEqual(item["last_confirmed_at"], (NOW + timedelta(days=1)).isoformat())

    def test_reusing_carryover_cannot_refresh(self):
        state = {}
        refresh_carryover_pool(state, [flight()], NOW)
        before = copy.deepcopy(state)
        refresh_carryover_pool(state, [carried("A")], NOW + timedelta(days=1))
        self.assertEqual(state["carryover_pool"][0]["last_confirmed_at"], before["carryover_pool"][0]["last_confirmed_at"])

    def test_kst_departure_and_bad_return(self):
        utc = NOW.astimezone(timezone.utc)
        invalid = [carried(depart_date=NOW.date()), carried(return_date=NOW.date())]
        self.assertEqual(select_with_carryover({}, [], invalid, utc), [])

    def test_future_and_naive_confirmation_rejected(self):
        for stamp in (NOW + timedelta(seconds=1), NOW.replace(tzinfo=None)):
            self.assertEqual(select_with_carryover({}, [], [replace(carried(), last_confirmed_at=stamp)], NOW), [])

    def test_corrupt_entries_isolated(self):
        state = {}
        refresh_carryover_pool(state, [flight()], NOW)
        valid = copy.deepcopy(state["carryover_pool"][0])
        for bad in (None, {}, {**valid, "price": "cheap"}, {**valid, "depart_date": "bad"}, {**valid, "price": -1}):
            state["carryover_pool"] = [bad, valid]
            self.assertEqual(len(refresh_carryover_pool(state, [], NOW)), 1)
        state["carryover_pool"] = {"bad": "shape"}
        self.assertEqual(refresh_carryover_pool(state, [], NOW), [])

    def test_fresh_always_wins_cross_origin_and_date(self):
        fresh = [flight("A B", price=180000)]
        old = [carried("AB", price=10000, origin="CJJ"), carried("Other", price=20000)]
        out = select_with_carryover({}, fresh, old, NOW)
        self.assertEqual([f.destination_name for f in out], ["A B", "Other"])
        self.assertEqual(out[0].price, 180000)

    def test_caps_include_access_cost(self):
        out = select_with_carryover({}, [], [carried(price=180000, origin="CJJ")], NOW)
        self.assertEqual(out, [])

    def test_fresh_only_pipeline_unchanged(self):
        fresh = [flight(str(i), price=50000 + i * 1000) for i in range(30)]
        expected = assign_grades(apply_quota(apply_exposure_penalty({}, sort_by_score(apply_caps(strict_collapse(fresh))))))
        self.assertEqual(select_with_carryover({}, fresh, [], NOW), expected)

    def test_full_report_cannot_be_displaced(self):
        fresh = [flight(str(i), price=150000) for i in range(25)]
        old = [carried("Far", destination="LAX", price=1000)]
        out = select_with_carryover({}, fresh, old, NOW)
        self.assertEqual(len(out), 20)
        self.assertTrue(all(not f.is_carryover for f in out))

    def test_reserved_wildcards_do_not_displace_fresh(self):
        fresh = [flight(str(i)) for i in range(19)]
        old = [carried("Far" + str(i), destination="LAX", price=1000) for i in range(3)]
        out = select_with_carryover({}, fresh, old, NOW)
        self.assertEqual(len(out), 20)
        self.assertEqual(sum(not f.is_carryover for f in out), 19)

    def test_residual_quota_prefers_unfilled_group(self):
        fresh = [flight(str(i)) for i in range(10)]
        old = [carried("Near" + str(i), price=10000) for i in range(15)]
        old += [carried("Far" + str(i), destination="LAX", price=300000) for i in range(2)]
        out = select_with_carryover({}, fresh, old, NOW)
        self.assertEqual(sum(f.destination == "LAX" for f in out), 2)
        self.assertEqual(len(out), 20)

    def test_alternate_dates_removed_and_exposure_applied(self):
        old = [carried("A", alt_dates=[("bad", "bad", 1)]), carried("B", price=110000)]
        state = {"exposure_log": {"ICN->A": [{"date": str(i), "price": 100000} for i in range(7)]}}
        out = select_with_carryover(state, [], old, NOW)
        self.assertEqual(out[0].destination_name, "B")
        self.assertTrue(all(not f.alt_dates for f in out))

    def test_end_to_end_offline_no_extra_calls_or_stale_history(self):
        import main
        import state as storage
        now = datetime.now(KST)
        f = flight(depart_date=now.date() + timedelta(days=30), return_date=now.date() + timedelta(days=34))
        state = {}
        refresh_carryover_pool(state, [replace(f, destination_name="Old")], now - timedelta(days=1))
        with tempfile.TemporaryDirectory() as tmp, patch.object(storage, "STATE_FILE", str(Path(tmp)/"state.json")), \
             patch.object(main, "SERPAPI_KEY", "test"), patch.object(main, "load_state", return_value=state), \
             patch.object(main, "fetch_raw_flight_deals", return_value=[{
                 "outbound_date": str(f.depart_date), "return_date": str(f.return_date),
                 "destination_id": f.destination, "name": f.destination_name,
                 "country": f.destination_country, "price": f.price,
                 "discount_percentage": 50, "flight_link": f.booking_link,
             }]) as search, \
             patch.object(main, "is_deep_scan_day", return_value=False), \
             patch.object(main, "send_email"), patch.object(main, "send_kakao_message", return_value=True), \
             patch.object(main, "send_warning_email"), patch.object(main, "generate_report_html") as report, \
             patch("socket.socket", side_effect=AssertionError("Network forbidden")):
            main.run_system()
            self.assertEqual(search.call_count, 7)
            self.assertEqual(state["api_usage"]["count"], 7)
            self.assertEqual(len(report.call_args.args[0]), 2)
            self.assertNotIn("ICN->Old", state["route_history"])
            self.assertTrue(Path(tmp, "state.json").exists())

    def test_report_email_and_kakao_labels(self):
        import notifier
        import report_generator as report
        old = carried()
        with tempfile.TemporaryDirectory() as tmp, patch.object(report, "OUTPUT_DIR", tmp), \
             patch.object(report, "OUTPUT_FILE", str(Path(tmp)/"index.html")):
            report.generate_report_html([old], "")
            self.assertIn(old.carryover_label, Path(tmp, "index.html").read_text(encoding="utf-8"))
        with patch.object(notifier, "_send_raw_email") as email:
            notifier.send_email([old])
            self.assertIn(old.carryover_label, email.call_args.args[1])
        token_response = Mock()
        token_response.json.return_value = {"access_token": "test"}
        message_response = Mock()
        message_response.json.return_value = {"result_code": 0}
        with patch.object(notifier, "KAKAO_REST_API_KEY", "test"), \
             patch.object(notifier, "KAKAO_TOKEN_ENCRYPTION_KEY", "test-key"), \
             patch.object(notifier, "PAGE_URL", "https://owner.github.io/repo/"), \
             patch.object(notifier, "KAKAO_CARD_IMAGE_URL", "https://example.com/card.png"), \
             patch.object(notifier, "load_refresh_token", return_value="test"), \
             patch.object(notifier.requests, "post", side_effect=[token_response, message_response]) as post:
            self.assertTrue(notifier.send_kakao_message([old]))
            payload = json.loads(post.call_args.kwargs["data"]["template_object"])
            self.assertIn(old.carryover_label, payload["content"]["description"])

    def test_empty_search_backfills_without_new_confirmation(self):
        import main
        now = datetime.now(KST)
        f = flight(depart_date=now.date() + timedelta(days=30), return_date=now.date() + timedelta(days=34))
        state = {}
        refresh_carryover_pool(state, [f], now - timedelta(days=1))
        stamp = state["carryover_pool"][0]["last_confirmed_at"]
        with patch.object(main, "SERPAPI_KEY", "test"), patch.object(main, "load_state", return_value=state), \
             patch.object(main, "fetch_raw_flight_deals", return_value=[]) as fetch, \
             patch.object(main, "is_deep_scan_day", return_value=False), patch.object(main, "save_state"), \
             patch.object(main, "send_email"), patch.object(main, "send_kakao_message", return_value=True), \
             patch.object(main, "send_warning_email"), patch.object(main, "generate_report_html") as report, \
             patch("socket.socket", side_effect=AssertionError("Network forbidden")):
            main.run_system()
            self.assertEqual(fetch.call_count, 7)
            self.assertTrue(report.call_args.args[0][0].is_carryover)
            self.assertEqual(state["route_history"], {})
            self.assertEqual(state["carryover_pool"][0]["last_confirmed_at"], stamp)

    def test_exhausted_budget_keeps_existing_skip_behavior(self):
        import main
        state = {"api_usage": {"month": datetime.now().strftime("%Y-%m"), "count": 235}}
        with patch.object(main, "SERPAPI_KEY", "test"), patch.object(main, "load_state", return_value=state), \
             patch.object(main, "fetch_raw_flight_deals") as fetch, patch.object(main, "save_state"), \
             patch.object(main, "send_warning_email"), patch.object(main, "generate_report_html") as report:
            main.run_system()
            fetch.assert_not_called()
            self.assertEqual(report.call_args.args[0], [])
            self.assertEqual(state["api_usage"]["count"], 235)


if __name__ == "__main__":
    unittest.main()
