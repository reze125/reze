---
name: a2a-protocol
description: Agent-to-Agent 프로토콜 — 에이전트 간 통신
type: ops
triggers:
  - a2a
  - agent to agent
  - 에이전트 통신
  - mcp
health_checks: []
fix_actions: []
---
# Agent-to-Agent Protocol

## Concept
에이전트 간 표준화된 통신 프로토콜.
Google의 A2A protocol 또는 MCP 활용.

## Use Cases
1. REZE ↔ 외부 에이전트
2. 멀티 에이전트 협업
3. 태스크 위임

## Message Format
```json
{
  "from": "reze",
  "to": "external-agent",
  "action": "request",
  "payload": {...},
  "metadata": {
    "timestamp": "...",
    "correlation_id": "..."
  }
}
```

## Security
- API Key 인증
- Rate limiting
- Payload validation
