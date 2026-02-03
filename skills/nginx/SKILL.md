---
name: nginx
description: Nginx 리버스 프록시, SSL, 도메인 라우팅
type: infra
triggers:
  - nginx
  - reverse proxy
  - ssl
  - https
  - domain
health_checks:
  - name: nginx_running
    command: "systemctl is-active nginx"
    expect: "active"
    severity: critical
  - name: config_valid
    command: "nginx -t 2>&1 | grep -c 'successful'"
    verify_check: "int(output) >= 1"
    severity: critical
fix_actions:
  - trigger: "nginx_running"
    command: "sudo systemctl restart nginx"
    verify: "systemctl is-active nginx"
---
# Nginx Configuration

## Locations
- Config: /etc/nginx/sites-available/, /etc/nginx/sites-enabled/
- Logs: /var/log/nginx/access.log, error.log

## Commands
```bash
# 상태
sudo systemctl status nginx
nginx -t                      # 설정 테스트

# 관리
sudo systemctl reload nginx   # 설정 리로드 (무중단)
sudo systemctl restart nginx  # 재시작

# 설정
sudo ln -s /etc/nginx/sites-available/mysite /etc/nginx/sites-enabled/
```

## Domain Routing
| Domain | Upstream |
|--------|----------|
| postpilot.runstate.dev | localhost:3000 |
| api.postpilot.runstate.dev | localhost:8000 |
| quotepilot.runstate.dev | localhost:8030 |
| browserpilot.runstate.dev | localhost:8100 |
| agenthub.runstate.dev | localhost:8101 |
| aitoolslab.runstate.dev | localhost:3005 |
| n8n.runstate.dev | localhost:5678 |
