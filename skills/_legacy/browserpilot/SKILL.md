---
name: browserpilot
description: BrowserPilot 브라우저 자동화 SaaS (port 8100)
type: service
triggers:
  - browserpilot
  - 브라우저파일럿
  - browser automation
health_checks:
  - name: api_health
    command: "curl -sf http://localhost:8100/health -o /dev/null && echo OK || echo FAIL"
    expect: "OK"
    severity: critical
fix_actions:
  - trigger: "api_health"
    command: "pm2 restart browserpilot-api"
    verify: "sleep 5 && curl -sf http://localhost:8100/health -o /dev/null && echo OK"
---
# BrowserPilot

- API: PM2 browserpilot-api, port 8100, /home/reze/browserpilot/backend
- Domain: browserpilot.runstate.dev
- Health: GET http://localhost:8100/health
- Restart: pm2 restart browserpilot-api
- Logs: pm2 logs browserpilot-api --lines 50
