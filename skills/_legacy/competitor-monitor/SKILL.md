---
name: competitor-monitor
description: 경쟁사 모니터링 — 가격, 기능, 마케팅
type: research
triggers:
  - competitor
  - 경쟁사
  - 경쟁
  - competition
health_checks: []
fix_actions: []
---
# Competitor Monitor

## SaaS Competitors
| Our Product | Competitors |
|-------------|-------------|
| QuotePilot | Quotient, PandaDoc |
| PostPilot | Buffer, Hootsuite |
| BrowserPilot | Selenium Cloud, Browserbase |
| AgentHub | AgentGPT, AutoGPT platforms |

## Monitor Points
1. **Pricing Changes**: 가격 인상/인하
2. **New Features**: 기능 추가
3. **Marketing**: 캠페인, 포지셔닝
4. **Reviews**: G2, Capterra 평점

## Actions on Change
- 가격 변경 → pricing-analysis 스킬 트리거
- 새 기능 → 구현 검토
- 마케팅 → 블로그 대응

## Schedule
- 매주 월요일 09:00
