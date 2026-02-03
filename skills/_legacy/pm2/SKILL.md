---
name: pm2
description: PM2 프로세스 매니저 — Node.js 앱 관리, 로그, 모니터링
type: infra
triggers:
  - pm2
  - process manager
  - node process
health_checks:
  - name: pm2_daemon
    command: "pm2 ping > /dev/null 2>&1 && echo OK || echo FAIL"
    expect: "OK"
    severity: critical
  - name: all_online
    command: "pm2 jlist 2>/dev/null | python3 -c \"import sys,json; d=json.load(sys.stdin); print('OK' if all(p['pm2_env']['status']=='online' for p in d) else 'FAIL')\""
    expect: "OK"
    severity: warning
fix_actions:
  - trigger: "pm2_daemon"
    command: "pm2 resurrect"
    verify: "pm2 ping > /dev/null 2>&1 && echo OK"
---
# PM2 Process Manager

## Commands
```bash
# 상태 확인
pm2 list
pm2 jlist              # JSON 출력
pm2 monit              # 실시간 모니터

# 프로세스 관리
pm2 start app.js --name myapp
pm2 restart myapp
pm2 stop myapp
pm2 delete myapp

# 로그
pm2 logs myapp --lines 100
pm2 flush              # 로그 클리어

# 저장/복구
pm2 save               # 현재 프로세스 저장
pm2 resurrect          # 저장된 프로세스 복구
```

## 현재 프로세스
| Name | Port | Path |
|------|------|------|
| ai-tools-lab | 3005 | ~/ai-tools-lab |
| postpilot-backend | 8000 | ~/postpilot/backend |
| postpilot-frontend | 3000 | ~/postpilot/frontend |
| quotepilot-api | 8030 | ~/quotepilot/backend |
| browserpilot-api | 8100 | ~/browserpilot/backend |
| agenthub-api | 8101 | ~/agenthub/backend |
| rag-service | 8020 | ~/rag-service/backend |
| rapidapi-server | 8001 | ~/rapidapi_server |
| rapidapi-nocode | 8002 | ~/rapidapi_nocode_server |
| reze | 8300 | ~/reze-agent |
