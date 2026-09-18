# normalizer.py
# NOTE: All Korean text uses unicode escapes (\uXXXX) to survive copy-paste.

from collections import Counter
from typing import List, Dict, Tuple, Optional
from datetime import datetime
from dataclasses import replace
from models import Flight
from config import (
    MIN_DISCOUNT_PERCENTAGE,
    DOMESTIC_ALLOWED_ORIGINS,
    DISCOUNT_BYPASS_RATIO,
    MAX_PER_DESTINATION,
    KEEP_ALT_DATES,
    TRIP_DAYS_MAX_SLACK,
    ACCESS_COST,
    ACCESS_COST_DEFAULT,
    TIER_HARD_CAP,
    HARD_CAP_DEFAULT,
)
from valuation import value_ratio, grade, trip_days_range, resolve_tier

UNKNOWN_NAME = "\uc54c \uc218 \uc5c6\uc74c"          # "알 수 없음"
KOREA = "\ub300\ud55c\ubbfc\uad6d"                    # "대한민국"

# 깔때기 계측 단계 이름
STAGE_RAW = "raw"
STAGE_BAD_DATE = "drop_bad_date"
STAGE_TRIP_MIN = "drop_trip_too_short"
STAGE_TRIP_MAX = "drop_trip_too_long"
STAGE_CAP = "drop_over_cap"
STAGE_DISCOUNT = "drop_low_discount"
STAGE_DOMESTIC = "drop_domestic_origin"
STAGE_ERROR = "drop_exception"
STAGE_QUALIFIED = "qualified"


def _parse_date(date_str: str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def normalize_and_deduplicate(
    origin: str,
    raw_deals: list,
    stats: Optional[Counter] = None,
) -> List[Flight]:
    """
    stats 를 넘기면 각 게이트에서 몇 건이 떨어졌는지 기록한다.
    어느 단계가 병목인지 로그로 확인할 수 있어야 튜닝이 추측이 아니게 된다.
    """
    if stats is None:
        stats = Counter()

    access = ACCESS_COST.get(origin, ACCESS_COST_DEFAULT)
    best_flights: Dict[Tuple[str, str, str, str], Flight] = {}
    stats[STAGE_RAW] += len(raw_deals)

    for deal in raw_deals:
        try:
            depart_date = _parse_date(deal.get("outbound_date", ""))
            return_date = _parse_date(deal.get("return_date", ""))
            if not depart_date or not return_date:
                stats[STAGE_BAD_DATE] += 1
                continue

            price = deal.get("price", 0)
            destination_id = deal.get("destination_id", "UNKNOWN")
            destination_name = deal.get("name", UNKNOWN_NAME)
            destination_country = deal.get("country", "")

            # -- gate 1: trip length ------------------------------------------
            # 하한은 그대로 지킨다. 유럽 3박은 실제로 말이 안 되니까.
            # 상한은 SLACK 만큼 풀어준다. far/deep 프로필이 trip_length 7~16 으로
            # 검색하기 때문에, 상한을 엄격히 걸면 근거리 결과가 거의 전멸한다.
            trip_days = (return_date - depart_date).days
            min_days, max_days = trip_days_range(
                destination_id, destination_country, destination_name
            )
            if trip_days < min_days:
                stats[STAGE_TRIP_MIN] += 1
                continue
            if trip_days > max_days + TRIP_DAYS_MAX_SLACK:
                stats[STAGE_TRIP_MAX] += 1
                continue

            # -- gate 2: absolute price ceiling -------------------------------
            # 접근비용을 더한 실질 지불액으로 판정한다.
            # 이전의 MAX_VALUE_RATIO 게이트를 대체한다. ratio 는 tier 마다
            # 상한 대비 배율이 제각각(0.65~1.33)이라 일관된 컷이 되지 못했다.
            tier = resolve_tier(destination_id, destination_country, destination_name)
            if (price + access) > TIER_HARD_CAP.get(tier, HARD_CAP_DEFAULT):
                stats[STAGE_CAP] += 1
                continue

            ratio = value_ratio(price, destination_id, destination_country, destination_name)
            if ratio is None:
                stats[STAGE_CAP] += 1
                continue

            # -- gate 3: discount, waived when already cheap ------------------
            discount_percentage = deal.get("discount_percentage", 0)
            if ratio > DISCOUNT_BYPASS_RATIO and discount_percentage < MIN_DISCOUNT_PERCENTAGE:
                stats[STAGE_DISCOUNT] += 1
                continue

            if destination_country == KOREA and origin not in DOMESTIC_ALLOWED_ORIGINS:
                stats[STAGE_DOMESTIC] += 1
                continue

            flight = Flight(
                origin=origin,
                destination=destination_id,
                destination_name=destination_name,
                destination_country=destination_country,
                depart_date=depart_date,
                return_date=return_date,
                price=price,
                average_price=deal.get("average_price", 0),
                discount_percentage=discount_percentage,
                airline=deal.get("airline", "Unknown"),
                duration=deal.get("duration", 0),
                stops=deal.get("stops", 0),
                booking_link=deal.get("flight_link", ""),
                value_ratio=ratio,
                value_grade=grade(ratio),
            )

            dedup_key = (
                flight.origin, flight.destination,
                str(flight.depart_date), str(flight.return_date),
            )
            if dedup_key not in best_flights or price < best_flights[dedup_key].price:
                best_flights[dedup_key] = flight

        except Exception:
            stats[STAGE_ERROR] += 1
            continue

    qualified = list(best_flights.values())
    stats[STAGE_QUALIFIED] += len(qualified)
    return collapse_by_destination(qualified)


def collapse_by_destination(
    flights: List[Flight],
    max_per_dest: int = MAX_PER_DESTINATION,
    keep_alts: int = KEEP_ALT_DATES,
) -> List[Flight]:
    """
    목적지별 저렴한 순 max_per_dest 건만 노출하고 나머지는 alt_dates 로 접는다.
    destination_id 는 신뢰할 수 없어 (origin, destination_name) 으로 묶는다.
    출발지를 가로지르는 중복은 selection.strict_collapse() 가 처리한다.
    """
    buckets: Dict[Tuple[str, str], List[Flight]] = {}
    for f in flights:
        buckets.setdefault((f.origin, f.destination_name), []).append(f)

    result = []
    for group in buckets.values():
        group.sort(key=lambda f: f.price)
        shown = group[:max_per_dest]
        rest = group[max_per_dest:max_per_dest + keep_alts]

        alt_dates = [(str(f.depart_date), str(f.return_date), f.price) for f in rest]
        result.append(replace(shown[0], alt_dates=alt_dates))
        result.extend(shown[1:])

    return result


def format_funnel(stats: Counter) -> str:
    """로그 한 줄로 깔때기 요약."""
    order = [
        STAGE_RAW, STAGE_BAD_DATE, STAGE_TRIP_MIN, STAGE_TRIP_MAX,
        STAGE_CAP, STAGE_DISCOUNT, STAGE_DOMESTIC, STAGE_ERROR, STAGE_QUALIFIED,
    ]
    return " | ".join(f"{k}={stats.get(k, 0)}" for k in order)
