---
name: quotepilot
description: QuotePilot AI 견적 자동화 SaaS (API:8030, DB:PostgreSQL 5433)
type: service
triggers:
  - quotepilot
  - 쿼트파일럿
  - 견적
  - catering quote
health_checks:
  - name: api_health
    command: "curl -sf http://localhost:8030/health -o /dev/null && echo OK || echo FAIL"
    expect: "OK"
    severity: critical
  - name: db_health
    command: "docker exec quotepilot-db pg_isready -U postgres && echo OK || echo FAIL"
    expect: "OK"
    severity: critical
fix_actions:
  - trigger: "api_health"
    command: "pm2 restart quotepilot-api"
    verify: "sleep 5 && curl -sf http://localhost:8030/health -o /dev/null && echo OK"
  - trigger: "db_health"
    command: "docker restart quotepilot-db"
    verify: "sleep 10 && docker exec quotepilot-db pg_isready -U postgres && echo OK"
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
