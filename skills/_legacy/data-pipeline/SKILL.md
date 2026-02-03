---
name: data-pipeline
description: 데이터 파이프라인 — ETL, 동기화
type: ops
triggers:
  - data pipeline
  - etl
  - sync
  - 동기화
health_checks: []
fix_actions: []
---
# Data Pipeline

## Current Pipelines
| Source | Target | Frequency |
|--------|--------|-----------|
| LemonSqueezy | biz_metrics | 6시간 |
| Signals | Daily Report | 일간 |

## Components
1. **Extract**: 데이터 소스에서 추출
2. **Transform**: 정제, 변환
3. **Load**: 대상에 저장

## REZE Data Flow
```
외부 API → signals 테이블 → judgment → daemon_tasks
                ↓
           daily_report → Discord
```

## Scheduling
APScheduler 사용:
```python
scheduler.add_job(func, "cron", hour=6)
scheduler.add_job(func, "interval", hours=6)
```
