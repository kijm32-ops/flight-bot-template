"""Exact airport/date route watch using SerpAPI google_flights."""

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from config import KST, TARGET_ORIGINS
from focus import USER_CONFIG_FILE
from models import Flight
from valuation import grade, value_ratio


SLOT_MODES = {"alternate", "route_first", "region_first"}


class RouteWatchConfigError(ValueError):
    """Raised when enabled Route Watch settings are invalid."""


@dataclass(frozen=True)
class RouteWatchConfig:
    origin: str
    destination: str
    outbound_date: date
    return_date: date
    max_price: Optional[int] = None
    nonstop_only: bool = False
    name: str = ""

    @property
    def label(self) -> str:
        suffix = " / nonstop" if self.nonstop_only else ""
        prefix = f"{self.name}: " if self.name else ""
        return (
            f"{prefix}{self.origin}->{self.destination} / "
            f"{self.outbound_date}..{self.return_date}{suffix}"
        )

    def search_params(self) -> Dict[str, Any]:
        params = {
            "engine": "google_flights",
            "currency": "KRW",
            "hl": "ko",
            "gl": "kr",
            "type": 1,
            "departure_id": self.origin,
            "arrival_id": self.destination,
            "outbound_date": str(self.outbound_date),
            "return_date": str(self.return_date),
            "sort_by": 2,
        }
        if self.max_price is not None:
            params["max_price"] = self.max_price
        if self.nonstop_only:
            params["stops"] = 1
        return params


