# selection.py
# PTIS 리포트 최종 선별 단계.
# NOTE: All Korean text uses unicode escapes (\uXXXX) to survive copy-paste.
#
# merge_and_collapse() -> annotate_origin_alternatives() 이후에 호출한다.
#   strict_collapse -> apply_caps -> sort_by_score
#   -> (exposure penalty) -> apply_quota -> assign_grades
#
# valuation.py 는 수정하지 않는다. tier/baseline 만 가져다 쓴다.

import logging
from dataclasses import replace
from typing import Dict, List

from config import (
    ACCESS_COST, ACCESS_COST_DEFAULT, TIER_HARD_CAP, HARD_CAP_DEFAULT,
)
from models import Flight
from valuation import TIER_BASELINE, normalize_name, resolve_tier

# ---------------------------------------------------------------------------
# 1. 접근비용  (값은 config.ACCESS_COST 가 단일 출처)
# ---------------------------------------------------------------------------


def access_cost(flight: Flight) -> int:
    return ACCESS_COST.get(flight.origin, ACCESS_COST_DEFAULT)


def effective_price(flight: Flight) -> int:
    """정렬/비교/상한 판정의 기준이 되는 실질 지불액."""
    return flight.price + access_cost(flight)


def tier_of(flight: Flight) -> str:
    return resolve_tier(
        flight.destination, flight.destination_country, flight.destination_name
    )


def effective_ratio(flight: Flight) -> float:
    baseline = TIER_BASELINE.get(tier_of(flight))
    if not baseline:
        return 1.0
    return effective_price(flight) / baseline


# ---------------------------------------------------------------------------
# 2. tier별 절대 상한  (값은 config.TIER_HARD_CAP 가 단일 출처)
# ---------------------------------------------------------------------------
# normalizer 가 이미 같은 상한으로 걸러내므로 여기서는 안전망 역할이다.
# 이월 풀처럼 normalizer 를 거치지 않는 경로가 생길 때를 대비해 남겨둔다.


def apply_caps(flights: List[Flight]) -> List[Flight]:
    kept, dropped = [], []
    for f in flights:
        cap = TIER_HARD_CAP.get(tier_of(f), HARD_CAP_DEFAULT)
        (kept if effective_price(f) <= cap else dropped).append(f)

    if dropped:
        logging.info(
            "cap: dropped %d over ceiling (%s)",
            len(dropped),
            ", ".join(f"{d.destination_name} {effective_price(d):,}" for d in dropped[:5]),
        )
    return kept


# ---------------------------------------------------------------------------
# 3. 목적지 단위 strict collapse (출발지 무관, 등급 부여 이전)
# ---------------------------------------------------------------------------

MAX_ALT_DATES = 2


def strict_collapse(flights: List[Flight]) -> List[Flight]:
    """
    destination_name 단독 키로 목적지당 정확히 1건만 남긴다.
    normalizer.collapse_by_destination() 이 출발지별로 동작하기 때문에
    GMP/CJJ 제주 같은 중복이 살아남는데, 여기서 최종적으로 정리한다.

    같은 출발지의 다른 날짜 -> alt_dates 로 흡수.
    다른 출발지 -> 그냥 버린다. alt_dates 튜플에 origin 을 담을 자리가 없어서
    표시하면 출발지를 오인하게 된다.
    """
    buckets: Dict[str, List[Flight]] = {}
    for f in flights:
        buckets.setdefault(normalize_name(f.destination_name), []).append(f)

    merged: List[Flight] = []
    for group in buckets.values():
        group.sort(key=effective_price)
        winner, rest = group[0], group[1:]

        alts = list(winner.alt_dates)
        for other in rest:
            if len(alts) >= MAX_ALT_DATES:
                break
            if other.origin != winner.origin:
                continue
            entry = (str(other.depart_date), str(other.return_date), other.price)
            if entry not in alts:
                alts.append(entry)

        if alts != list(winner.alt_dates):
            merged.append(replace(winner, alt_dates=alts))
        else:
            merged.append(winner)

    logging.info("strict_collapse: %d -> %d", len(flights), len(merged))
    return merged


# ---------------------------------------------------------------------------
# 4. 점수 / 정렬
# ---------------------------------------------------------------------------

