---
name: incident-response
description: 장애 대응 — 에스컬레이션, 복구
type: ops
triggers:
  - incident
  - 장애
  - outage
  - emergency
  - 긴급
health_checks: []
fix_actions: []
---
# Incident Response

## Severity Levels
| Level | Description | Response |
|-------|-------------|----------|
| P0 | 전체 서비스 다운 | 즉시 |
| P1 | 주요 기능 장애 | 1시간 내 |
| P2 | 부분 기능 장애 | 24시간 내 |
| P3 | 마이너 이슈 | 계획된 수정 |

## Response Flow
1. **Detect**: 모니터링/알림
2. **Triage**: 심각도 판정
3. **Respond**: 자동수리 또는 수동
4. **Resolve**: 문제 해결
5. **Review**: 사후 분석

## Automatic Actions (Self-Healing)
- PM2 재시작
- Docker 재시작
- 롤백

## Escalation (LOCK)
- P0: 즉시 Discord 알림
- 3회 자동수리 실패: 수동 개입 요청
