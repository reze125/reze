---
name: backup
description: 백업 전략 — DB, 코드, 설정 파일 백업
type: infra
triggers:
  - backup
  - 백업
  - restore
  - 복구
health_checks:
  - name: backup_dir_exists
    command: "test -d ~/backups && echo OK || echo FAIL"
    expect: "OK"
    severity: warning
fix_actions:
  - trigger: "backup_dir_exists"
    command: "mkdir -p ~/backups"
    verify: "test -d ~/backups && echo OK"
---
# Backup Strategy

## Backup Locations
- DB: ~/backups/db/
- Code: Git repositories
- Config: ~/backups/config/

## Database Backup
```bash
# aitoolslab DB
docker exec quotepilot-db pg_dump -U quotepilot aitoolslab > ~/backups/db/aitoolslab_$(date +%Y%m%d).sql

# quotepilot DB
docker exec quotepilot-db pg_dump -U quotepilot quotepilot > ~/backups/db/quotepilot_$(date +%Y%m%d).sql
```

## Code Backup
```bash
# Git 태그로 스냅샷
cd ~/reze-agent
git add -A && git commit -m "backup: $(date +%Y%m%d)" && git tag backup-$(date +%Y%m%d)
```

## Config Backup
```bash
# nginx
sudo cp -r /etc/nginx ~/backups/config/nginx_$(date +%Y%m%d)

# PM2
pm2 save
cp ~/.pm2/dump.pm2 ~/backups/config/
```

## Restore
```bash
# DB
psql -h localhost -p 5433 -U quotepilot -d aitoolslab < backup.sql

# Git
git checkout backup-20260201 -- .
```
