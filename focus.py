"""User-intent Focus Search configuration and request construction."""

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional

from config import BASE_SEARCH_PARAMS, KST, TARGET_ORIGINS


USER_CONFIG_FILE = Path(__file__).resolve().parent / "user_config.json"


class FocusConfigError(ValueError):
    """Raised when enabled Focus Search settings are invalid."""


@dataclass(frozen=True)
class FocusConfig:
    origin: str
    region: str
    outbound_from: date
    outbound_to: date
    stay_min: Optional[int] = None
    stay_max: Optional[int] = None
    max_price: Optional[int] = None

    @property
    def label(self) -> str:
        label = f"{self.region} / {self.outbound_from}..{self.outbound_to}"
        if self.stay_min is not None:
            if self.stay_min == self.stay_max:
                label += f" / {self.stay_min}d"
            else:
                label += f" / {self.stay_min}-{self.stay_max}d"
        return label

    def query_text(self) -> str:
        if self.stay_min is None:
            return self.region
        if self.stay_min == self.stay_max:
            duration = f"{self.stay_min} day trip"
        else:
            duration = f"{self.stay_min} to {self.stay_max} day trip"
        return f"{self.region}, {duration}"

    def search_params(self) -> Dict[str, Any]:
        params = {
            **BASE_SEARCH_PARAMS,
            "query": self.query_text(),
            "outbound_date": f"{self.outbound_from},{self.outbound_to}",
        }
        if self.max_price is not None:
            params["max_price"] = self.max_price
        return params

    def matches(self, flight) -> bool:
        if not (self.outbound_from <= flight.depart_date <= self.outbound_to):
            return False
        if self.max_price is not None and flight.price > self.max_price:
            return False
        if self.stay_min is not None:
            days = (flight.return_date - flight.depart_date).days
            if not (self.stay_min <= days <= self.stay_max):
                return False
        return True


def _parse_date(value: Any, name: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise FocusConfigError(f"{name} must be YYYY-MM-DD.")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise FocusConfigError(f"{name} must be YYYY-MM-DD.") from exc


def _positive_int(value: Any, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise FocusConfigError(f"{name} must be a positive integer.")
    return value


def parse_focus_config(payload: Any, now: Optional[datetime] = None) -> Optional[FocusConfig]:
    if not isinstance(payload, dict):
        raise FocusConfigError("user_config.json must contain a JSON object.")

    raw = payload.get("focus_search", {})
    if not isinstance(raw, dict):
        raise FocusConfigError("focus_search must be a JSON object.")

    enabled = raw.get("enabled", False)
    if type(enabled) is not bool:
        raise FocusConfigError("focus_search.enabled must be true or false.")
    if not enabled:
        return None

    origin = raw.get("origin")
    if not isinstance(origin, str):
        raise FocusConfigError("focus_search.origin is required.")
    origin = origin.strip().upper()
    if origin not in TARGET_ORIGINS:
        raise FocusConfigError(
            "focus_search.origin must be one of: " + ", ".join(TARGET_ORIGINS)
        )

    region = raw.get("region")
    if not isinstance(region, str) or not region.strip():
        raise FocusConfigError("focus_search.region is required.")
    region = region.strip()

    outbound_from = _parse_date(raw.get("outbound_from"), "focus_search.outbound_from")
    outbound_to = _parse_date(raw.get("outbound_to"), "focus_search.outbound_to")
    if outbound_from > outbound_to:
        raise FocusConfigError("focus_search.outbound_from must not be after outbound_to.")

    today = (now or datetime.now(KST)).astimezone(KST).date()
    if outbound_to < today:
        logging.info("Focus Search expired on %s; discovery slot restored.", outbound_to)
        return None
    if outbound_from < today:
        outbound_from = today

    stay_min = raw.get("stay_min")
    stay_max = raw.get("stay_max")
    if stay_min is None and stay_max is None:
        parsed_stay_min = parsed_stay_max = None
    elif stay_min is None or stay_max is None:
        raise FocusConfigError("focus_search.stay_min and stay_max must be set together.")
    else:
        parsed_stay_min = _positive_int(stay_min, "focus_search.stay_min")
        parsed_stay_max = _positive_int(stay_max, "focus_search.stay_max")
        if parsed_stay_min > parsed_stay_max:
            raise FocusConfigError("focus_search.stay_min must not exceed stay_max.")

    max_price = raw.get("max_price")
    parsed_max_price = None if max_price is None else _positive_int(
        max_price, "focus_search.max_price"
    )

    return FocusConfig(
        origin=origin,
        region=region,
        outbound_from=outbound_from,
        outbound_to=outbound_to,
        stay_min=parsed_stay_min,
        stay_max=parsed_stay_max,
        max_price=parsed_max_price,
    )


def load_focus_config(
    path: Path = USER_CONFIG_FILE,
    now: Optional[datetime] = None,
) -> Optional[FocusConfig]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        config = parse_focus_config(payload, now=now)
        if config is not None:
            logging.info("Focus Search active: %s", config.label)
        return config
    except (OSError, json.JSONDecodeError, FocusConfigError) as exc:
        logging.warning("Focus Search disabled for this run: %s", exc)
        return None
