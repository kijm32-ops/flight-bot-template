import smtplib
import logging
import os
import json
import requests
from typing import List, Set, Tuple
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config import (
    GMAIL_USER, GMAIL_PASSWORD, KAKAO_CARD_IMAGE_URL, KAKAO_CLIENT_SECRET,
    KAKAO_REST_API_KEY, KAKAO_TOKEN_ENCRYPTION_KEY, PAGE_URL,
)
from kakao_auth import KakaoAuthError, load_refresh_token, store_refresh_token
from models import Flight


# ─────────────────────────────────────────────────────────────
# 카카오톡 카드 대표 이미지
#
# 카카오 서버가 이 URL을 직접 가져가므로 로그인 없이 열리는 공개 주소여야 한다.
# 이미지를 교체할 때는 파일명의 v1 → v2 처럼 버전을 올릴 것.
# 카카오가 URL 단위로 이미지를 캐싱해서, 같은 이름으로 덮어쓰면 옛 이미지가 계속 나온다.
# ─────────────────────────────────────────────────────────────
KAKAO_CARD_IMAGE_WIDTH = 800
KAKAO_CARD_IMAGE_HEIGHT = 400


def _short_name(deal: Flight) -> str:
    """
    destination_name에 붙은 'ICN 출발 ...' 경고 문구를 떼어낸 짧은 도시명.
    카카오톡 요약처럼 길이가 빠듯한 곳에서 사용한다.
    """
    return deal.destination_name.split(" ⚠️ ")[0]


def _grade_badge_html(deal: Flight) -> str:
    """메일용 등급 배지 (인라인 스타일 — 메일 클라이언트는 <style> 태그를 자주 무시함)"""
    if not deal.value_grade or deal.value_grade == "unknown":
        return ""
    colors = {
        "🔥 초특가": ("#b3261e", "#fce8e6"),
        "✨ 특가": ("#b06000", "#fef7e0"),
        "👍 괜찮음": ("#1e6b3a", "#e6f4ea"),
    }
    fg, bg = colors.get(deal.value_grade, ("#1e6b3a", "#e6f4ea"))
    return (
        f"<br><span style='display:inline-block;font-size:11px;font-weight:bold;"
        f"color:{fg};background:{bg};padding:2px 7px;border-radius:10px;"
        f"margin-top:5px;'>{deal.value_grade}</span>"
    )


def _alt_dates_html(deal: Flight) -> str:
    """메일용 대안 날짜 목록 (<details>는 메일에서 동작하지 않으므로 평문으로 펼쳐서 표시)"""
    if not deal.alt_dates:
        return ""
    lines = "".join(
        f"<div>{depart} ~ {ret} · {price:,}원</div>"
        for depart, ret, price in deal.alt_dates
    )
    return (
        f"<div style='margin-top:6px;font-size:11px;color:#5f6368;"
        f"border-top:1px dashed #ddd;padding-top:5px;'>"
        f"<span style='color:#1a73e8;'>다른 날짜</span>{lines}</div>"
    )


