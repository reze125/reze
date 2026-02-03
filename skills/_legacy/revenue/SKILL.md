---
name: revenue
description: 매출 분석 — 전체 수익, 제품별 매출, 트렌드
type: biz
triggers:
  - revenue
  - 매출
  - 수익
  - income
  - 매출분석
health_checks: []
fix_actions: []
---
# Revenue Analysis

## Revenue Sources
| Product | Platform | Pricing |
|---------|----------|---------|
| QuotePilot | LemonSqueezy | $19/$49/$99 |
| PostPilot | LemonSqueezy | TBD |
| BrowserPilot | LemonSqueezy | TBD |
| RapidAPI | RapidAPI | Usage-based |
| Affiliate | Various | Commission |

## Metrics
- MRR (Monthly Recurring Revenue)
- ARR (Annual Recurring Revenue)
- Churn Rate
- LTV (Lifetime Value)
- CAC (Customer Acquisition Cost)

## Data Sources
- LemonSqueezy API (lemonsqueezy skill)
- RapidAPI Dashboard
- Affiliate networks

## Analysis
```sql
-- 월별 매출
SELECT
  DATE_TRUNC('month', created_at) as month,
  SUM(total) / 100 as revenue
FROM orders
WHERE status = 'paid'
GROUP BY 1
ORDER BY 1;
```
