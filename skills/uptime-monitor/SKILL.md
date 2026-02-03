---
name: uptime-monitor
description: 서비스 가동시간 모니터링
type: monitoring
triggers:
  - uptime
  - 가동시간
  - availability
health_checks: []
fix_actions: []
---
# Uptime Monitoring

## Monitored Endpoints
| Service | URL | Check Interval |
|---------|-----|----------------|
| AI Tools Lab | https://aitoolslab.runstate.dev | 5min |
| PostPilot | https://postpilot.runstate.dev | 5min |
| QuotePilot | https://quotepilot.runstate.dev | 5min |
| BrowserPilot | https://browserpilot.runstate.dev | 5min |
| AgentHub | https://agenthub.runstate.dev | 5min |

## Internal health_check
REZE 스케줄러가 매시간 모든 서비스 체크.

## SLA Target
- 99.9% uptime = 8.76 hours downtime/year
- Target: 99.5%

## Incident Response
1. 알림 수신
2. 서비스 확인
3. 자동 재시작 (self_healing)
4. 수동 개입 필요 시 LOCK