# 기준가 대비 할인폭(%)에 곱하는 가중치.
# tier 내부 경쟁은 쿼터가 이미 격리하므로, 여기서는 노출 순서만 결정한다.
TIER_WEIGHT = {
    "domestic": 1.6,
    "jp_near": 1.2, "jp_mid": 1.2, "cn_near": 1.2, "cn_mid": 1.2, "tw_hk": 1.2,
    "sea_near": 1.0, "sea_mid": 1.0, "sea_far": 1.0, "mongolia": 1.0, "guam": 1.0,
    "oceania": 0.7, "europe": 0.7, "namerica": 0.7, "longhaul": 0.7,
}
TIER_WEIGHT_DEFAULT = 1.0


def score(flight: Flight) -> float:
    discount_pct = (1.0 - effective_ratio(flight)) * 100.0
    return discount_pct * TIER_WEIGHT.get(tier_of(flight), TIER_WEIGHT_DEFAULT)


def sort_by_score(flights: List[Flight]) -> List[Flight]:
    """
    effective_ratio 를 Flight.value_ratio 에 반영해 두어야
    report_generator 의 '기준가 대비 %' 툴팁이 접근비용까지 반영한 값이 된다.
    """
    rescored = [replace(f, value_ratio=round(effective_ratio(f), 3)) for f in flights]
    rescored.sort(key=score, reverse=True)
    return rescored


# ---------------------------------------------------------------------------
# 5. 쿼터
# ---------------------------------------------------------------------------

TIER_GROUP = {
    "domestic": "domestic",
    "jp_near": "near", "jp_mid": "near",
    "cn_near": "near", "cn_mid": "near", "tw_hk": "near",
    "sea_near": "mid", "sea_mid": "mid", "sea_far": "mid",
    "mongolia": "mid", "guam": "mid",
    "oceania": "far", "europe": "far", "namerica": "far", "longhaul": "far",
}
GROUP_DEFAULT = "mid"

SLOT_QUOTA = {"domestic": 2, "near": 8, "mid": 6, "far": 2}
WILDCARD_SLOTS = 2
TOTAL_SLOTS = sum(SLOT_QUOTA.values()) + WILDCARD_SLOTS  # 20


def group_of(flight: Flight) -> str:
    return TIER_GROUP.get(tier_of(flight), GROUP_DEFAULT)


def apply_quota(flights: List[Flight], reserved: List[Flight] = None) -> List[Flight]:
    """입력 순서(점수 + 노출 감점 반영)를 그대로 유지한 채 쿼터만 적용한다."""
    reserved = reserved or []
    capacity = max(0, TOTAL_SLOTS - len(reserved))
    remaining = dict(SLOT_QUOTA)
    for f in reserved:
        g = group_of(f)
        remaining[g] = max(0, remaining.get(g, 0) - 1)
    picked_idx, leftover_idx = [], []

    for i, f in enumerate(flights):
        g = group_of(f)
        if remaining.get(g, 0) > 0 and len(picked_idx) < capacity:
            remaining[g] -= 1
            picked_idx.append(i)
        else:
            leftover_idx.append(i)

    free = capacity - len(picked_idx)
    if free > 0:
        picked_idx.extend(leftover_idx[:free])

    picked_idx.sort()
    result = [flights[i] for i in picked_idx]

    logging.info("quota: %d -> %d (free slots: %d)", len(flights), len(result), free)
    return result


# ---------------------------------------------------------------------------
# 6. 상대평가 등급
# ---------------------------------------------------------------------------

GRADE_SUPER = "\U0001F525 \uCD08\uD2B9\uAC00"
GRADE_GOOD = "\u2728 \uD2B9\uAC00"
GRADE_OK = "\U0001F44D \uAD1C\uCC2E\uC74C"
GRADE_NONE = ""

SUPER_CUT = 0.10
GOOD_CUT = 0.30
OK_CUT = 0.60


def assign_grades(flights: List[Flight]) -> List[Flight]:
    """절대 임계값 대신 회차 내 순위 백분위로 등급을 준다."""
    n = len(flights)
    if n == 0:
        return []

    out = []
    for i, f in enumerate(flights):
        pct = i / n
        if pct < SUPER_CUT:
            g = GRADE_SUPER
        elif pct < GOOD_CUT:
            g = GRADE_GOOD
        elif pct < OK_CUT:
            g = GRADE_OK
        else:
            g = GRADE_NONE
        out.append(replace(f, value_grade=g))
    return out
