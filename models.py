from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Tuple


@dataclass(frozen=True)
class Flight:
    origin: str                  # 출발 공항 코드 (예: ICN)
    destination: str             # 도착 공항 코드/ID
    destination_name: str        # 도착 도시명 (예: 제주시)
    destination_country: str     # 도착 국가 (예: 대한민국)
    depart_date: date            # 출발일
    return_date: date            # 귀국일
    price: int                   # 현재 특가 가격
    average_price: int           # 평소 평균 가격
    discount_percentage: int     # 할인율 (예: 76)
    airline: str                 # 항공사 코드
    duration: int                # 비행 시간 (분 단위)
    stops: int                   # 경유 횟수 (직항은 0)
    booking_link: str            # 예약 링크
    value_ratio: float = 0.0     # 권역 기준가 대비 비율 (낮을수록 특가)
    value_grade: str = ""        # "🔥 초특가" / "✨ 특가" / "👍 괜찮음" / "보통"
    alt_dates: List[Tuple[str, str, int]] = field(default_factory=list)
    # 같은 목적지의 다른 저렴한 날짜 조합: (출발일, 귀국일, 가격)

    last_confirmed_at: datetime = None
    is_carryover: bool = False

    @property
    def carryover_label(self) -> str:
        if not self.is_carryover or self.last_confirmed_at is None:
            return ""
        return (f"\uc774\uc6d4 / \ub9c8\uc9c0\ub9c9 \ud655\uc778 {self.last_confirmed_at:%m/%d %H:%M} KST"
                " / \uac00\uaca9 \uc7ac\ud655\uc778 \ud544\uc694")