def _airport_code(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise RouteWatchConfigError(f"{name} must be a 3-letter airport code.")
    code = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise RouteWatchConfigError(f"{name} must be a 3-letter airport code.")
    return code


def _parse_date(value: Any, name: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise RouteWatchConfigError(f"{name} must be YYYY-MM-DD.")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise RouteWatchConfigError(f"{name} must be YYYY-MM-DD.") from exc


def _positive_int(value: Any, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise RouteWatchConfigError(f"{name} must be a positive integer.")
    return value


def _parse_route_watch(
    raw: Any,
    field_name: str,
    now: Optional[datetime] = None,
) -> Optional[RouteWatchConfig]:
    if not isinstance(raw, dict):
        raise RouteWatchConfigError(f"{field_name} must be a JSON object.")

    enabled = raw.get("enabled", False)
    if type(enabled) is not bool:
        raise RouteWatchConfigError(f"{field_name}.enabled must be true or false.")
    if not enabled:
        return None

    origin = _airport_code(raw.get("origin"), f"{field_name}.origin")
    if origin not in TARGET_ORIGINS:
        raise RouteWatchConfigError(
            f"{field_name}.origin must be one of: " + ", ".join(TARGET_ORIGINS)
        )

    destination = _airport_code(
        raw.get("destination"),
        f"{field_name}.destination",
    )
    if destination == origin:
        raise RouteWatchConfigError(f"{field_name}.destination must differ from origin.")

    outbound_date = _parse_date(
        raw.get("outbound_date"),
        f"{field_name}.outbound_date",
    )
    return_date = _parse_date(
        raw.get("return_date"),
        f"{field_name}.return_date",
    )
    if return_date <= outbound_date:
        raise RouteWatchConfigError(
            f"{field_name}.return_date must be after outbound_date."
        )

    today = (now or datetime.now(KST)).astimezone(KST).date()
    if outbound_date < today:
        logging.info(
            "Route Watch expired on %s; another user-intent task may use the slot.",
            outbound_date,
        )
        return None

    max_price = raw.get("max_price")
    parsed_max_price = None if max_price is None else _positive_int(
        max_price,
        f"{field_name}.max_price",
    )

    nonstop_only = raw.get("nonstop_only", False)
    if type(nonstop_only) is not bool:
        raise RouteWatchConfigError(
            f"{field_name}.nonstop_only must be true or false."
        )

    name = raw.get("name", "")
    if not isinstance(name, str):
        raise RouteWatchConfigError(f"{field_name}.name must be a string.")

    return RouteWatchConfig(
        origin=origin,
        destination=destination,
        outbound_date=outbound_date,
        return_date=return_date,
        max_price=parsed_max_price,
        nonstop_only=nonstop_only,
        name=name.strip(),
    )


def parse_route_watch_config(
    payload: Any,
    now: Optional[datetime] = None,
) -> Optional[RouteWatchConfig]:
    """Parse the v1.4 single-route shape for backward compatibility."""
    if not isinstance(payload, dict):
        raise RouteWatchConfigError("user_config.json must contain a JSON object.")
    return _parse_route_watch(payload.get("route_watch", {}), "route_watch", now)


def parse_route_watch_configs(
    payload: Any,
    now: Optional[datetime] = None,
) -> List[RouteWatchConfig]:
    """Parse v1.7 route_watches plus the legacy v1.4 route_watch object."""
    if not isinstance(payload, dict):
        raise RouteWatchConfigError("user_config.json must contain a JSON object.")

    configs: List[RouteWatchConfig] = []
    legacy = _parse_route_watch(payload.get("route_watch", {}), "route_watch", now)
    if legacy is not None:
        configs.append(legacy)

    raw_watches = payload.get("route_watches", [])
    if raw_watches is None:
        raw_watches = []
    if not isinstance(raw_watches, list):
        raise RouteWatchConfigError("route_watches must be a JSON array.")

    for index, raw in enumerate(raw_watches):
        field_name = f"route_watches[{index}]"
        try:
            config = _parse_route_watch(raw, field_name, now)
        except RouteWatchConfigError as exc:
            logging.warning("Route Watch disabled for this run: %s", exc)
            continue
        if config is not None:
            configs.append(config)
    return configs


def load_route_watch_config(
    path: Path = USER_CONFIG_FILE,
    now: Optional[datetime] = None,
) -> Optional[RouteWatchConfig]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        config = parse_route_watch_config(payload, now=now)
        if config is not None:
            logging.info("Route Watch active: %s", config.label)
        return config
    except (OSError, json.JSONDecodeError, RouteWatchConfigError) as exc:
        logging.warning("Route Watch disabled for this run: %s", exc)
        return None


def load_route_watch_configs(
    path: Path = USER_CONFIG_FILE,
    now: Optional[datetime] = None,
) -> List[RouteWatchConfig]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        configs = parse_route_watch_configs(payload, now=now)
        for config in configs:
            logging.info("Route Watch active: %s", config.label)
        return configs
    except (OSError, json.JSONDecodeError, RouteWatchConfigError) as exc:
        logging.warning("Route Watches disabled for this run: %s", exc)
        return []


def load_focus_slot_mode(path: Path = USER_CONFIG_FILE) -> str:
    if not path.exists():
        return "alternate"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "alternate"
    if not isinstance(payload, dict):
        return "alternate"
    raw = payload.get("focus_slot", {})
    if raw is None:
        return "alternate"
    if not isinstance(raw, dict):
        logging.warning("focus_slot must be a JSON object; using alternate.")
        return "alternate"
    mode = raw.get("mode", "alternate")
    if mode not in SLOT_MODES:
        logging.warning("Unknown focus_slot.mode %r; using alternate.", mode)
        return "alternate"
    return mode


@dataclass(frozen=True)
class UserIntent:
    kind: str
    config: Any


def choose_user_intent(
    focus_config: Any,
    route_configs: Sequence[RouteWatchConfig],
    mode: str,
    now: Optional[datetime] = None,
) -> Optional[UserIntent]:
    """Select one active user intent using a KST date-only, state-free rotation."""
    routes = list(route_configs)
    if focus_config is None and not routes:
        return None
    current = (now or datetime.now(KST)).astimezone(KST).date()
    route_intents = [UserIntent("route", config) for config in routes]
    focus_intent = UserIntent("focus", focus_config) if focus_config else None

    # Modes retain their v1.6 setting names as deterministic list-order choices.
    # They are not strict priorities: strict priority would starve another active intent.
    if mode == "region_first":
        candidates = ([focus_intent] if focus_intent else []) + route_intents
    else:
        candidates = route_intents + ([focus_intent] if focus_intent else [])
    return candidates[current.toordinal() % len(candidates)]


def route_watch_flight(
    config: RouteWatchConfig,
    payload: Any,
) -> Optional[Flight]:
    if not isinstance(payload, dict):
        return None

    options = []
    for key in ("best_flights", "other_flights"):
        rows = payload.get(key, [])
        if isinstance(rows, list):
            options.extend(row for row in rows if isinstance(row, dict))

    valid = []
    for item in options:
        price = item.get("price")
        if type(price) is not int or price <= 0:
            continue
        if config.max_price is not None and price > config.max_price:
            continue
        segments = item.get("flights")
        if not isinstance(segments, list) or not segments:
            continue
        valid.append(item)

    if not valid:
        return None

    item = min(valid, key=lambda row: row["price"])
    segments = item["flights"]
    price = item["price"]

    last_segment = segments[-1]
    arrival = last_segment.get("arrival_airport", {})
    destination_name = (
        arrival.get("name")
        if isinstance(arrival, dict) and isinstance(arrival.get("name"), str)
        else config.destination
    )

    airlines = []
    for segment in segments:
        airline = segment.get("airline") if isinstance(segment, dict) else None
        if isinstance(airline, str) and airline and airline not in airlines:
            airlines.append(airline)
    airline_text = ", ".join(airlines) if airlines else "Unknown"

    insights = payload.get("price_insights", {})
    average_price = 0
    if isinstance(insights, dict):
        typical = insights.get("typical_price_range")
        if (
            isinstance(typical, list)
            and len(typical) == 2
            and all(type(value) is int and value > 0 for value in typical)
        ):
            average_price = round(sum(typical) / 2)

    discount = 0
    if average_price > price:
        discount = round((average_price - price) / average_price * 100)

    metadata = payload.get("search_metadata", {})
    booking_link = ""
    if isinstance(metadata, dict):
        candidate = metadata.get("google_flights_url")
        if isinstance(candidate, str):
            booking_link = candidate

    ratio = value_ratio(
        price,
        config.destination,
        "",
        destination_name,
    )
    return Flight(
        origin=config.origin,
        destination=config.destination,
        destination_name=destination_name,
        destination_country="",
        depart_date=config.outbound_date,
        return_date=config.return_date,
        price=price,
        average_price=average_price,
        discount_percentage=discount,
        airline=airline_text,
        duration=item.get("total_duration", 0)
        if type(item.get("total_duration", 0)) is int
        else 0,
        stops=max(0, len(segments) - 1),
        booking_link=booking_link,
        value_ratio=ratio or 0.0,
        value_grade=grade(ratio),
    )
