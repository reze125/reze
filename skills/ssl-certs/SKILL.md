---
name: ssl-certs
description: SSL 인증서 관리 — Let's Encrypt, certbot
type: infra
triggers:
  - ssl
  - certificate
  - certbot
  - https
  - letsencrypt
health_checks:
  - name: cert_valid
    command: "certbot certificates 2>/dev/null | grep -c 'VALID' || echo 0"
    verify_check: "int(output) >= 1"
    severity: warning
fix_actions:
  - trigger: "cert_valid"
    command: "sudo certbot renew --nginx --quiet"
    verify: "certbot certificates 2>/dev/null | grep -c 'VALID'"
---
# SSL Certificates (Let's Encrypt)

## Check Status
```bash
sudo certbot certificates
```

## Renew
```bash
# 자동 갱신 테스트
sudo certbot renew --dry-run

# 실제 갱신
sudo certbot renew --nginx
```

## Add New Domain
```bash
sudo certbot --nginx -d newdomain.runstate.dev
```

## Managed Domains
- *.runstate.dev (wildcard or individual)
- postpilot.runstate.dev
- quotepilot.runstate.dev
- browserpilot.runstate.dev
- agenthub.runstate.dev
- aitoolslab.runstate.dev
- n8n.runstate.dev

## Auto-Renewal
Certbot auto-renewal is configured via systemd timer.
```bash
systemctl status certbot.timer
```
