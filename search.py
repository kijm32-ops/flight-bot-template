import requests
import logging
from typing import Dict, Any, List
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type


class APIFetchError(Exception):
    pass


# 최대 3회 재시도 (대기 시간: 2초 -> 4초 -> 8초)
@retry(
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(APIFetchError)
)
def fetch_raw_flight_deals(api_key: str, base_params: Dict[str, Any], origin: str) -> List[Dict[str, Any]]:
    url = "https://serpapi.com/search.json"
    request_params = {**base_params, "api_key": api_key, "departure_id": origin}

    try:
        logging.info(f"[{origin}] 구글 플라이트 특가 데이터 검색 중...")
        res = requests.get(url, params=request_params, timeout=30)
        res.raise_for_status()
        data = res.json()

        deals = data.get("deals", [])
        logging.info(f"[{origin}] {len(deals)}건 수신")
        return deals
    except requests.exceptions.RequestException as e:
        logging.error(f"[{origin}] ❌ API 호출 에러: {e}")
        raise APIFetchError(f"API Fetch Failed for {origin}: {e}")


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(APIFetchError)
)
def fetch_google_flights(api_key: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch one google_flights response without selecting a return leg."""
    url = "https://serpapi.com/search.json"
    request_params = {**params, "api_key": api_key}
    label = (
        f"{request_params.get('departure_id', '?')}->"
        f"{request_params.get('arrival_id', '?')}"
    )
    try:
        logging.info("[%s] exact route watch search", label)
        res = requests.get(url, params=request_params, timeout=30)
        res.raise_for_status()
        data = res.json()
        if not isinstance(data, dict):
            raise APIFetchError(f"Invalid google_flights response for {label}")
        logging.info(
            "[%s] %d best + %d other flight options received",
            label,
            len(data.get("best_flights", []) or []),
            len(data.get("other_flights", []) or []),
        )
        return data
    except requests.exceptions.RequestException as exc:
        logging.error("[%s] google_flights API error: %s", label, exc)
        raise APIFetchError(
            f"Google Flights fetch failed for {label}: {exc}"
        )
