---
name: n8n-workflow
description: n8n 워크플로우 자동화
type: ops
triggers:
  - n8n
  - workflow
  - 워크플로우
  - automation
health_checks:
  - name: n8n_health
    command: "curl -sf http://localhost:5678 -o /dev/null && echo OK || echo FAIL"
    expect: "OK"
    severity: warning
fix_actions:
  - trigger: "n8n_health"
    command: "docker restart n8n"
    verify: "sleep 15 && curl -sf http://localhost:5678 -o /dev/null && echo OK"
---
# n8n Workflow Automation

## Access
- URL: http://localhost:5678
- Domain: n8n.runstate.dev

## Active Workflows
| Name | Trigger | Action |
|------|---------|--------|
| TBD | TBD | TBD |

## Common Integrations
- Webhook → REZE
- RSS → Discord
- Schedule → Report
- Email → Task

## Backup
n8n 워크플로우는 데이터베이스에 저장됨.
Docker 볼륨 백업 필요.
