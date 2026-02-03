---
name: dependency-audit
description: 의존성 보안 감사 — npm audit, pip check
type: security
triggers:
  - dependency
  - 의존성
  - audit
  - vulnerability
  - 취약점
health_checks: []
fix_actions: []
---
# Dependency Audit

## Commands
```bash
# Python
pip check
pip list --outdated
safety check -r requirements.txt  # (safety 설치 필요)

# Node.js
npm audit
npm outdated
```

## Schedule
- 매주 토요일 03:00
- 취약점 발견 시 Alert

## Severity Levels
- Critical: 즉시 패치
- High: 24시간 내 패치
- Medium: 1주일 내 패치
- Low: 다음 업데이트에 포함

## Actions
1. 취약점 발견
2. 영향 범위 분석
3. 패치/업그레이드
4. 테스트
5. 배포
