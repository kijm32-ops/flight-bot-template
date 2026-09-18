import logging
import sys
import concurrent.futures
from collections import Counter
from typing import List, Tuple, Dict
from config import (
    SERPAPI_KEY, BASE_SEARCH_PARAMS, KAKAO_JS_KEY,
    PROFILES, ORIGIN_PROFILES,
    DAILY_TASK_PRIORITY, DEEP_TASK_PRIORITY, is_deep_scan_day,
    SERPAPI_SAFE_BUDGET, SERPAPI_MONTHLY_LIMIT, API_QUOTA_WARNING_THRESHOLD,
)
from search import fetch_google_flights, fetch_raw_flight_deals
from normalizer import normalize_and_deduplicate, collapse_by_destination, format_funnel
from notifier import send_email, send_kakao_message, send_warning_email
from report_generator import generate_report_html
from state import (
    load_state, save_state, update_route_history, refresh_carryover_pool,
    peek_api_usage, record_api_calls, record_kakao_result,
)
from models import Flight
from carryover import select_with_carryover
from origin_compare import annotate_origin_alternatives
from exposure import record_exposure
from focus import FocusConfig, load_focus_config
from route_watch import (
    RouteWatchConfig,
    choose_user_intent,
    load_focus_slot_mode,
    load_route_watch_config,
    route_watch_flight,
)
from selection import (
    TOTAL_SLOTS,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

FOCUS_TASK = ("__FOCUS__", "focus")
FOCUS_REPLACED_TASK = ("GMP", "near")


def _task_label(task: Tuple[str, str]) -> str:
    return "FOCUS" if task == FOCUS_TASK else f"{task[0]}/{task[1]}"


def build_tasks(
    remaining_budget: int,
    deep_scan: bool,
    focus_active: bool = False,
) -> List[Tuple[str, str]]:
    candidates = list(DAILY_TASK_PRIORITY)
    if focus_active:
        try:
            index = candidates.index(FOCUS_REPLACED_TASK)
        except ValueError:
            logging.error("Focus Search replacement slot is missing; Focus disabled for this run.")
        else:
            candidates[index] = FOCUS_TASK

    if deep_scan:
        candidates += DEEP_TASK_PRIORITY

    valid = [
        (origin, profile)
        for origin, profile in candidates
        if (origin, profile) == FOCUS_TASK
        or profile in ORIGIN_PROFILES.get(origin, [])
    ]

    if remaining_budget >= len(valid):
        return valid

    trimmed = valid[:max(0, remaining_budget)]
    dropped = valid[len(trimmed):]
    if dropped:
        logging.warning(
            f"\u26A0\uFE0F \uC608\uC0B0 \uBD80\uC871\uC73C\uB85C {len(dropped)}\uAC1C \uC791\uC5C5 \uC0DD\uB7B5: "
            + ", ".join(_task_label(task) for task in dropped)
        )
    return trimmed


def process_profile(origin: str, profile_name: str) -> Tuple[List[Flight], Counter]:
    stats: Counter = Counter()
    try:
        date_range, trip_length, max_price = PROFILES[profile_name]
        search_params = {
            **BASE_SEARCH_PARAMS,
            "outbound_date": date_range,
            "trip_length": trip_length,
        }
        # 응답 건수에 상한이 있는 것으로 보여, 어차피 TIER_HARD_CAP 에 걸릴
        # 고가 노선이 슬롯을 차지하지 않도록 서버 쪽에서 미리 잘라낸다.
        if max_price:
            search_params["max_price"] = max_price
        raw_deals = fetch_raw_flight_deals(SERPAPI_KEY, search_params, origin)
        if not raw_deals:
            logging.info(f"[{origin} / {profile_name}] no raw deals returned.")
            return [], stats

        flights = normalize_and_deduplicate(origin, raw_deals, stats)
        logging.info(
            f"[{origin} / {profile_name}] {len(flights)} normalized. "
            f"funnel: {format_funnel(stats)}"
        )
        return flights, stats
    except Exception as e:
        logging.error(f"[{origin} / {profile_name}] FAILED: {e}")
        return [], stats


def process_focus(config: FocusConfig) -> Tuple[List[Flight], Counter]:
    stats: Counter = Counter()
    try:
        raw_deals = fetch_raw_flight_deals(
            SERPAPI_KEY,
            config.search_params(),
            config.origin,
        )
        if not raw_deals:
            logging.info("[FOCUS] no raw deals returned.")
            return [], stats

        flights = normalize_and_deduplicate(config.origin, raw_deals, stats)
        flights = [flight for flight in flights if config.matches(flight)]
        flights.sort(key=lambda flight: (flight.price, flight.value_ratio))
        logging.info(
            "[FOCUS] %d normalized matches. funnel: %s",
            len(flights),
            format_funnel(stats),
        )
        return flights, stats
    except Exception as exc:
        logging.error("[FOCUS] FAILED: %s", exc)
        return [], stats


def process_route_watch(config: RouteWatchConfig) -> List[Flight]:
    try:
        payload = fetch_google_flights(SERPAPI_KEY, config.search_params())
        flight = route_watch_flight(config, payload)
        if flight is None:
            logging.info("[ROUTE] no matching fare returned.")
            return []
        logging.info(
            "[ROUTE] %s %s->%s %s KRW",
            config.outbound_date,
            config.origin,
            config.destination,
            flight.price,
        )
        return [flight]
    except Exception as exc:
        logging.error("[ROUTE] FAILED: %s", exc)
        return []


def merge_and_collapse(flights: List[Flight]) -> List[Flight]:
    """
    Merge results from all profiles:
    1) drop exact duplicates (same origin/dest/dates), keeping cheapest
    2) re-collapse per destination so MAX_PER_DESTINATION is enforced globally

    NOTE: this stage is still origin-aware. Cross-origin duplicates
    (GMP/CJJ -> same city) are resolved later in selection.strict_collapse().
    """
    seen: Dict[Tuple[str, str, str, str], Flight] = {}
    for f in flights:
        key = (f.origin, f.destination_name, str(f.depart_date), str(f.return_date))
        if key not in seen or f.price < seen[key].price:
            seen[key] = f

    deduped = list(seen.values())
    before = len(deduped)
    result = collapse_by_destination(deduped)
    logging.info(f"merge: {len(flights)} -> dedup {before} -> collapse {len(result)}")
    return result


def run_system():
    if not SERPAPI_KEY:
        logging.error("SERPAPI_KEY missing.")
        sys.exit(1)

    state = load_state()
    focus_config = load_focus_config()
    route_config = load_route_watch_config()
    focus_slot_mode = load_focus_slot_mode()
    user_intent = choose_user_intent(
        focus_config,
        route_config,
        focus_slot_mode,
    )
    if user_intent:
        logging.info("User-intent slot: %s (%s)", user_intent, focus_slot_mode)

    deep_scan = is_deep_scan_day()
    if deep_scan:
        logging.info("Deep scan day (8-11 months ahead included).")

    used = peek_api_usage(state)
    remaining = SERPAPI_SAFE_BUDGET - used
    logging.info(
        f"Budget: {used}/{SERPAPI_MONTHLY_LIMIT} used, "
        f"{remaining} left (safe cap {SERPAPI_SAFE_BUDGET})"
    )

    tasks = build_tasks(remaining, deep_scan, focus_active=user_intent is not None)

    if not tasks:
        logging.error("Budget exhausted; skipping API calls.")
        send_warning_email(
            "\U0001F6D1 [PTIS] SerpApi \uC608\uC0B0 \uC18C\uC9C4 \u2014 \uAC80\uC0C9 \uC911\uB2E8",
            f"\uC774\uBC88 \uB2EC SerpApi \uD638\uCD9C\uC774 {used}\uD68C\uC5D0 \uB3C4\uB2EC\uD558\uC5EC "
            f"\uAC80\uC0C9\uC744 \uC911\uB2E8\uD588\uC2B5\uB2C8\uB2E4. "
            f"(\uBB34\uB8CC \uD55C\uB3C4 {SERPAPI_MONTHLY_LIMIT}\uD68C) "
            f"\uB2E4\uC74C \uB2EC 1\uC77C\uC5D0 \uC790\uB3D9\uC73C\uB85C \uC7AC\uAC1C\uB429\uB2C8\uB2E4."
        )
        refresh_carryover_pool(state, [])
        generate_report_html([], KAKAO_JS_KEY, set())
        save_state(state)
        return

    logging.info(
        f"Start {len(tasks)} tasks: " + ", ".join(_task_label(task) for task in tasks)
    )
    all_final_flights: List[Flight] = []
    focus_flights: List[Flight] = []
    route_watch_flights: List[Flight] = []
    funnel: Counter = Counter()

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as executor:
        future_to_task = {}
        for origin, profile in tasks:
            task = (origin, profile)
            if task == FOCUS_TASK:
                if user_intent == "route" and route_config is not None:
                    future = executor.submit(process_route_watch, route_config)
                elif user_intent == "focus" and focus_config is not None:
                    future = executor.submit(process_focus, focus_config)
                else:
                    continue
            else:
                future = executor.submit(process_profile, origin, profile)
            future_to_task[future] = task

        for future in concurrent.futures.as_completed(future_to_task):
            task = future_to_task[future]
            try:
                result = future.result()
                if task == FOCUS_TASK and user_intent == "route":
                    route_watch_flights.extend(result)
                elif task == FOCUS_TASK:
                    flights, stats = result
                    focus_flights.extend(flights)
                    funnel.update(stats)
                else:
                    flights, stats = result
                    all_final_flights.extend(flights)
                    funnel.update(stats)
            except Exception as exc:
                logging.error("[%s] thread error: %s", _task_label(task), exc)

    logging.info("FUNNEL (all tasks): " + format_funnel(funnel))

    carried = refresh_carryover_pool(state, all_final_flights)
    all_final_flights = merge_and_collapse(all_final_flights)
    all_final_flights = annotate_origin_alternatives(all_final_flights)

    all_final_flights = select_with_carryover(state, all_final_flights, carried)

    logging.info(
        "SLOTS: %d/%d filled. If this is well under 20, the bottleneck is "
        "upstream (raw yield or gates), not the quota.",
        len(all_final_flights), TOTAL_SLOTS,
    )

    record_exposure(state, all_final_flights)

    logging.info(
        "Done. %d discovery, %d focus, %d route-watch deals collected.",
        len(all_final_flights),
        len(focus_flights),
        len(route_watch_flights),
    )

    low_price_keys = update_route_history(state, [f for f in all_final_flights if not f.is_carryover])
    if low_price_keys:
        logging.info(f"30-day lows: {len(low_price_keys)}")

    total_calls = record_api_calls(state, len(tasks))
    logging.info(f"Monthly SerpApi calls: {total_calls}")
    if total_calls >= API_QUOTA_WARNING_THRESHOLD:
        send_warning_email(
            "\u26A0\uFE0F [PTIS] SerpApi \uD55C\uB3C4 \uC784\uBC15",
            f"\uC774\uBC88 \uB2EC SerpApi \uD638\uCD9C\uC774 {total_calls}\uD68C\uB97C "
            f"\uAE30\uB85D\uD588\uC2B5\uB2C8\uB2E4 (\uBB34\uB8CC \uD55C\uB3C4 {SERPAPI_MONTHLY_LIMIT}\uD68C / "
            f"\uC548\uC804 \uC608\uC0B0 {SERPAPI_SAFE_BUDGET}\uD68C)."
        )

    generate_report_html(
        all_final_flights,
        KAKAO_JS_KEY,
        low_price_keys,
        focus_deals=focus_flights,
        focus_label=focus_config.label if focus_config else "",
        route_watch_deals=route_watch_flights,
        route_watch_label=route_config.label if route_config else "",
    )

    if all_final_flights or focus_flights or route_watch_flights:
        send_email(
            route_watch_flights + focus_flights + all_final_flights,
            low_price_keys,
        )
        kakao_success = send_kakao_message(
            all_final_flights,
            focus_deals=focus_flights,
            route_watch_deals=route_watch_flights,
        )
        need_warning = record_kakao_result(state, kakao_success)
        if need_warning:
            send_warning_email(
                "\u26A0\uFE0F [PTIS] \uCE74\uCE74\uC624\uD1A1 \uBC1C\uC1A1 3\uD68C \uC5F0\uC18D \uC2E4\uD328",
                "\uCE74\uCE74\uC624\uD1A1 \uC54C\uB9BC\uC774 3\uD68C \uC5F0\uC18D \uBC1C\uC1A1\uC5D0 "
                "\uC2E4\uD328\uD588\uC2B5\uB2C8\uB2E4. Kakao OAuth \uAD8C\uD55C\uACFC \uC554\uD638\uD654\uB41C "
                "\uD1A0\uD070 \uC124\uC815\uC744 \uD655\uC778\uD574\uC8FC\uC138\uC694."
            )
    else:
        logging.warning("No deals to send.")

    save_state(state)


if __name__ == "__main__":
    run_system()
