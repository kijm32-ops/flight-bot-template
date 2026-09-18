import os
import logging
import html as html_lib
from typing import List, Set, Tuple
from models import Flight

OUTPUT_DIR = "public"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "index.html")

# value_grade 문자열 → CSS 클래스 매핑
GRADE_CLASS = {
    "🔥 초특가": "grade-super",
    "✨ 특가": "grade-good",
    "👍 괜찮음": "grade-ok",
}


def _grade_badge(deal: Flight) -> str:
    """권역 기준가 대비 등급 배지 HTML"""
    if not deal.value_grade or deal.value_grade == "unknown":
        return ""
    cls = GRADE_CLASS.get(deal.value_grade, "grade-ok")
    ratio_text = f"기준가 대비 {int(deal.value_ratio * 100)}%"
    return f"<span class='grade {cls}' title='{ratio_text}'>{deal.value_grade}</span>"


def _alt_dates_html(deal: Flight) -> str:
    """같은 목적지의 다른 저렴한 날짜 조합"""
    if not deal.alt_dates:
        return ""
    items = ""
    for depart, ret, price in deal.alt_dates:
        items += f"<li>{depart} ~ {ret} · {price:,}원</li>"
    return f"""
        <details class='alt'>
            <summary>다른 날짜 {len(deal.alt_dates)}건</summary>
            <ul>{items}</ul>
        </details>
    """


