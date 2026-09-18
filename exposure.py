"""
exposure.py - Demote destinations that appeared in recent reports.

Rank penalty only: nothing is filtered out, so a genuinely great deal
still shows up, just lower down unless it beat its own recent price.
"""
import logging
from datetime import datetime, timedelta
from typing import List
from models import Flight

# How far back to look when counting repeat appearances
EXPOSURE_WINDOW_DAYS = 7
# Penalty added to value_ratio per day the destination was shown
PENALTY_PER_DAY = 0.03
# Cap so a repeat offender never sinks below genuinely worse deals
MAX_PENALTY = 0.15
# If today's price is this fraction of the recent best, waive the penalty
IMPROVEMENT_THRESHOLD = 0.90


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def record_exposure(state: dict, flights: List[Flight], top_n: int = 10) -> None:
    """Remember which destinations were shown near the top today."""
    log = state.setdefault("exposure_log", {})
    today = _today()
    cutoff = (datetime.now() - timedelta(days=EXPOSURE_WINDOW_DAYS)).strftime("%Y-%m-%d")

    # prune entries older than the window
    for key in list(log.keys()):
        log[key] = [e for e in log[key] if e["date"] >= cutoff]
        if not log[key]:
            del log[key]

    for f in flights[:top_n]:
        key = f"{f.origin}->{f.destination_name}"
        entries = log.setdefault(key, [])
        if not any(e["date"] == today for e in entries):
            entries.append({"date": today, "price": f.price})


def apply_exposure_penalty(state: dict, flights: List[Flight]) -> List[Flight]:
    """
    Re-sort with a penalty for destinations seen recently.
    The penalty is waived when today's price clearly beats the recent best.
    """
    log = state.get("exposure_log", {})
    scored = []

    for f in flights:
        entries = log.get(f"{f.origin}->{f.destination_name}", [])
        penalty = 0.0

        if entries:
            best_prev = min(e["price"] for e in entries)
            if f.price > best_prev * IMPROVEMENT_THRESHOLD:
                days_seen = len({e["date"] for e in entries})
                penalty = min(days_seen * PENALTY_PER_DAY, MAX_PENALTY)

        scored.append((f, penalty))

    scored.sort(key=lambda x: (x[0].value_ratio + x[1], x[0].price))

    demoted = sum(1 for _, p in scored if p > 0)
    if demoted:
        logging.info(f"exposure: {demoted} entries demoted for repetition")

    return [f for f, _ in scored]
