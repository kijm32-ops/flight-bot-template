<!-- MANAGED BY AI-HARNESS -->
# Environment Policy

사용자가 세션 시작 문구에서 작업 장소/기기를 말하면 아래 환경 ID로 정규화한다.

## Environment IDs

### HOME_WINDOWS
자연어 예시: `집`, `집이야`, `집 PC`, `집 윈도우`

기본 원칙:
- Windows 사용자 환경
- 중앙 Harness 기본 위치: `~/ai-harness`
- 관리자 권한은 필요할 때만 사용하고 기본적으로 요구하지 않는다.
- 프로젝트 고유 경로는 확인 후 사용한다.

### VPN_WINDOWS
자연어 예시: `VPN`, `VPN이야`, `VPN PC`, `VPN 윈도우`

기본 원칙:
- VPN이 적용된 Windows 제한 환경으로 취급한다.
- 중앙 Harness 기본 위치: `~/ai-harness`
- 관리자 권한을 전제로 하지 않는다.
- 시스템 PATH, 레지스트리, Windows 서비스, 보안 정책을 임의로 변경하지 않는다.
- 설치/네트워크/외부 전송이 필요한 작업은 환경 제약을 먼저 확인한다.
- VPN 내부 시스템 또는 민감 데이터와 관련된 작업은 `.ai/SAFETY.md`를 우선한다.

### MACBOOK
자연어 예시: `노트북`, `맥`, `맥북`, `MacBook`

기본 원칙:
- macOS 사용자 환경
- 중앙 Harness 기본 위치: `~/ai-harness`
- shell은 현재 실제 환경을 확인한다. `zsh`라고 추측하지 않는다.
- Windows 전용 명령을 그대로 사용하지 않는다.

### UNKNOWN
사용자가 환경을 말하지 않았고 현재 도구/프로젝트에서도 확인할 수 없을 때 사용한다.

`UNKNOWN` 자체는 분석 작업을 막지 않는다. 다만 환경에 따라 결과가 달라지는 명령 실행, 설치, 경로 변경, 배포는 환경 확인 전 실행하지 않는다.

## Natural-language session bootstrap

다음과 같은 문구는 Harness 시작 요청으로 취급한다.

- `집이야. 챗 하네스 걸고 시작하자.`
- `VPN이야. 코덱스 하네스 걸고 시작하자.`
- `노트북이야. 워크 하네스 걸고 시작하자.`
- `집이야. 하네스 걸고 시작하자.`

에이전트는 사용자가 PowerShell/Bash 명령이나 0~4 점수를 직접 입력하게 하지 않는 것을 기본값으로 한다.

### 시작 처리 순서

1. 자연어에서 `ENVIRONMENT`를 정규화한다.
2. 역할이 명시되었으면 그대로 `ROLE`을 사용한다.
3. 역할이 생략되었으면 `.ai/ROLE_POLICY.md`로 `CHAT / WORK / CODEX`를 결정한다.
4. 현재 요청을 기준으로 `COMPLEXITY / AMBIGUITY / RISK / SCOPE / WORKLOAD`를 에이전트가 평가한다.
5. `.ai/MODEL_POLICY.md`로 권장 모델/추론/예상 사용량을 계산한다.
6. 프로젝트 파일을 수정할 수 있는 환경이면 `SESSION_STATE.md`를 갱신하고 중앙 Harness CLI의 `verify`/`gate`를 가능한 범위에서 직접 실행한다.
7. 프로젝트 파일을 수정할 수 없는 Chat 환경이면 세션 내 논리 상태로 동일한 프로필을 적용하되, 로컬 `SESSION_STATE.md`가 갱신되었다고 주장하지 않는다.
8. 실제 제품 모델 선택기를 자동 조작할 수 없다면 권장 프로필만 명시하고 전환했다고 주장하지 않는다.

## Role phrases

- `챗`, `Chat`, `CHAT` -> `CHAT`
- `워크`, `Work`, `WORK` -> `WORK`
- `코덱스`, `Codex`, `CODEX` -> `CODEX`

사용자가 역할을 명시하면 그 요청을 우선한다. 단, 요청의 실제 작업이 해당 역할의 안전 경계를 명백히 넘으면 수행하지 말고 적절한 역할로 handoff를 제안한다.
