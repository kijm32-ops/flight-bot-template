<!-- MANAGED BY AI-HARNESS -->
# Model and Reasoning Policy

목표는 역할별로 다르다.

- `CHAT`: 성공 가능성, 작업 완결성, 사용자 왕복 최소화를 우선한다. 사용량 절약 때문에 필요한 탐색·추론·검증을 생략하지 않는다.
- `WORK / CODEX`: "성공 가능성이 충분한 가장 저렴한 실행 프로필"에서 시작하고, 근거가 있을 때만 한 단계씩 승격한다.

> 모델 이름과 UI 제공 여부는 제품 업데이트로 바뀔 수 있다. 실제 계정에서 선택 가능한 옵션이 이 문서보다 우선한다. 선택 불가능한 모델을 가정하지 말고 아래 fallback을 사용한다.

## 1. Current capability tiers

현재 정책 기준 모델 계층:

- `GPT-5.6 Luna` — 빠르고 경제적인 반복/집중 작업
- `GPT-5.6 Terra` — 일상적인 업무와 일반 코드 수정의 균형형 기본값
- `GPT-5.6 Sol` — 복잡한 코딩, 연구, 전문 업무
- `GPT-6 Astra` — 가장 어려운 코딩, 분석, 미지의 문제 해결용; 사용량 절약을 위해 기본값으로 사용하지 않음

표준 Chat에서는 Work/Codex와 모델 선택지가 다를 수 있다. Chat은 실제 UI에서 제공되는 Chat 모델과 추론 강도를 사용한다.

### Claude catalog (Claude Code)

Claude 구독은 Chat, Cowork, Claude Code가 **하나의 주간 사용 한도를 공유**한다. 따라서 Claude 계열에서는 `CHAT`도 사용량 절약 대상이며 `WORK / CODEX`와 같은 프로필(5절)을 쓴다. 4절의 "Chat profile"과 "completion-first" 전제는 OpenAI 계열 전용이다.

- Claude Code 세션은 `CODEX`, Cowork는 `WORK`, claude.ai 채팅은 `CHAT` 역할이다.
- 계층 번호(1~4)는 **각 계열 안에서의 상대 순위**다(1이 가장 가볍고 저렴하며 4가 가장 강하다). 아래 표는 GPT 모델과 Claude 모델이 동급이라는 뜻이 아니다. 같은 번호를 같은 행에 놓은 것은 라우팅 규칙(점수 구간, 승격·강등, fallback)을 두 계열에 같은 방식으로 적용하기 위한 편의일 뿐이다. 한 계열의 모델을 다른 계열의 모델로 대체하거나 성능을 비교하는 근거로 쓰지 않는다.
- 채팅에서 모델 선택기를 에이전트가 바꿀 수는 없다. 권장 프로필을 안내하고 전환했다고 가정하지 않는다. 확장 사고 끔은 `LOW`, 켬은 `MEDIUM` 이상으로 기록한다.

| 계층 (계열 안의 순위) | GPT | Claude |
|---|---|---|
| 1 | GPT-5.6 Luna | Claude Haiku 4.5 |
| 2 | GPT-5.6 Terra | Claude Sonnet 5.5 |
| 3 | GPT-5.6 Sol | Claude Opus 5.5 |
| 4 | GPT-6 Astra | Claude Fable 5.1 |

- Claude 계열은 5절의 `CAPABILITY` 구간 매핑 대신 **`PHASE`별 분업**으로 권장 프로필을 정한다. 승격·강등 규칙과 fallback 규칙은 계층 번호 기준으로 그대로 적용한다.

  | PHASE | 모델 | 추론 |
  |---|---|---|
  | `PLAN` (설계) | Opus | `CAPABILITY` ≤8 MEDIUM, ≤10 HIGH, 11..12 XHIGH |
  | `EXECUTE` (구현) | Haiku | ≤5 LOW, 6..8 MEDIUM |
  | 그 외 (조사, 판단, 검증) | Sonnet | ≤8 MEDIUM, 9 이상 HIGH |

  예외: `CAPABILITY ≤ 2`이고 `RISK ≤ 1`이면 어느 단계든 Haiku / LOW. `EXECUTE`에서 `RISK ≥ 3` 또는 `CAPABILITY ≥ 9`이면 Sonnet. `RISK == 4`이면 최소 Opus / HIGH. 자세한 운영 방법은 `.ai/CLAUDE_CODE.md`를 따른다.