def generate_report_html(
    deals: List[Flight],
    js_key: str,
    low_price_keys: Set[Tuple[str, str, str, str]] = None,
    focus_deals: List[Flight] = None,
    focus_label: str = "",
    route_watch_deals: List[Flight] = None,
    route_watch_label: str = "",
) -> None:
    low_price_keys = low_price_keys or set()
    focus_deals = focus_deals or []
    route_watch_deals = route_watch_deals or []
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    def render_rows(items: List[Flight], empty_message: str) -> str:
        if not items:
            return (
                "<tr><td colspan='4' style='padding:20px;text-align:center;'>"
                + empty_message
                + "</td></tr>"
            )

        rows = ""
        for deal in items:
            trip_nights = (deal.return_date - deal.depart_date).days
            dedup_key = (
                deal.origin,
                deal.destination,
                str(deal.depart_date),
                str(deal.return_date),
            )
            badge = (
                "<br><span class='badge'>\U0001F525 30\uC77C \uCD5C\uC800\uAC00</span>"
                if dedup_key in low_price_keys else ""
            )
            grade_badge = _grade_badge(deal)
            alt_html = _alt_dates_html(deal)
            carryover_html = (
                f"<br><small>{deal.carryover_label}</small>"
                if deal.is_carryover else ""
            )

            rows += f"""
            <tr>
                <td>
                    {deal.origin} \u2794 {deal.destination_name}
                    <br><span class='sub'>({deal.destination_country})</span>
                    {f"<br>{grade_badge}" if grade_badge else ""}
                </td>
                <td>
                    {deal.depart_date} ~ {deal.return_date}
                    <br><span class='sub'>({trip_nights}\uBC15 {trip_nights+1}\uC77C)</span>
                    {alt_html}
                </td>
                <td class='price'>
                    {deal.price:,}\uC6D0<br>
                    <span class='sub'>(-{deal.discount_percentage}%)</span>
                    {badge}
                    {carryover_html}
                </td>
                <td><a href="{deal.booking_link}" target="_blank" rel="noopener">\uD655\uC778</a></td>
            </tr>
            """
        return rows

    rows_html = render_rows(
        deals,
        "\uC624\uB298\uC740 \uC870\uAC74\uC5D0 \uB9DE\uB294 \uD2B9\uAC00\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4.",
    )
    focus_rows_html = render_rows(
        focus_deals,
        "\uAD00\uC2EC\uAC80\uC0C9 \uC870\uAC74\uC5D0 \uB9DE\uB294 \uACB0\uACFC\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4.",
    )
    safe_focus_label = html_lib.escape(focus_label)
    safe_route_watch_label = html_lib.escape(route_watch_label)

    route_watch_rows_html = render_rows(
        route_watch_deals,
        "\uB178\uC120\uAC10\uC2DC \uC870\uAC74\uC5D0 \uB9DE\uB294 \uACB0\uACFC\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4.",
    )
    route_watch_section = ""
    if route_watch_deals:
        route_watch_section = f"""
        <section class='route-box'>
          <h2>\U0001F4CD \uB178\uC120\uAC10\uC2DC ({len(route_watch_deals)}\uAC74)</h2>
          <p class='route-label'>{safe_route_watch_label}</p>
          <table>
            <tr>
              <th>\uB178\uC120</th><th>\uC77C\uC815</th><th>\uD2B9\uAC00 \uAE08\uC561</th><th>\uC608\uC57D</th>
            </tr>
            {route_watch_rows_html}
          </table>
        </section>
        """

    focus_section = ""
    if focus_deals:
        focus_section = f"""
        <section class='focus-box'>
          <h2>\U0001F3AF \uAD00\uC2EC\uAC80\uC0C9 ({len(focus_deals)}\uAC74)</h2>
          <p class='focus-label'>{safe_focus_label}</p>
          <table>
            <tr>
              <th>\uB178\uC120</th><th>\uC77C\uC815</th><th>\uD2B9\uAC00 \uAE08\uC561</th><th>\uC608\uC57D</th>
            </tr>
            {focus_rows_html}
          </table>
        </section>
        """

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PTIS \uc624\ub298\uc758 \ud2b9\uac00</title>
<script src="https://t1.kakaocdn.net/kakao_js_sdk/2.7.2/kakao.min.js"></script>
<style>
  body {{ font-family: 'Malgun Gothic', sans-serif; padding: 20px; max-width: 800px; margin: 0 auto; background:#f7f8fa; }}
  h2 {{ color: #1a73e8; }}
  table {{ border-collapse: collapse; width: 100%; background:white; }}
  th {{ background-color: #1a73e8; color: white; padding: 10px; }}
  td {{ padding: 10px; text-align: center; border-bottom: 1px solid #eee; }}
  .sub {{ font-size: 12px; color: gray; }}
  .price {{ color: #d93025; font-weight: bold; }}
  .badge {{
    display:inline-block; font-size: 11px; color:#d93025; background:#ffe4e1;
    padding: 2px 6px; border-radius: 4px; margin-top: 4px;
  }}
  .grade {{
    display:inline-block; font-size: 11px; font-weight: bold;
    padding: 2px 7px; border-radius: 10px; margin-top: 5px;
  }}
  .grade-super {{ color:#b3261e; background:#fce8e6; }}
  .grade-good  {{ color:#b06000; background:#fef7e0; }}
  .grade-ok    {{ color:#1e6b3a; background:#e6f4ea; }}
  .alt {{ margin-top: 6px; font-size: 12px; }}
  .alt summary {{
    cursor: pointer; color: #1a73e8; list-style: none;
    display: inline-block; padding: 2px 6px;
    border: 1px solid #d2e3fc; border-radius: 4px; background: #f0f6ff;
  }}
  .alt summary::-webkit-details-marker {{ display: none; }}
  .alt ul {{
    list-style: none; padding: 6px 0 0 0; margin: 0;
    color: #5f6368; text-align: center;
  }}
  .alt li {{ padding: 2px 0; }}
  .route-box {{
    margin-bottom: 24px; padding: 14px; border: 2px solid #1a73e8;
    border-radius: 10px; background: #e8f0fe;
  }}
  .route-box h2 {{ color: #174ea6; margin-top: 0; }}
  .route-label {{ color: #5f6368; font-size: 13px; margin-top: -8px; }}
  .focus-box {{
    margin-bottom: 24px; padding: 14px; border: 2px solid #f9ab00;
    border-radius: 10px; background: #fff8e1;
  }}
  .focus-box h2 {{ color: #b06000; margin-top: 0; }}
  .focus-label {{ color: #5f6368; font-size: 13px; margin-top: -8px; }}
  #shareBtn {{
    display: inline-block; margin-bottom: 16px; padding: 10px 16px;
    background-color: #FEE500; color: #191919; border: none; border-radius: 6px;
    font-weight: bold; cursor: pointer; font-size: 15px;
  }}
</style>
</head>
<body>
  {route_watch_section}
  {focus_section}
  <h2>\U0001f4ca \uc624\ub298\uc758 \uc9c1\ud56d \ud2b9\uac00 ({len(deals)}\uac74)</h2>
  <button id="shareBtn">💬 카카오톡으로 공유하기</button>
  <table>
    <tr>
      <th>노선</th><th>일정</th><th>특가 금액</th><th>예약</th>
    </tr>
    {rows_html}
  </table>

  <script>
    Kakao.init('{js_key}');
    document.getElementById('shareBtn').addEventListener('click', function() {{
      Kakao.Share.sendDefault({{
        objectType: 'feed',
        content: {{
          title: '\u2708\ufe0f \uc624\ub298\uc758 \ud2b9\uac00 \ud56d\uacf5\uad8c ({len(deals)}\uac74)',
          description: '\ucd5c\uadfc \uac80\uc0c9 \ud2b9\uac00 \ub9ac\ud3ec\ud2b8 \xb7 \uc774\uc6d4 \uac00\uaca9\uc740 \uc7ac\ud655\uc778 \ud544\uc694',
          imageUrl: 'https://developers.kakao.com/assets/img/about/logos/kakaolink/kakaolink_btn_medium.png',
          link: {{
            mobileWebUrl: window.location.href,
            webUrl: window.location.href
          }}
        }},
        buttons: [
          {{
            title: '전체 특가 보기',
            link: {{
              mobileWebUrl: window.location.href,
              webUrl: window.location.href
            }}
          }}
        ]
      }});
    }});
  </script>
</body>
</html>
"""

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    logging.info(f"🌐 리포트 페이지 생성 완료: {OUTPUT_FILE}")
