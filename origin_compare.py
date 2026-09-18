# origin_compare.py
from typing import List, Dict
from dataclasses import replace
from models import Flight
from config import ORIGIN_SWAP_THRESHOLD


def annotate_origin_alternatives(all_flights: List[Flight]) -> List[Flight]:
    """
    ICN 출발이 지방 출발(CJJ/GMP/YNY)보다 ORIGIN_SWAP_THRESHOLD 이상 저렴하면
    지방 출발 항공편의 destination_name에 경고 문구를 덧붙인다.
    """
    icn_best: Dict[str, Flight] = {}
    for f in all_flights:
        if f.origin == "ICN":
            cur = icn_best.get(f.destination)
            if cur is None or f.price < cur.price:
                icn_best[f.destination] = f

    result = []
    for f in all_flights:
        if f.origin == "ICN":
            result.append(f)
            continue

        alt = icn_best.get(f.destination)
        if alt and (f.price - alt.price) >= ORIGIN_SWAP_THRESHOLD:
            diff = f.price - alt.price
            new_name = (
                f"{f.destination_name} ⚠️ ICN 출발 {alt.price:,}원 "
                f"({diff:,}원 저렴)"
            )
            result.append(replace(f, destination_name=new_name))
        else:
            result.append(f)

    return result
