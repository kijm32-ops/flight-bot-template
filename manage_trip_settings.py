"""Safely update PTIS user_config.json from guided GitHub forms."""

import argparse
import calendar
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from config import KST
from focus import FocusConfigError, parse_focus_config
from route_watch import (
    RouteWatchConfigError,
    parse_route_watch_config,
    parse_route_watch_configs,
)

USER_CONFIG_FILE = Path("user_config.json")
OPERATIONS = {"exact_add", "exact_replace", "focus_set", "pause_all"}
MONTH_OFFSETS = {"next_1": 1, "next_2": 2, "next_3": 3, "next_4": 4,
                 "next_5": 5, "next_6": 6}
STAY_OPTIONS = {"2": (2, 4), "3": (3, 5), "4": (4, 6),
                "5": (5, 7), "7": (7, 10)}
WEEK_OFFSETS = {"week_1": 0, "week_2": 7, "week_3": 14, "week_4": 21}
ISSUE_TITLE_PREFIX = "[PTIS \uc124\uc815]"
ISSUE_FIELD_LABELS = {
    "operation": "\uc791\uc5c5",
    "origin": "\ucd9c\ubc1c \uacf5\ud56d",
    "destination_choice": "\ubaa9\uc801\uc9c0/\uc9c0\uc5ed",
    "travel_month": "\uc5ec\ud589 \uc2dc\uae30",
    "stay_option": "\uc219\ubc15",
    "departure_week": "\ucd9c\ubc1c \uc8fc\ucc28",
    "budget_option": "\uc608\uc0b0",
    "nonstop_only": "\uc9c1\ud56d \uc5ec\ubd80",
    "custom_destination": "\uc9c1\uc811 \ubaa9\uc801\uc9c0",
    "custom_outbound": "\uc9c1\uc811 \uc2dc\uc791\uc77c",
    "custom_return": "\uc9c1\uc811 \uc885\ub8cc\uc77c",
}
NO_RESPONSE_VALUES = {"", "_no response_", "no response", "_\uc751\ub2f5 \uc5c6\uc74c_"}


class SettingsError(ValueError):
    pass


def _choice_value(value: str) -> str:
    value = value.strip()
    if "(" in value and value.endswith(")"):
        return value.rsplit("(", 1)[1][:-1].strip()
    return value


def _choice_label(value: str) -> str:
    return value.split("(", 1)[0].strip()


def _add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    return date(year, month_zero + 1, 1)


def resolve_guided_inputs(
    operation: str,
    destination_choice: str,
    travel_month: str,
    departure_week: str,
    stay_option: str,
    budget_option: str,
    custom_destination: str = "",
    custom_outbound: str = "",
    custom_return: str = "",
    now: Optional[datetime] = None,
) -> Dict[str, str]:
    """Turn phone-friendly choices into the existing validated fields."""
    if operation == "pause_all":
        return {}
    current = now or datetime.now(KST)
    destination = custom_destination.strip() or _choice_value(destination_choice)
    if not destination:
        raise SettingsError("destination choice is required")
    try:
        month_start = _add_months(
            current.date(), MONTH_OFFSETS[_choice_value(travel_month)]
        )
        stay, stay_max = STAY_OPTIONS[_choice_value(stay_option)]
    except KeyError as exc:
        raise SettingsError(f"Unknown guided choice: {exc.args[0]}") from exc

    if operation == "focus_set":
        month_end = date(
            month_start.year,
            month_start.month,
            calendar.monthrange(month_start.year, month_start.month)[1],
        )
        outbound = custom_outbound.strip() or month_start.isoformat()
        returning = custom_return.strip() or month_end.isoformat()
    else:
        first_friday = month_start + timedelta(
            days=(4 - month_start.weekday()) % 7
        )
        try:
            week_offset = WEEK_OFFSETS[_choice_value(departure_week)]
        except KeyError as exc:
            raise SettingsError(f"Unknown guided choice: {exc.args[0]}") from exc
        outbound_date = first_friday + timedelta(days=week_offset)
        outbound = custom_outbound.strip() or outbound_date.isoformat()
        returning = custom_return.strip() or (
            outbound_date + timedelta(days=stay)
        ).isoformat()

    return {
        "name": _choice_label(destination_choice),
        "destination_or_region": destination,
        "outbound_from": outbound,
        "outbound_to": returning,
        "stay_min": str(stay),
        "stay_max": str(stay_max),
        "max_price": _choice_value(budget_option),
    }


