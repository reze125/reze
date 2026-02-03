---
name: project-mgmt
description: 프로젝트 관리 — 우선순위, 로드맵
type: strategy
triggers:
  - project
  - 프로젝트
  - roadmap
  - 로드맵
  - priority
  - 우선순위
health_checks: []
fix_actions: []
---
# Project Management

## Current Projects
| Project | Status | Priority |
|---------|--------|----------|
| REZE v3.3 | In Progress | P0 |
| AI Tools Lab | Active | P1 |
| QuotePilot | Active | P1 |

## Priority Framework
- P0: 즉시 (장애, 긴급)
- P1: 이번 주
- P2: 이번 달
- P3: 백로그

## Task Queue
REZE 태스크 큐는 priority 기반 FIFO.
```python
ssot.enqueue(task, priority=1)  # 1=높음, 5=낮음
```

## Weekly Planning
- 월: 주간 목표 설정
- 수: 중간 점검
- 금: 주간 리뷰
