---
name: agenthub
description: AgentHub AI 에이전트 마켓플레이스 (port 8101)
type: service
triggers:
  - agenthub
  - 에이전트허브
  - agent marketplace
health_checks:
  - name: api_health
    command: "curl -sf http://localhost:8101/health -o /dev/null && echo OK || echo FAIL"
    expect: "OK"
    severity: critical
fix_actions:
  - trigger: "api_health"
    command: "pm2 restart agenthub-api"
    verify: "sleep 5 && curl -sf http://localhost:8101/health -o /dev/null && echo OK"
---
# AgentHub

- API: PM2 agenthub-api, port 8101, /home/reze/agenthub/backend
- Domain: agenthub.runstate.dev
- Health: GET http://localhost:8101/health
- Restart: pm2 restart agenthub-api
- Logs: pm2 logs agenthub-api --lines 50
