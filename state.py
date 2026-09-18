import json
import os
import logging
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
from config import KST
from models import Flight
from carryover import valid_carryover, valid_departure, destination_key

STATE_FILE = "data/state.json"


def _carryover_key(flight):
    return (flight.origin, destination_key(flight), flight.depart_date, flight.return_date)


def refresh_carryover_pool(state, fresh, now=None):
    """Prune saved candidates and replace observations only from fresh searches.

    Pool entries are complete primary deals, saved before display annotations.
    Legacy state without this key is an empty pool. Never touch route_history.
    Returns previous observations for this run's backfill selection.
    """
    now = now or datetime.now(KST)
    pool = {}
    entries = state.get("carryover_pool", [])
    invalid = 0
    expired = 0
    if not isinstance(entries, list):
        entries = []
        invalid += 1
    for entry in entries:
        try:
            data = dict(entry)
            data["depart_date"] = date.fromisoformat(data["depart_date"])
            data["return_date"] = date.fromisoformat(data["return_date"])
            data["last_confirmed_at"] = datetime.fromisoformat(data["last_confirmed_at"])
            data.update(is_carryover=True, alt_dates=[], value_grade="", value_ratio=0.0)
            f = Flight(**data)
            for field in ("origin", "destination", "destination_name", "destination_country", "airline", "booking_link"):
                if not isinstance(getattr(f, field), str):
                    raise ValueError("invalid string field")
            for field in ("price", "average_price", "discount_percentage", "duration", "stops"):
                if type(getattr(f, field)) is not int or getattr(f, field) < 0:
                    raise ValueError("invalid numeric field")
            if not f.origin or not destination_key(f) or f.price <= 0:
                raise ValueError("invalid identity or price")
            if not valid_carryover(f, now):
                expired += 1
                continue
            f = replace(f, last_confirmed_at=f.last_confirmed_at.astimezone(KST))
            key = _carryover_key(f)
            previous = pool.get(key)
            if previous is None or (f.last_confirmed_at, -f.price) > (previous.last_confirmed_at, -previous.price):
                pool[key] = f
        except (ValueError, TypeError, KeyError, OverflowError):
            invalid += 1

    observed = {}
    for f in fresh:
        if f.is_carryover or not valid_departure(f, now):
            continue
        key = _carryover_key(f)
        if key not in observed or f.price < observed[key].price:
            observed[key] = replace(f, last_confirmed_at=now.astimezone(KST),
                                    is_carryover=False, alt_dates=[], value_grade="")
    carried = [f for key, f in pool.items() if key not in observed]
    pool.update(observed)
    encoded = []
    for f in pool.values():
        data = asdict(f)
        for field in ("depart_date", "return_date", "last_confirmed_at"):
            data[field] = data[field].isoformat()
        encoded.append(data)
    state["carryover_pool"] = encoded
    logging.info("CARRYOVER pool: invalid=%d expired_or_departed=%d fresh=%d saved=%d",
                 invalid, expired, len(observed), len(encoded))
    return carried


def load_state() -> dict:
    """저장된 상태 파일을 불러온다. 없으면 빈 상태로 시작."""
    if not os.path.exists(STATE_FILE):
        return {"route_history": {}, "kakao_consecutive_failures": 0, "api_usage": {}}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"route_history": {}, "kakao_consecutive_failures": 0, "api_usage": {}}


def save_state(state: dict) -> None:
    """상태를 파일로 저장한다 (워크플로우에서 커밋되어 다음 실행에 이어짐)."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def update_route_history(state: dict, flights: list) -> set:
    """
    노선별(출발지->목적지) 최근 30일 가격 이력을 갱신하고,
    이번에 새로 '30일 최저가'를 기록한 항공권의 dedup key 집합을 반환한다.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    cutoff = datetime.now() - timedelta(days=30)
    history = state.setdefault("route_history", {})
    low_price_keys = set()

    routes_to_delete = []
    for route_key, entries in history.items():
        pruned = [
            e for e in entries
            if datetime.strptime(e["date"], "%Y-%m-%d") >= cutoff
        ]
        if pruned:
            history[route_key] = pruned
        else:
            routes_to_delete.append(route_key)
    for route_key in routes_to_delete:
        del history[route_key]

    for flight in flights:
        route_key = f"{flight.origin}->{flight.destination_name}"
        entries = history.get(route_key, [])
        previous_min = min((e["price"] for e in entries), default=None)
        if previous_min is not None and flight.price <= previous_min:
            dedup_key = (
                flight.origin, flight.destination,
                str(flight.depart_date), str(flight.return_date)
            )
            low_price_keys.add(dedup_key)
        entries.append({"date": today, "price": flight.price})
        history[route_key] = entries

    return low_price_keys


def peek_api_usage(state: dict) -> int:
    """
    호출 '전에' 이번 달 누적 사용량을 확인한다 (증가시키지 않음).
    월이 바뀌었으면 여기서 리셋한다.
    """
    month = datetime.now().strftime("%Y-%m")
    usage = state.setdefault("api_usage", {"month": month, "count": 0})
    if usage.get("month") != month:
        usage["month"] = month
        usage["count"] = 0
    return usage["count"]


def record_api_calls(state: dict, count: int) -> int:
    """이번 달 API 호출 누적 횟수를 기록하고 반환한다. 월이 바뀌면 리셋."""
    month = datetime.now().strftime("%Y-%m")
    usage = state.setdefault("api_usage", {"month": month, "count": 0})
    if usage.get("month") != month:
        usage["month"] = month
        usage["count"] = 0
    usage["count"] += count
    return usage["count"]


def record_kakao_result(state: dict, success: bool) -> bool:
    """
    카카오 발송 성공/실패를 기록한다.
    3회 연속 실패 시 True(경고 필요)를 반환.
    """
    if success:
        state["kakao_consecutive_failures"] = 0
        return False
    state["kakao_consecutive_failures"] = state.get("kakao_consecutive_failures", 0) + 1
    return state["kakao_consecutive_failures"] >= 3
