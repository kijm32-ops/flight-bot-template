import os
from datetime import datetime, timedelta, timezone

SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_PASSWORD = os.environ.get("GMAIL_PASSWORD")
KAKAO_JS_KEY = os.environ.get("KAKAO_JS_KEY")
KAKAO_REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY")
KAKAO_CLIENT_SECRET = os.environ.get("KAKAO_CLIENT_SECRET")
KAKAO_TOKEN_ENCRYPTION_KEY = os.environ.get("KAKAO_TOKEN_ENCRYPTION_KEY")


def _github_pages_url() -> str:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    owner, separator, name = repository.partition("/")
    if not separator or not owner or not name:
        return ""
    return f"https://{owner}.github.io/{name}/"


def _kakao_card_image_url() -> str:
    explicit_url = os.environ.get("PTIS_KAKAO_CARD_IMAGE_URL")
    if explicit_url:
        return explicit_url
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    revision = os.environ.get("GITHUB_SHA") or os.environ.get("GITHUB_REF_NAME")
    if repository and revision:
        return f"https://raw.githubusercontent.com/{repository}/{revision}/assets/kakao_card_v1.png"
    return ""


# Deployment URLs have one source: GitHub Actions repository context. PTIS_PAGE_URL
# and PTIS_KAKAO_CARD_IMAGE_URL are explicit overrides for custom domains or local tests.
PAGE_URL = os.environ.get("PTIS_PAGE_URL") or _github_pages_url()
KAKAO_CARD_IMAGE_URL = _kakao_card_image_url()

# 양양(YNY) 제외 — 국제선 노선이 거의 없어 호출 대비 수확이 없음
TARGET_ORIGINS = ["ICN", "CJJ", "GMP"]
DOMESTIC_ALLOWED_ORIGINS = ["CJJ", "GMP", "ICN"]

# ── SerpApi 무료 티어 예산 관리 ──────────────────────
SERPAPI_MONTHLY_LIMIT = 250
SERPAPI_SAFE_BUDGET = 235        # 재시도/수동실행 대비 15회 예비분
API_QUOTA_WARNING_THRESHOLD = 200
# ────────────────────────────────────────────────────

# ── 출발지 접근비용 ─────────────────────────────────
# 집 -> 공항 왕복 실비 + 시간가치. 가격 비교/상한 판정은 이걸 더한 값으로 한다.
ACCESS_COST = {"ICN": 0, "GMP": 0, "CJJ": 25_000}
ACCESS_COST_DEFAULT = 0
# ────────────────────────────────────────────────────

# ── 권역별 절대 가격 상한 (가격 컷의 단일 출처) ──────
# "아무리 할인율이 커도 이 위면 결제하지 않는다" 선.
# 접근비용을 더한 실질 지불액과 비교한다.
#
# 이전에는 normalizer 의 MAX_VALUE_RATIO 와 이 상한이 이중으로 걸려 있었는데,
# 계측해보니 근거리/중거리에서는 상한 대비 기준가 비율이 1.25~1.33 이라
# ratio 1.20 쪽이 항상 먼저 죽여 후보를 깎아먹었고,
# 유럽/미주에서는 반대로 0.65~0.72 라 ratio 가 아무 역할도 못 했다.
# 어느 tier 에서도 유용하지 않아 ratio 게이트는 제거하고 상한으로 일원화했다.
TIER_HARD_CAP = {
    "domestic": 60_000,
    "jp_near": 200_000,
    "jp_mid": 260_000,
    "cn_near": 200_000,
    "cn_mid": 280_000,
    "tw_hk": 250_000,
    "sea_near": 300_000,
    "sea_mid": 330_000,
    "sea_far": 480_000,
    "mongolia": 330_000,
    "guam": 400_000,
    # 대양주는 유럽/미주와 같은 650,000 을 쓰다가 시드니 665,828(기준가 대비 0.83),
    # 브리즈번 695,452 를 놓쳤다. 호주 왕복으로는 충분히 좋은 값이라 700,000 으로 올림.
    "oceania": 700_000,
    "europe": 650_000,
    "namerica": 650_000,
    "longhaul": 650_000,
}
HARD_CAP_DEFAULT = 650_000
# ────────────────────────────────────────────────────