- `profile` 명령은 `PHASE`를 마지막 인자로 받는다. 생략하면 판단 단계(Sonnet)로 계산한다.
- `Claude Fable 5.1`(계층 4)은 크레딧 구매가 필요하다. 기본 권장에서 제외하며, 사용자가 크레딧 사용을 명시적으로 승인한 뒤 `ESCALATION_COUNT >= 1`로 기록했을 때만 `gate`가 통과시킨다. 승인 없이 추천하거나 선택하지 않는다.
- 사용량 절약 규칙(Claude 전 역할 공통): 가장 저렴한 충분한 모델에서 시작하고, 확인이 필요하면 질문을 한 번에 묶고, 웹 검색·리서치·커넥터는 결론을 바꿀 정보가 필요할 때만 쓰고, 어려운 판단이 끝나면 더 저렴한 모델로 낮추고, 대화가 길어지거나 컨텍스트가 무거워지면 에이전트 판단으로 새 세션에 handoff 한다.
- `MODEL`에는 위 표의 이름 또는 API ID(`claude-haiku-4-5-20251001`, `claude-sonnet-5-5`, `claude-opus-5-5`, `claude-fable-5-1`)를 기록한다. 계열은 `MODEL` 이름으로 자동 판별한다.
- Claude Code의 추론 단계 `low / medium / high / xhigh / max`는 각각 `LOW / MEDIUM / HIGH / XHIGH / MAX`로 기록한다. `XHIGH`와 `MAX`는 `EXTRA_HIGH`와 같은 순위로 비교한다.
- `profile` 명령은 환경변수 `HARNESS_PROVIDER=claude`일 때 Claude 이름으로 권장 프로필을 출력한다. 기본값은 `openai`다.
- 계층 순서(Haiku < Sonnet < Opus < Fable)는 현재 정책의 가정이다. 실제 계정의 모델 구성이 다르면 이 표와 `scripts/`의 카탈로그를 함께 갱신한다.

## 2. Assessment dimensions

모든 항목은 `0..4` 정수로 평가한다.

### COMPLEXITY
- 0: 기계적/정형 작업
- 1: 단순 판단
- 2: 일반적인 구현/분석
- 3: 여러 제약이 얽힌 문제
- 4: 고난도 추론 또는 새로운 문제

### AMBIGUITY
- 0: 입력과 완료조건이 명확
- 1: 작은 해석 필요
- 2: 일부 전제 확인 필요
- 3: 원인/요구사항이 상당히 불명확
- 4: 탐색적 문제, 원인 범위가 넓음

### RISK
- 0: 읽기/분석만
- 1: 쉽게 되돌릴 수 있는 변경
- 2: 일반 소스/설정 변경
- 3: DB/배포/호환성 등 실패 비용이 큼
- 4: 운영 데이터, 보안, 파괴적 변경 등 매우 높은 위험

### SCOPE
- 0: 한 문장/한 파일 수준
- 1: 소수 파일
- 2: 한 컴포넌트/모듈
- 3: 여러 컴포넌트/도구
- 4: 저장소/업무 전반

### WORKLOAD
- 0: 매우 짧음
- 1: 짧음
- 2: 보통
- 3: 큼
- 4: 매우 큼/반복량 많음

`WORKLOAD`와 `SCOPE`는 사용량을 예측하는 값이다. 작업량이 크다는 이유만으로 더 강한 모델을 선택하지 않는다.

## 3. Derived scores

```text
CAPABILITY_SCORE = COMPLEXITY + AMBIGUITY + RISK    # 0..12
USAGE_SCORE      = SCOPE + WORKLOAD                 # 0..8
```

예상 사용량:

- 0..2  -> `LOW`
- 3..5  -> `MEDIUM`
- 6..7  -> `HIGH`
- 8     -> `VERY_HIGH`

도구 호출이 많거나 긴 컨텍스트/대형 파일을 반복해서 읽어야 하면 예상 사용량을 한 단계 올릴 수 있다.

## 4. Chat profile

표준 Chat에서는 실제 계정에 표시되는 모델을 사용한다. GPT-5.6 Sol을 사용할 수 있는 환경의 기본 매핑은 다음과 같다.

- CAPABILITY 0..2 -> `GPT-5.6 Sol / INSTANT`
- CAPABILITY 3..7 -> `GPT-5.6 Sol / MEDIUM`
- CAPABILITY 8..12 -> `GPT-5.6 Sol / HIGH`

Chat은 설계/판단/검토뿐 아니라 현재 제공된 도구로 안전하게 완결할 수 있는 실행까지 담당할 수 있다. 저장소 수정이 포함됐다는 이유만으로 `CODEX`로 전환하지 않는다.

