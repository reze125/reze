---
name: server-hardening
description: 서버 보안 강화 — 방화벽, SSH, 권한
type: security
triggers:
  - security
  - 보안
  - hardening
  - firewall
  - ssh
health_checks:
  - name: ssh_root_disabled
    command: "grep -c 'PermitRootLogin no' /etc/ssh/sshd_config || echo 0"
    verify_check: "int(output) >= 1"
    severity: warning
  - name: ufw_active
    command: "ufw status | grep -c 'Status: active' || echo 0"
    verify_check: "int(output) >= 1"
    severity: warning
fix_actions: []
---
# Server Hardening

## Checklist
- [x] SSH: Key-only, no root login
- [x] UFW: Firewall enabled
- [x] Fail2ban: Brute force protection
- [ ] Auto-updates: unattended-upgrades
- [x] HTTPS: All domains SSL

## Allowed Ports (UFW)
| Port | Service |
|------|---------|
| 22 | SSH |
| 80 | HTTP |
| 443 | HTTPS |

## SSH Config
```
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
```

## Monitoring
- fail2ban-client status
- ufw status verbose
- last (로그인 기록)