def _send_raw_email(subject: str, html_content: str) -> None:
    """공통 메일 발송 로직 (일반 리포트, 경고 메일 모두 사용)"""
    if not GMAIL_USER or not GMAIL_PASSWORD:
        logging.error("❌ 메일 계정 환경변수가 없습니다.")
        return

    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = GMAIL_USER
    msg['To'] = GMAIL_USER
    msg.attach(MIMEText(html_content, 'html'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.sendmail(GMAIL_USER, GMAIL_USER, msg.as_string())
        logging.info(f"📬 메일 발송 성공: {subject}")
    except Exception as e:
        logging.error(f"❌ 메일 발송 에러: {e}")


def send_warning_email(subject: str, body_text: str) -> None:
    """시스템 경고용 간단 메일 (카카오 발송 실패, API 한도 임박 등)"""
    html_content = f"""
    <html><body style='font-family: Malgun Gothic, sans-serif; padding: 20px;'>
        <h3 style='color: #d93025;'>⚠️ PTIS 시스템 경고</h3>
        <p>{body_text}</p>
    </body></html>
    """
    _send_raw_email(subject, html_content)


def send_email(deals: List[Flight], low_price_keys: Set[Tuple[str, str, str, str]] = None) -> None:
    low_price_keys = low_price_keys or set()

    if not deals:
        html_content = "<h3>📢 오늘의 특가 항공권 내역</h3><p>현재 조건에 부합하는 특가 항공권이 없습니다.</p>"
    else:
        html_content = """
        <html><body style='font-family: Malgun Gothic, sans-serif; padding: 20px;'>
            <h2 style='color: #1a73e8;'>\U0001f4ca \uc624\ub298\uc758 \uc9c1\ud56d \ud2b9\uac00</h2>
            <p style='font-size:12px;color:#5f6368;margin-top:-8px;'>
                \ub4f1\uae09\uc740 \uc774\ubc88 \ub9ac\ud3ec\ud2b8\uc758 \ud45c\uc2dc \uc21c\uc704 \uae30\uc900\uc785\ub2c8\ub2e4. \uc624\ub298 \uac80\uc0c9 \uacb0\uacfc\ub97c \uc6b0\uc120 \ud45c\uc2dc\ud569\ub2c8\ub2e4.
            </p>
            <table border='0' style='border-collapse: collapse; width: 100%; max-width: 750px;'>
                <tr style='background-color: #1a73e8; color: white;'>
                    <th style='padding: 10px;'>노선</th>
                    <th style='padding: 10px;'>일정</th>
                    <th style='padding: 10px;'>특가 금액</th>
                    <th style='padding: 10px;'>예약</th>
                </tr>
        """
        for deal in deals:
            trip_nights = (deal.return_date - deal.depart_date).days
            dedup_key = (deal.origin, deal.destination, str(deal.depart_date), str(deal.return_date))
            badge = (
                "<br><span style='font-size:11px;color:#d93025;background:#ffe4e1;"
                "padding:2px 6px;border-radius:4px;'>🔥 30일 최저가</span>"
                if dedup_key in low_price_keys else ""
            )
            grade_badge = _grade_badge_html(deal)
            alt_html = _alt_dates_html(deal)
            carryover_html = f"<br><small>{deal.carryover_label}</small>" if deal.is_carryover else ""

            html_content += f"""
                <tr style='border-bottom: 1px solid #eee; text-align: center;'>
                    <td style='padding: 10px; font-weight: bold;'>
                        {deal.origin} ➔ {deal.destination_name}
                        <br><span style='font-size: 12px; color: gray;'>({deal.destination_country})</span>
                        {grade_badge}
                    </td>
                    <td style='padding: 10px;'>
                        {deal.depart_date} ~ {deal.return_date}
                        <br><span style='font-size: 12px; color: gray;'>({trip_nights}박 {trip_nights+1}일)</span>
                        {alt_html}
                    </td>
                    <td style='padding: 10px; color: #d93025; font-weight: bold;'>
                        {deal.price:,}원<br>
                        <span style='font-size: 12px; color: gray;'>(-{deal.discount_percentage}%)</span>
                        {badge}
                    {carryover_html}
                    </td>
                    <td style='padding: 10px;'><a href='{deal.booking_link}' target='_blank'>확인</a></td>
                </tr>
            """
        html_content += "</table></body></html>"

    _send_raw_email(f"\u2708\ufe0f [PTIS] \uc624\ub298\uc758 \ud2b9\uac00 \ub9ac\ud3ec\ud2b8 ({len(deals)}\uac74)", html_content)


def refresh_kakao_access_token() -> str:
    """Refresh the access token and persist an optional Kakao token rotation first."""
    if not KAKAO_REST_API_KEY or not KAKAO_TOKEN_ENCRYPTION_KEY:
        raise KakaoAuthError("Kakao REST API key and encryption key are required.")

    refresh_token = load_refresh_token(KAKAO_TOKEN_ENCRYPTION_KEY)
    if not refresh_token:
        raise KakaoAuthError("Run setup_kakao.py before enabling Kakao delivery.")

    request_data = {
        "grant_type": "refresh_token",
        "client_id": KAKAO_REST_API_KEY,
        "refresh_token": refresh_token,
    }
    if KAKAO_CLIENT_SECRET:
        request_data["client_secret"] = KAKAO_CLIENT_SECRET

    token_res = requests.post(
        "https://kauth.kakao.com/oauth/token", data=request_data, timeout=15
    )
    token_res.raise_for_status()
    token_payload = token_res.json()
    access_token = token_payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise KakaoAuthError("Kakao token response did not include an access token.")

    rotated_token = token_payload.get("refresh_token")
    if rotated_token is not None:
        if not isinstance(rotated_token, str) or not rotated_token:
            raise KakaoAuthError("Kakao returned an invalid rotated refresh token.")
        store_refresh_token(rotated_token, KAKAO_TOKEN_ENCRYPTION_KEY)
        logging.info("Kakao refresh token rotation persisted.")
    return access_token


def send_kakao_message(
    deals: List[Flight],
    focus_deals: List[Flight] = None,
    route_watch_deals: List[Flight] = None,
) -> bool:
    """
    카카오톡 '나에게 보내기'로 특가 요약 알림 발송.
    성공 여부를 True/False로 반환한다 (연속 실패 감지에 사용).
    """
    focus_deals = focus_deals or []
    route_watch_deals = route_watch_deals or []
    if not deals and not focus_deals and not route_watch_deals:
        return True  # 보낼 게 없는 것은 실패가 아님

    if not PAGE_URL or not KAKAO_CARD_IMAGE_URL:
        logging.error("Kakao delivery needs GitHub repository context or PTIS URL overrides.")
        return False

    # 1단계: Refresh Token으로 새 Access Token 발급
    try:
        access_token = refresh_kakao_access_token()
    except Exception as e:
        logging.error(f"❌ 카카오 Access Token 갱신 실패: {e}")
        return False

    # 2단계: Route Watch -> Region Focus -> Discovery 순으로 최대 3건 요약한다.
    summary_lines = []

    for d in route_watch_deals[:1]:
        nights = (d.return_date - d.depart_date).days
        summary_lines.append(
            f"\U0001F4CD {d.origin}\u2192{_short_name(d)} {d.price:,}\uC6D0 "
            f"{d.depart_date.strftime('%m/%d')} {nights}\uBC15{nights+1}\uC77C"
        )

    remaining = max(0, 3 - len(summary_lines))
    for d in focus_deals[:remaining]:
        nights = (d.return_date - d.depart_date).days
        summary_lines.append(
            f"\U0001F3AF {d.origin}\u2192{_short_name(d)} {d.price:,}\uC6D0 "
            f"{d.depart_date.strftime('%m/%d')} {nights}\uBC15{nights+1}\uC77C"
        )

    remaining = max(0, 3 - len(summary_lines))
    for d in deals[:remaining]:
        nights = (d.return_date - d.depart_date).days
        grade = d.value_grade.split(" ")[0] if d.value_grade and d.value_grade != "unknown" else ""
        summary_lines.append(
            f"\U0001F50E {grade}{d.origin}\u2192{_short_name(d)} {d.price:,}\uC6D0 "
            f"{d.carryover_label} "
            f"{d.depart_date.strftime('%m/%d')} {nights}\uBC15{nights+1}\uC77C"
        )

    if route_watch_deals:
        title = (
            f"\u2708\uFE0F \uB178\uC120\uAC10\uC2DC {len(route_watch_deals)}\uAC74"
            f" \u00B7 \uAD00\uC2EC\uAC80\uC0C9 {len(focus_deals)}\uAC74"
            f" \u00B7 \uD2B9\uAC00 {len(deals)}\uAC74"
        )
    elif focus_deals:
        title = (
            f"\u2708\uFE0F \uAD00\uC2EC\uAC80\uC0C9 {len(focus_deals)}\uAC74"
            f" \u00B7 \uD2B9\uAC00 {len(deals)}\uAC74"
        )
    else:
        title = (
            f"\u2708\uFE0F \uC624\uB298\uC758 \uD2B9\uAC00 \uD56D\uACF5\uAD8C "
            f"{len(deals)}\uAC74 \uBC1C\uACAC!"
        )

    description_text = "\n".join(summary_lines)

    template_object = {
        "object_type": "feed",
        "content": {
            "title": title,
            "description": description_text,
            "image_url": KAKAO_CARD_IMAGE_URL,
            "image_width": KAKAO_CARD_IMAGE_WIDTH,
            "image_height": KAKAO_CARD_IMAGE_HEIGHT,
            "link": {
                "web_url": PAGE_URL,
                "mobile_web_url": PAGE_URL,
            },
        },
        "buttons": [
            {
                "title": "전체 특가 보기",
                "link": {
                    "web_url": PAGE_URL,
                    "mobile_web_url": PAGE_URL,
                },
            }
        ],
    }

    # 3단계: 나에게 보내기 API 호출
    try:
        send_res = requests.post(
            "https://kapi.kakao.com/v2/api/talk/memo/default/send",
            headers={"Authorization": f"Bearer {access_token}"},
            data={"template_object": json.dumps(template_object)},
            timeout=15,
        )
        send_res.raise_for_status()
        if send_res.json().get("result_code") != 0:
            logging.error("Kakao message API did not return result_code 0.")
            return False
        logging.info("💬 카카오톡 알림 발송 성공!")
        return True
    except Exception as e:
        logging.error(f"❌ 카카오톡 발송 에러: {e}")
        return False