Chat에서 `EXPECTED_USAGE`는 관찰값이다. 사용량이 높다는 이유만으로 필요한 사고를 줄이거나 작업을 중단하지 않는다. 로컬 저장소 전체 탐색, 터미널, build/test/migration 등 현재 Chat에 없는 실행 능력이 핵심일 때만 `CODEX` 전환을 우선한다.

## 5. Work / Codex profile

Codex에서는 모든 모델 계층(Astra 포함)과 모든 추론 단계가 열려 있다. 그래서 `PHASE`와 중요도로 분업하며, **Astra는 중요한 설계 부분에만 아주 조금** 쓴다. 나머지는 계층을 내려서 쓴다.

| 하는 일 | 모델 | 추론 |
|---|---|---|
| 중요한 설계 (`PLAN`이고 `CAPABILITY ≥ 9` 또는 `RISK ≥ 3`) | Astra | MEDIUM, `CAPABILITY ≥ 11`이면 HIGH |
| 일반 설계 (`PLAN`) | Sol | MEDIUM |
| 중요한 판단 (조사·검증 등에서 `CAPABILITY ≥ 6` 또는 `RISK ≥ 3`) | Sol | MEDIUM, `CAPABILITY ≥ 9`이면 HIGH |
| 일반 판단 (그 외 조사·검증) | Terra | MEDIUM |
| 구현, 생산적인 작업 (`EXECUTE`) | Luna | `CAPABILITY ≤ 5` LOW, 6..8 MEDIUM |

예외:

- `CAPABILITY ≤ 2`이고 `RISK ≤ 1`이면 어느 단계든 Luna / LOW.
- `EXECUTE`에서 `RISK ≥ 3` 또는 `CAPABILITY ≥ 9`이면 Luna 대신 Terra (9 이상은 HIGH).
- `RISK == 4`이면 최소 Sol / HIGH.
- `profile` 명령에서 `PHASE`를 생략하면 판단 단계로 계산한다. 판단 단계에서는 Astra를 쓰지 않는다.

추가 규칙:

- Astra는 설계의 중요한 부분에만 쓰고, 설계가 확정되면 바로 아래 계층으로 내린다.
- Astra가 실제 계정에 없으면 `GPT-5.6 Sol / HIGH`로 fallback하고 그 사실을 기록한다.
- Luna/Terra가 없는 환경에서는 사용 가능한 가장 가까운 상위 모델을 선택하되 추론 강도를 불필요하게 높이지 않는다.
- `FAST_MODE` 기본값은 `OFF`다. 지연시간이 중요하고 추가 사용량을 감수할 이유가 있을 때만 켠다.

## 6. Escalation policy

실패했다고 즉시 최고 모델로 이동하지 않는다.

`gate`는 작업을 멈추는 일을 최소화한다. 권장 프로필과 다른 선택(낮은 모델, 높은 모델, 추론 단계, 예상 사용량, 카탈로그에 없는 모델)은 **경고만 하고 통과**한다. 다음 경우에만 멈춘다.

- `SESSION_STATE.md` 필드가 없거나 `<REQUIRED:...>`로 비어 있음, 값이 잘못됨
- 중앙 관리 파일 누락 또는 관리 헤더 없음
- 역할 불일치, `PROFILE_STATUS`가 `READY`가 아님
- 크레딧 구매가 필요한 모델(Claude Fable)을 승인 기록 없이 사용

환경변수 `HARNESS_STRICT=1`을 지정하면 프로필 불일치도 오류로 취급한다. CI나 calibration처럼 엄격한 검사가 필요할 때만 쓴다.

CHAT에서는 실패 횟수 자체를 승격 근거로 사용하지 않는다. 가설이 기각된 경우에는 먼저 다른 가설이나 실행 경로로 전환하고, 추론 부족이 반복 실패의 원인이라는 근거가 있을 때만 reasoning/model을 승격한다.

순서:

1. 누락된 파일, 잘못된 전제, 권한, 환경, 로그 등 `context problem`인지 먼저 확인한다.
2. context 문제면 모델을 올리지 말고 context를 보강한다.
3. 추론 부족이 원인일 때만 현재 모델의 reasoning을 한 단계 올린다.
4. 같은 원인의 검증 실패가 계속되면 모델을 한 단계 올리고 reasoning은 `MEDIUM`부터 다시 시작할 수 있다.
5. Astra는 최종 고난도 승격으로 사용한다.
6. `AI_HARNESS.md`의 자동 수리 루프 한도를 넘기지 않는다.

권장 모델 승격 순서:

```text
Luna -> Terra -> Sol -> Astra
```

