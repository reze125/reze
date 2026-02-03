---
name: analytics
description: 분석 — 트래픽, 사용자, 전환
type: monitoring
triggers:
  - analytics
  - 분석
  - traffic
  - 트래픽
  - 방문자
health_checks: []
fix_actions: []
---
# Analytics

## Platforms
- Google Analytics (블로그)
- REZE 내부 트래킹 (SaaS)
- LemonSqueezy (매출)

## Key Metrics
### Blog
- Page views
- Unique visitors
- Bounce rate
- Average session duration
- Top pages

### SaaS
- Signups
- Activations
- Conversions
- Churn

## Reporting
- 일간: 핵심 지표 (데일리 리포트)
- 주간: 트렌드 분석
- 월간: 심층 분석

## Data Sources
```sql
-- REZE 태스크 통계
SELECT DATE(created_at), COUNT(*),
       SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success
FROM daemon_tasks
GROUP BY DATE(created_at);
```
