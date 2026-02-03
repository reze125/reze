---
name: postpilot
description: PostPilot AI 블로그 자동화 SaaS 관리 (backend:8000, frontend:3000)
type: service
triggers:
  - postpilot
  - 포스트파일럿
  - blog automation saas
health_checks:
  - name: backend_health
    command: "curl -sf http://localhost:8000/health -o /dev/null && echo OK || echo FAIL"
    expect: "OK"
    severity: critical
  - name: frontend_health
    command: "curl -sf http://localhost:3000 -o /dev/null && echo OK || echo FAIL"
    expect: "OK"
    severity: critical
fix_actions:
  - trigger: "backend_health"
    command: "pm2 restart postpilot-backend"
    verify: "sleep 5 && curl -sf http://localhost:8000/health -o /dev/null && echo OK"
  - trigger: "frontend_health"
    command: "pm2 restart postpilot-frontend"
    verify: "sleep 5 && curl -sf http://localhost:3000 -o /dev/null && echo OK"
---
# PostPilot

- Backend: PM2 postpilot-backend, port 8000, /home/reze/postpilot/backend
- Frontend: PM2 postpilot-frontend, port 3000, /home/reze/postpilot/frontend
- Domain: postpilot.runstate.dev (frontend), api.postpilot.runstate.dev (backend)
- Health: GET http://localhost:8000/health
- Restart: pm2 restart postpilot-backend && pm2 restart postpilot-frontend
- Known issue: beautifulsoup4 (bs4) dependency
- Logs: pm2 logs postpilot-backend --lines 50
