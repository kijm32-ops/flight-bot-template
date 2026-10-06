# Architecture Decisions

중요하고 반복해서 재논의할 가능성이 높은 결정만 기록한다.

## ADR-001 ai-harness 적용

Status: ACCEPTED (2026-10-06)

Decision:
- 공통 AI 작업 규칙을 `kijm32-ops/ai-harness`에서 중앙 관리하고, 이 프로젝트에는 배포본과 프로젝트 고유 파일만 둔다.

Reason:
- 여러 프로젝트의 규칙을 한 곳에서 갱신하고, 모델/추론 사용량 라우팅과 안전 게이트를 같은 방식으로 적용하기 위해서다.

Do not:
- `MANAGED BY AI-HARNESS` 헤더가 붙은 파일(`AGENTS.md`, `AI_HARNESS.md`, `.ai/SAFETY.md`, `.ai/ROLE_POLICY.md`, `.ai/MODEL_POLICY.md`, `.ai/ENVIRONMENTS.md`, `.ai/CLAUDE_CODE.md`, `.claude/agents/*`)을 이 저장소에서 직접 수정하지 않는다. 다음 `sync`에서 덮어써진다. 변경이 필요하면 ai-harness 저장소에서 고친다.
