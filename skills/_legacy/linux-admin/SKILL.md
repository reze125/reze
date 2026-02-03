---
name: linux-admin
description: Linux 시스템 관리 — 디스크, 메모리, 네트워크, 프로세스
type: infra
triggers:
  - linux
  - ubuntu
  - system
  - disk
  - memory
  - network
  - process
health_checks:
  - name: disk_space
    command: "df / --output=pcent | tail -1 | tr -d ' %'"
    verify_check: "int(output) < 85"
    severity: warning
  - name: memory
    command: "free | grep Mem | awk '{printf \"%.0f\", $3/$2*100}'"
    verify_check: "int(output) < 90"
    severity: warning
  - name: load_avg
    command: "uptime | awk -F'load average:' '{print $2}' | cut -d, -f1 | tr -d ' '"
    verify_check: "float(output) < 8.0"
    severity: warning
fix_actions:
  - trigger: "disk_space"
    command: "docker system prune -f --volumes; find /tmp -type f -mtime +7 -delete 2>/dev/null; journalctl --vacuum-time=7d"
    verify: "df / --output=pcent | tail -1 | tr -d ' %'"
---
# Linux System Administration

## System Info
- OS: Ubuntu 24
- Python: 3.12.3
- Home: /home/reze

## Resource Monitoring
```bash
# 디스크
df -h
du -sh /home/reze/*

# 메모리
free -h
top -bn1 | head -20

# CPU
uptime
htop

# 네트워크
ss -tulpn          # 열린 포트
netstat -an        # 연결 상태
```

## Disk Cleanup
```bash
# Docker 정리
docker system prune -f --volumes

# 임시 파일
find /tmp -type f -mtime +7 -delete

# 로그 정리
journalctl --vacuum-time=7d
```

## Port Usage
| Port | Service |
|------|---------|
| 3000-3005 | Frontend apps |
| 5433 | PostgreSQL |
| 5678 | n8n |
| 6333 | Qdrant |
| 8000-8300 | Backend APIs |