## 7. Downgrade policy

작업의 어려운 부분이 끝나고 이후 단계가 반복/정형 작업이면 더 저렴한 모델로 낮출 수 있다.

예:

- 설계 확정 후 대량 분류/추출 -> Luna
- 복잡한 원인 분석 후 명확한 소규모 수정 -> Terra
- 긴 검증 로그의 단순 수집 -> Luna/Terra

한 세션 전체를 처음 선택한 최고 모델로 고정하지 않는다.

## 8. Mandatory execution profile

실행 전에 `SESSION_STATE.md`에 최소 다음을 기록한다.

```text
ROLE: CHAT|WORK|CODEX
MODEL: 실제 선택한 모델
REASONING: 실제 선택한 추론 단계 또는 관찰 불가 시 N/A
EXPECTED_USAGE: LOW|MEDIUM|HIGH|VERY_HIGH
FAST_MODE: ON|OFF
PROFILE_STATUS: READY|BLOCKED
PROFILE_FALLBACK: NONE|MODEL_UNAVAILABLE|PLAN_LIMIT|ENVIRONMENT_LIMIT
COMPLEXITY: 0..4
AMBIGUITY: 0..4
RISK: 0..4
SCOPE: 0..4
WORKLOAD: 0..4
ESCALATION_COUNT: 0..
```

권장 모델을 선택할 수 없어 fallback을 사용하면 `PROFILE_FALLBACK`에 이유를 기록한다.

현재 제품/UI/API가 실제 추론 강도를 노출하지 않아 값을 확인할 수 없으면 추측하지 않는다. 이 경우에만 `REASONING: N/A`와 `PROFILE_FALLBACK: ENVIRONMENT_LIMIT`를 함께 기록할 수 있다. `N/A`를 사용하면 Harness는 reasoning rank 비교를 경고와 함께 건너뛴다.

`REASONING: N/A`는 선택 모델이 권장 모델과 같거나 더 높은 경우에만 허용한다. 권장 모델보다 낮은 모델을 사용하면서 reasoning 수준으로 capability floor를 보완해야 하는 fallback에는 `N/A`를 사용할 수 없다.

실제 UI에서 모델을 변경할 수 없는 에이전트는 스스로 변경했다고 주장하지 않는다. 권장 프로필과 현재 프로필이 다르면 차이를 기록하고, 역할 또는 모델 변경이 필요한 지점에서 handoff 한다.

## 9. Executor and unlisted models

`SESSION_STATE.md`에는 실행자(제품/도구), 역할(`ROLE`), 모델(`MODEL`)을 각각 구분해서 기록한다. 셋을 하나로 섞어 쓰지 않는다.

- `EXECUTOR`(선택): 제품/도구 이름. 예: `Codex`, `Claude Code`. `Claude Code`는 제품 이름이고 `CODEX`는 역할 이름이므로 같은 개념이 아니다. `gate`는 이 값을 검사하지 않는다.
- `MODEL`에는 그 세션에서 실제로 확인된 모델명만 기록한다. 추정하거나 이전 세션 기록을 재사용하지 않는다. `REASONING`도 실제 선택값을 확인할 수 있을 때만 쓰고, 아니면 `N/A`로 기록한다.
- 모델이 위 카탈로그(GPT, Claude)에 없으면 이름을 그대로 기록한다. `gate`는 모델 비교를 건너뛰고 경고만 하며, 이 이유만으로 작업을 멈추지 않는다. 별도의 `MODEL_TIER` 표시는 쓰지 않는다. 이전 문서의 `MODEL_TIER: EXTERNAL|UNMAPPED` 표기는 더 이상 필요하지 않다.
- 카탈로그에 없는 모델에는 6절의 승격 경로를 적용하지 않는다. 같은 원인으로 반복 실패하면 `AI_HARNESS.md` 8절의 자동 수리 루프 한도에 따라 중단하고 사용자에게 보고한다.
- 어떤 모델도 근거 없이 다른 계열의 모델과 동급으로 취급하지 않는다. 동급 관계가 필요하면 이 문서에 그 관계를 명시한 결정을 추가한 뒤에만 쓴다. Claude catalog의 계층 번호는 이런 동급 결정이 아니다.
- 역할, 환경, 안전, 검증 게이트는 모델 등록 여부와 무관하게 동일하게 적용한다. 대상은 `.ai/ROLE_POLICY.md`, `.ai/ENVIRONMENTS.md`, `AI_HARNESS.md`의 위험 분류와 실행 게이트, `.ai/SAFETY.md`, `.ai/VALIDATION.md`다.
