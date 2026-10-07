# Validation

`.github/workflows/validate.yml`은 `flight-bot`과 내용이 같다. 이 저장소에는 `build_template.py`가 없을 수 있어 일부 단계는 적용되지 않을 수 있다. 확인하지 않은 명령은 임의로 작성하지 않는다.

## Pre-check

- `git status`
- placeholder 검사: `<REQUIRED:`

## Backend

- `python -m pip install -r requirements.txt` 와 `pip install pyyaml`
- `python -m py_compile *.py`
- `python -m unittest`

## Frontend

- 없음

## Database

- 없음

## Final

- 워크플로 YAML 파싱 (`validate.yml` 참고)
- `git diff --check`
- `git diff`
- 예상 외 파일 변경 여부 확인
