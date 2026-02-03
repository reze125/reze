---
name: rapidapi
description: RapidAPI 서버 2개 (server:8001, nocode:8002)
type: service
triggers:
  - rapidapi
  - rapid api
health_checks:
  - name: server_health
    command: "curl -sf http://localhost:8001/health -o /dev/null && echo OK || echo FAIL"
    expect: "OK"
    severity: warning
  - name: nocode_health
    command: "curl -sf http://localhost:8002/health -o /dev/null && echo OK || echo FAIL"
    expect: "OK"
    severity: warning
fix_actions:
  - trigger: "server_health"
    command: "pm2 restart rapidapi-server"
    verify: "sleep 5 && curl -sf http://localhost:8001/health -o /dev/null && echo OK"
  - trigger: "nocode_health"
    command: "pm2 restart rapidapi-nocode"
    verify: "sleep 5 && curl -sf http://localhost:8002/health -o /dev/null && echo OK"
---
# RapidAPI Services

- Server: PM2 rapidapi-server, port 8001, /home/reze/rapidapi_server
- NoCode: PM2 rapidapi-nocode, port 8002, /home/reze/rapidapi_nocode_server
- Health: GET http://localhost:8001/health, GET http://localhost:8002/health
- Restart: pm2 restart rapidapi-server && pm2 restart rapidapi-nocode
