"""Offline candidate validation and fresh-first selection. No network access."""
import logging
from dataclasses import replace
from datetime import datetime, timedelta

from config import KST
from exposure import apply_exposure_penalty
from selection import (
    strict_collapse, apply_caps, sort_by_score, apply_quota, assign_grades,
)
from valuation import normalize_name

# Single source for the elapsed-time TTL; exactly 48 hours is still valid.
CARRYOVER_TTL = timedelta(days=2)


def destination_key(flight):
    # origin_compare appends presentation text; it is not part of city identity.
    return normalize_name(flight.destination_name.split(" \u26a0\ufe0f ")[0])


def valid_departure(flight, now):
    return flight.depart_date > now.astimezone(KST).date() and flight.return_date > flight.depart_date


def valid_carryover(flight, now):
    confirmed = flight.last_confirmed_at
    return (
        confirmed is not None and confirmed.tzinfo is not None
        and timedelta(0) <= now - confirmed <= CARRYOVER_TTL
        and valid_departure(flight, now)
    )


def select_with_carryover(state, fresh, carried, now=None):
    now = now or datetime.now(KST)
    fresh = [f for f in fresh if valid_departure(f, now)]
    fresh_keys = {destination_key(f) for f in fresh}
    selected = apply_quota(apply_exposure_penalty(
        state, sort_by_score(apply_caps(strict_collapse(fresh)))
    ))
    eligible = [f for f in carried
                if valid_carryover(f, now) and destination_key(f) not in fresh_keys]
    capped = apply_caps(eligible)
    ranked = apply_exposure_penalty(state, sort_by_score(strict_collapse(capped)))
    # Do not merge unconfirmed alternate dates under a newer confirmation stamp.
    ranked = [replace(f, alt_dates=[]) for f in ranked]
    backfill = apply_quota(ranked, reserved=selected)
    logging.info(
        "CARRYOVER: loaded=%d eligible=%d cap_pass=%d unique=%d backfill=%d fresh=%d",
        len(carried), len(eligible), len(capped), len(ranked), len(backfill), len(selected),
    )
    # Grades reflect final display order. Carryover cannot move ahead of fresh.
    return assign_grades(selected + backfill)
