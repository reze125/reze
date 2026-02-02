---
name: browserpilot
description: BrowserPilot 브라우저 자동화 SaaS (port 8100)
triggers:
  - browserpilot
  - 브라우저파일럿
  - browser automation
---
# BrowserPilot

- API: PM2 browserpilot-api, port 8100, /home/reze/browserpilot/backend
- Domain: browserpilot.runstate.dev
- Health: GET http://localhost:8100/health
- Restart: pm2 restart browserpilot-api
- Logs: pm2 logs browserpilot-api --lines 50
