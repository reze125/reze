---
name: agenthub
description: AgentHub AI 에이전트 마켓플레이스 (port 8101)
triggers:
  - agenthub
  - 에이전트허브
  - agent marketplace
---
# AgentHub

- API: PM2 agenthub-api, port 8101, /home/reze/agenthub/backend
- Domain: agenthub.runstate.dev
- Health: GET http://localhost:8101/health
- Restart: pm2 restart agenthub-api
- Logs: pm2 logs agenthub-api --lines 50
