# Project

## Purpose

PTIS(Personal Template)의 깨끗한 개인용 템플릿이다. SerpAPI로 할인된 Google Flights 운임을 찾아 GitHub Pages 보고서를 발행하고, 요약을 본인 KakaoTalk "나와의 채팅"으로 보낼 수 있다. 설치본마다 자기 GitHub 저장소, SerpAPI 키, Kakao Developers 앱을 쓴다. 이 저장소는 공개(public)다.

## Architecture

- Frontend: GitHub Pages로 발행되는 정적 보고서
- Backend: Python 스크립트를 GitHub Actions가 실행. 의존성은 `requests`, `tenacity`, `cryptography`
- Database: 없음. JSON 상태 파일

## Important directories

- `.github/workflows/` — 정기 실행, 갱신, 검증, 설정 이슈 처리
- `.ptis/` — 갱신 manifest
- `assets/` — 정적 자원

## Environments

### Development

- 로컬 Python 환경. 설치 상태는 확인하지 않았다.

### Production / Deployment target

- 각 사용자의 GitHub Actions와 GitHub Pages.

## Invariants

- 이 템플릿의 내용은 `flight-bot` 저장소의 `build_template.py`가 `.ptis/update_manifest.json` 기준으로 만든다. 이 저장소로 템플릿이 갱신되는 정확한 경로는 확인하지 않았다. 직접 수정하기 전에 `flight-bot`의 원본과 비교한다.
- Kakao 암호화 키, Kakao Client Secret, 평문 refresh token, API 키를 절대 commit하지 않는다.
- 런타임 상태 파일(`data/state.json`, `data/kakao_auth.json`)을 넣지 않는다.
