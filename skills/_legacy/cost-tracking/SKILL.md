---
name: cost-tracking
description: 비용 추적 — API 사용량, 서버 비용
type: ops
triggers:
  - cost
  - 비용
  - spending
  - budget
  - 예산
health_checks: []
fix_actions: []
---
# Cost Tracking

## Monthly Costs
| Category | Item | Cost |
|----------|------|------|
| Server | Vultr/Hetzner | $XX/mo |
| API | OpenRouter | Usage |
| Domain | runstate.dev | $XX/yr |
| Tools | TBD | TBD |

## API Usage
```sql
-- 일일 토큰 사용량
SELECT date, total_tokens FROM daily_budget ORDER BY date DESC LIMIT 7;

-- 프로바이더별 호출 수
SELECT provider, COUNT(*) FROM traces
WHERE created_at > datetime('now', '-30 days')
GROUP BY provider;
```

## Budget Limits
- Daily tokens: 500,000
- Monthly API: $XX
- Alert threshold: 80%

## Optimization
1. 캐싱 (plan_cache)
2. 모델 선택 (저렴한 모델 우선)
3. 불필요한 호출 줄이기
