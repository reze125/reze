---
name: protocol
description: "에이전트 간 통신 프로토콜. A2A, MCP 표준."
type: meta-skill
triggers:
  - 에이전트
  - a2a
  - mcp
  - 프로토콜
  - agent
  - protocol
  - communication
health_checks: []
fix_actions: []
---

# Protocol Meta-Skill

에이전트 간 통신 및 외부 시스템 연동 프로토콜.

## 핵심 워크플로우

### A2A (Agent-to-Agent)
1. 다른 에이전트와 태스크 위임
2. 결과 수신 및 검증
3. 에스컬레이션 처리

### MCP (Model Context Protocol)
1. 표준 컨텍스트 전달
2. 도구 호출 규격
3. 응답 형식 표준화

### 외부 연동
1. Webhook 수신
2. API 호출
3. 이벤트 트리거

## 보안
- 인증 토큰 검증
- Rate limiting
- 입력 검증