def _load(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SettingsError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SettingsError("user_config.json must contain a JSON object")
    return payload


def _positive_optional(value: str, name: str) -> Optional[int]:
    value = value.strip()
    if not value or value == "0":
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise SettingsError(f"{name} must be a positive whole number") from exc
    if parsed <= 0:
        raise SettingsError(f"{name} must be a positive whole number")
    return parsed


def _required(value: str, name: str) -> str:
    value = value.strip()
    if not value:
        raise SettingsError(f"{name} is required for this operation")
    return value


def _validate(payload: Dict[str, Any], now: Optional[datetime]) -> None:
    try:
        parse_focus_config(payload, now=now)
        parse_route_watch_configs(payload, now=now)
    except (FocusConfigError, RouteWatchConfigError) as exc:
        raise SettingsError(str(exc)) from exc


def update_settings(
    payload: Dict[str, Any],
    operation: str,
    name: str = "",
    origin: str = "",
    destination_or_region: str = "",
    outbound_from: str = "",
    outbound_to: str = "",
    stay_min: str = "",
    stay_max: str = "",
    max_price: str = "",
    nonstop_only: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    if operation not in OPERATIONS:
        raise SettingsError(f"Unknown operation: {operation}")
    result = json.loads(json.dumps(payload))
    result.setdefault("focus_slot", {"mode": "alternate"})
    result.setdefault("focus_search", {"enabled": False})
    result.setdefault("route_watch", {"enabled": False})
    result.setdefault("route_watches", [])

    if operation == "pause_all":
        result["focus_search"] = {"enabled": False}
        result["route_watch"] = {"enabled": False}
        routes = result.get("route_watches", [])
        if not isinstance(routes, list):
            routes = []
        result["route_watches"] = [
            {**route, "enabled": False} if isinstance(route, dict) else route
            for route in routes
        ]
        _validate(result, now)
        return result

    origin = _required(origin, "origin").upper()
    destination_or_region = _required(
        destination_or_region, "destination or region"
    )
    outbound_from = _required(outbound_from, "first date")
    outbound_to = _required(outbound_to, "second date")
    price = _positive_optional(max_price, "max price")

    if operation == "focus_set":
        minimum = _positive_optional(stay_min, "minimum stay")
        maximum = _positive_optional(stay_max, "maximum stay")
        if minimum is None or maximum is None:
            raise SettingsError("minimum and maximum stay are required")
        focus = {
            "enabled": True,
            "origin": origin,
            "region": destination_or_region,
            "outbound_from": outbound_from,
            "outbound_to": outbound_to,
            "stay_min": minimum,
            "stay_max": maximum,
        }
        if price is not None:
            focus["max_price"] = price
        result["focus_search"] = focus
    else:
        route = {
            "name": name.strip(),
            "enabled": True,
            "origin": origin,
            "destination": destination_or_region.upper(),
            "outbound_date": outbound_from,
            "return_date": outbound_to,
            "nonstop_only": bool(nonstop_only),
        }
        if price is not None:
            route["max_price"] = price
        try:
            parse_route_watch_config({"route_watch": route}, now=now)
        except RouteWatchConfigError as exc:
            raise SettingsError(str(exc)) from exc
        if operation == "exact_replace":
            result["route_watch"] = {"enabled": False}
            result["route_watches"] = [route]
        else:
            routes = result.get("route_watches", [])
            if not isinstance(routes, list):
                raise SettingsError("route_watches must be a JSON array")
            result["route_watches"] = routes + [route]

    _validate(result, now)
    return result


def save_settings(path: Path, payload: Dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _operation(value: str) -> str:
    value = value.strip()
    mapping = {
        "1": "exact_add",
        "2": "exact_replace",
        "3": "focus_set",
        "4": "pause_all",
    }
    key = value.split(".", 1)[0]
    return mapping.get(key, value)


def _issue_sections(body: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    current = ""
    lines = []
    for raw_line in body.splitlines():
        if raw_line.startswith("### "):
            if current:
                sections[current] = "\n".join(lines).strip()
            current = raw_line[4:].strip()
            lines = []
        elif current:
            lines.append(raw_line)
    if current:
        sections[current] = "\n".join(lines).strip()
    return sections


def _issue_value(sections: Dict[str, str], key: str) -> str:
    label = ISSUE_FIELD_LABELS[key]
    value = sections.get(label, "").strip()
    if value.lower() in NO_RESPONSE_VALUES:
        return ""
    return value


def resolve_issue_event_inputs(event_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Parse one owner-authored GitHub Issue Form event into guided inputs."""
    if not isinstance(event_payload, dict):
        raise SettingsError("issue event must be a JSON object")

    repository = event_payload.get("repository")
    sender = event_payload.get("sender")
    issue = event_payload.get("issue")
    if not isinstance(repository, dict) or not isinstance(sender, dict) or not isinstance(issue, dict):
        raise SettingsError("issue event is missing repository, sender, or issue data")

    owner = repository.get("owner")
    if not isinstance(owner, dict):
        raise SettingsError("issue event is missing repository owner data")
    owner_login = str(owner.get("login", "")).strip()
    sender_login = str(sender.get("login", "")).strip()
    if not owner_login or sender_login != owner_login:
        raise SettingsError("only the repository owner can apply PTIS settings")

    title = str(issue.get("title", ""))
    if not title.startswith(ISSUE_TITLE_PREFIX):
        raise SettingsError("issue title is not a PTIS settings request")

    body = issue.get("body")
    if not isinstance(body, str):
        raise SettingsError("issue body is missing")
    sections = _issue_sections(body)

    operation_raw = _issue_value(sections, "operation")
    operation = _operation(operation_raw)
    if operation not in OPERATIONS:
        raise SettingsError("issue operation is missing or invalid")

    nonstop = _choice_value(_issue_value(sections, "nonstop_only")).lower() == "true"
    return {
        "operation": operation,
        "origin": _issue_value(sections, "origin"),
        "destination_choice": _issue_value(sections, "destination_choice"),
        "travel_month": _issue_value(sections, "travel_month"),
        "stay_option": _issue_value(sections, "stay_option"),
        "departure_week": _issue_value(sections, "departure_week"),
        "budget_option": _issue_value(sections, "budget_option"),
        "nonstop_only": nonstop,
        "custom_destination": _issue_value(sections, "custom_destination"),
        "custom_outbound": _issue_value(sections, "custom_outbound"),
        "custom_return": _issue_value(sections, "custom_return"),
    }


def _read_issue_event(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SettingsError(f"Cannot read issue event {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SettingsError("issue event must contain a JSON object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=USER_CONFIG_FILE)
    parser.add_argument("--issue-event", type=Path)
    parser.add_argument("--operation", default="")
    parser.add_argument("--name", default="")
    parser.add_argument("--origin", default="")
    parser.add_argument("--destination-or-region", default="")
    parser.add_argument("--outbound-from", default="")
    parser.add_argument("--outbound-to", default="")
    parser.add_argument("--stay-min", default="")
    parser.add_argument("--stay-max", default="")
    parser.add_argument("--max-price", default="")
    parser.add_argument("--nonstop-only", action="store_true")
    parser.add_argument("--destination-choice", default="")
    parser.add_argument("--travel-month", default="")
    parser.add_argument("--departure-week", default="week_2")
    parser.add_argument("--stay-option", default="")
    parser.add_argument("--budget-option", default="0")
    parser.add_argument("--custom-destination", default="")
    parser.add_argument("--custom-outbound", default="")
    parser.add_argument("--custom-return", default="")
    args = parser.parse_args()
    try:
        if args.issue_event:
            issue_inputs = resolve_issue_event_inputs(_read_issue_event(args.issue_event))
            args.operation = issue_inputs["operation"]
            args.origin = issue_inputs["origin"]
            args.destination_choice = issue_inputs["destination_choice"]
            args.travel_month = issue_inputs["travel_month"]
            args.stay_option = issue_inputs["stay_option"]
            args.departure_week = issue_inputs["departure_week"]
            args.budget_option = issue_inputs["budget_option"]
            args.nonstop_only = issue_inputs["nonstop_only"]
            args.custom_destination = issue_inputs["custom_destination"]
            args.custom_outbound = issue_inputs["custom_outbound"]
            args.custom_return = issue_inputs["custom_return"]

        operation = _operation(args.operation)
        if args.destination_choice and operation != "pause_all":
            guided = resolve_guided_inputs(
                operation, args.destination_choice, args.travel_month,
                args.departure_week, args.stay_option, args.budget_option,
                args.custom_destination, args.custom_outbound,
                args.custom_return, now=datetime.now(KST),
            )
            args.name = guided["name"]
            args.destination_or_region = guided["destination_or_region"]
            args.outbound_from = guided["outbound_from"]
            args.outbound_to = guided["outbound_to"]
            args.stay_min = guided["stay_min"]
            args.stay_max = guided["stay_max"]
            args.max_price = guided["max_price"]
        payload = update_settings(
            _load(args.config), operation, args.name, args.origin,
            args.destination_or_region, args.outbound_from, args.outbound_to,
            args.stay_min, args.stay_max, args.max_price, args.nonstop_only,
            now=datetime.now(KST),
        )
        save_settings(args.config, payload)
    except SettingsError as exc:
        parser.error(str(exc))
    print(f"Saved {args.config} for {operation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
