<!-- MANAGED BY AI-HARNESS -->
# Execution Safety

## 자동 실행 가능

- 파일 읽기/검색
- lint / typecheck / 정적 분석
- 테스트 / 빌드
- git status / diff
- 로컬 임시 산출물 생성

## 변경 후 검증 필수

- 소스 코드 수정
- 설정 수정
- dependency 변경
- migration 파일 생성
- 생성 코드 갱신

## 사용자 승인 필요

다음 작업은 실행 전에 구체적인 대상과 영향을 설명하고 승인을 받는다.

- 운영환경 배포
- 운영 DB 쓰기/스키마 변경
- 데이터 삭제 또는 대량 수정
- destructive migration
- `rm -rf` 등 복구가 어려운 삭제
- `git push --force`, history rewrite
- credential/secret rotation
- 외부 서비스에 메시지 전송
- 유료 API/리소스의 비정상적 대량 사용 가능 작업

## Placeholder Gate

`<REQUIRED:...>` 형식의 값이 실행 대상 파일 또는 명령에 남아 있으면 해당 작업을 중단한다.