# ── 특가 판정 기준 ──────────────────────────────────
ALERT_VALUE_RATIO = 0.85
MIN_DISCOUNT_PERCENTAGE = 20
DISCOUNT_BYPASS_RATIO = 0.75
ORIGIN_SWAP_THRESHOLD = 50_000

# selection.strict_collapse() 가 목적지당 1건을 최종 보장하므로
# 여기서는 1로 두고 나머지는 alt_dates 로 접는다.
MAX_PER_DESTINATION = 1
KEEP_ALT_DATES = 4

# 체류일수 상한에 허용할 여유일. far/deep 프로필은 trip_length 7~16 으로
# 검색하기 때문에 상한을 엄격히 적용하면 근거리 결과가 거의 전멸한다.
TRIP_DAYS_MAX_SLACK = 5
# ────────────────────────────────────────────────────

# ── 권역별 체류일수는 valuation.TIER_TRIP_DAYS 가 단일 출처 ──
# 이전 버전은 여기에 같은 이름의 사본을 두었으나 아무도 참조하지 않는
# 죽은 코드였고, valuation.py 쪽과 값이 어긋나 있었다
# (sea_far 10 vs 12, sea_mid 는 여기 아예 없었음).
# 수정할 일이 있으면 valuation.py 만 고칠 것.
# ────────────────────────────────────────────────────

# ── 요일 판정 (GitHub Actions는 UTC로 동작하므로 KST 고정) ──
KST = timezone(timedelta(hours=9))


def _now_kst() -> datetime:
    return datetime.now(KST)


def is_deep_scan_day() -> bool:
    """
    주 1회 심층 검색 실행 여부.
    - 기본: 한국 시간 토요일(weekday() == 5)
    - FORCE_DEEP_SCAN=1 환경변수로 강제 실행 가능 (테스트/수동 트리거용)
    """
    if os.environ.get("FORCE_DEEP_SCAN") == "1":
        return True
    return _now_kst().weekday() == 5


tomorrow = _now_kst() + timedelta(days=1)


def _range(start_offset: int, end_offset: int) -> str:
    s = tomorrow + timedelta(days=start_offset)
    e = tomorrow + timedelta(days=end_offset)
    return f"{s.strftime('%Y-%m-%d')},{e.strftime('%Y-%m-%d')}"


# 프로필 정의: {이름: (outbound_date 범위, trip_length, max_price)}
#
# max_price 는 SerpApi 에 그대로 넘어간다. ICN 호출이 매번 정확히 30건을
# 돌려주는 것으로 보아 응답 건수에 상한이 있고, 그렇다면 "그 30칸에 무엇이
# 담기느냐"가 수확량을 좌우한다. 상한을 넘을 게 뻔한 고가 노선이 슬롯을
# 차지하지 않도록, 각 프로필이 노리는 tier 들의 TIER_HARD_CAP 최대값을 건다.
PROFILES = {
    "near":  (_range(0, 60),    "2,7",  280_000),
    "mid":   (_range(45, 150),  "3,9",  400_000),
    "sea":   (_range(30, 120),  "4,11", 480_000),
    "far":   (_range(90, 240),  "7,14", 700_000),
    "deep":  (_range(240, 330), "7,16", 700_000),
}

# 출발지별로 실제 의미 있는 프로필만 배정
ORIGIN_PROFILES = {
    "ICN": ["near", "mid", "sea", "far", "deep"],
    "CJJ": ["near", "mid"],
    "GMP": ["near"],
}

# 매일 실행되는 작업 (우선순위 순 — 예산 부족 시 뒤에서부터 잘림)
# 7작업 x 31일 = 217, + 심층 약 4.3회 = 약 221회/월 (안전 예산 235)
DAILY_TASK_PRIORITY = [
    ("ICN", "near"),
    ("ICN", "mid"),
    ("ICN", "sea"),
    ("CJJ", "near"),
    ("ICN", "far"),
    ("CJJ", "mid"),
    ("GMP", "near"),
]

# 심층 검색일에만 추가되는 작업 (일반 작업보다 후순위)
DEEP_TASK_PRIORITY = [
    ("ICN", "deep"),
]

BASE_SEARCH_PARAMS = {
    "engine": "google_flights_deals",
    "currency": "KRW",
    "hl": "ko",
    "gl": "kr",
}
