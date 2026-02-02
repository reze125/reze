---
name: quotepilot
description: QuotePilot AI 견적 자동화 SaaS (API:8030, DB:PostgreSQL 5433)
triggers:
  - quotepilot
  - 쿼트파일럿
  - 견적
  - catering quote
---
# QuotePilot

- API: PM2 quotepilot-api, port 8030, /home/reze/quotepilot/backend
- DB: Docker quotepilot-db, PostgreSQL port 5433
- Domain: quotepilot.runstate.dev
- Health: GET http://localhost:8030/health
- Restart: pm2 restart quotepilot-api
- DB access: docker exec quotepilot-db psql -U postgres -d quotepilot
- Plans: $19/$49/$99, Stripe payments
- Logs: pm2 logs quotepilot-api --lines 50
