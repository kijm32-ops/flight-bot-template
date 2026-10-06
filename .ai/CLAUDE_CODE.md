<!-- MANAGED BY AI-HARNESS -->
# Claude Code Operating Rules

Claude Code 세션은 `ROLE: CODEX`이며 계열은 Claude다. 프로필 계산에는 `HARNESS_PROVIDER=claude`를 사용한다.

이 파일은 `CLAUDE.md`를 통해 세션 시작 시 자동으로 읽힌다. 사용자가 하네스를 언급하지 않아도 `AGENTS.md`의 자동 부트스트랩을 따라, 첫 파일 수정이나 명령 실행 전에 `SESSION_STATE.md`의 프로필을 확정하고 `gate`를 실행한다.

Chat, Cowork, Claude Code는 **하나의 주간 사용 한도를 공유**한다. 모든 단계에서 사용량을 절약하되, 필요한 사고와 검증은 생략하지 않는다.

## Phase routing

`SESSION_STATE.md`의 `PHASE`에 따라 모델을 나눈다.

| PHASE | 하는 일 | 모델 |
|---|---|---|
| `PLAN` | 설계, 아키텍처, 트레이드오프 판단 | Opus |
| `DISCOVER` `ROUTE` `VALIDATE` `BLOCKED` `COMPLETE` | 조사, 분석, 검증, 리뷰, 판단 | Sonnet |
| `EXECUTE` | 확정된 설계의 코드 구현 | Haiku |

예외:

- 사소한 작업(점수 합 2 이하, `RISK` 1 이하)은 어느 단계든 Haiku로 시작한다.
- `EXECUTE`라도 `RISK >= 3`(DB, 배포 등) 또는 점수 합 9 이상이면 Sonnet을 쓴다.
- `RISK == 4`이면 최소 Opus / HIGH다.
- Fable은 크레딧이 필요하다. 사용자가 크레딧 사용을 명시적으로 승인하기 전에는 선택하거나 권장하지 않는다. 승인받으면 `ESCALATION_COUNT`를 1 이상으로 기록한다.

권장 프로필은 이렇게 계산한다.

```powershell
$env:HARNESS_PROVIDER = 'claude'
.\ai.ps1 profile . CODEX <C> <A> <R> <S> <W> <PHASE>
```

```bash
HARNESS_PROVIDER=claude ./ai profile . CODEX <C> <A> <R> <S> <W> <PHASE>
```

## How to apply the routing

세션 도중 에이전트가 자기 모델을 바꿀 수는 없다. 다음 두 방법을 쓴다.

1. **서브에이전트 위임**: 설계는 `harness-architect`(Opus), 구현은 `harness-coder`(Haiku)에 맡긴다. 둘 다 `.claude/agents/`에 배포된다.
2. **모델 전환 안내**: 사용자가 `/model`로 바꾸도록 권장 모델을 안내한다. 전환했다고 가정하지 않는다.

위임 기준:

- 서브에이전트는 컨텍스트를 처음부터 다시 읽는다. 그래서 **여러 파일에 걸치거나 스펙이 명확한 덩어리**에만 위임한다.
- 한두 줄 수정처럼 작은 작업은 위임하지 말고 현재 세션에서 처리한다.
- 위임할 때는 목표, 대상 파일, 확정된 설계, 변경 금지 범위, 검증 방법을 한 번에 전달한다.
- 설계 결과(spec)는 `SESSION_STATE.md`나 `.ai/DECISIONS.md`에 남기고, 구현 단계는 그 spec만 보고 진행한다.

## Recording MODEL while delegating

`SESSION_STATE.md`의 `MODEL`과 `REASONING`에는 **그 단계를 실제로 수행하는 모델**을 기록한다. 서브에이전트에 위임하는 동안에는 서브에이전트의 모델이다. `gate`는 이 값을 `PHASE`의 권장 프로필과 비교한다.

- `gate`는 권장과 다른 모델을 경고만 하고 통과시킨다. 작업은 멈추지 않지만 경고는 사용량이 새고 있다는 신호다.
- `EXECUTE` 단계를 Opus로 직접 하는 것처럼 권장보다 두 계층 이상 높으면 경고가 나온다. Haiku에 위임하거나 `/model`을 바꾼다.
- Fable만 예외로, 크레딧 사용 승인과 `ESCALATION_COUNT` 기록이 없으면 `gate`가 멈춘다.
- 단계가 바뀔 때마다 `PHASE`, `MODEL`, `REASONING`을 함께 갱신한다.

## Escalation

- 구현이 반복 실패하면 먼저 context 문제(누락된 파일, 잘못된 전제)인지 확인한다.
- 그 다음에 Haiku → Sonnet → Opus 순서로 한 단계씩만 올리고 `ESCALATION_COUNT`를 갱신한다.
- 구현 중 설계 결함이 드러나면 억지로 진행하지 말고 `BLOCKED_BY_DESIGN`으로 기록해 `PLAN`으로 돌아간다.

## Usage economy

- 확인이 필요한 질문은 한 번에 묶어서 한다.
- 웹 검색, 리서치, 커넥터는 결론을 바꿀 정보가 필요할 때만 쓴다.
- 이미 통과한 검증은 상태가 바뀌기 전까지 반복하지 않는다.
- 어려운 단계가 끝나면 더 저렴한 모델로 낮춘다.
- 대화가 길어지거나 컨텍스트가 무거워지면 `SESSION_STATE.md`를 갱신한 뒤 새 세션으로 handoff 한다. 시점은 에이전트가 판단한다.
