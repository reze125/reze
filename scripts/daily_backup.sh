#!/bin/bash
# REZE 일일 백업 스크립트
BACKUP_DIR="/home/reze/backups"
DATE=$(date +%Y%m%d_%H%M)
mkdir -p "$BACKUP_DIR"

# 1. REZE SQLite (WAL 안전 백업)
sqlite3 /home/reze/reze-agent/reze_data/ssot.sqlite ".backup '$BACKUP_DIR/ssot_$DATE.db'" 2>/dev/null

# 2. QuotePilot PostgreSQL
docker exec quotepilot-db pg_dump -U postgres quotepilot 2>/dev/null \
  | gzip > "$BACKUP_DIR/quotepilot_$DATE.sql.gz"

# 3. Listmonk PostgreSQL
docker exec listmonk-db pg_dump -U listmonk listmonk 2>/dev/null \
  | gzip > "$BACKUP_DIR/listmonk_$DATE.sql.gz"

# 4. 7일 초과 백업 삭제
find "$BACKUP_DIR" -type f -mtime +7 -delete 2>/dev/null

echo "[backup] $DATE completed ($(ls -1 $BACKUP_DIR | wc -l) files)"
