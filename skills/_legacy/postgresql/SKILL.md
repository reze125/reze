---
name: postgresql
description: PostgreSQL 데이터베이스 관리, 백업, 쿼리
type: infra
triggers:
  - postgresql
  - postgres
  - psql
  - database
  - db
health_checks:
  - name: quotepilot_db
    command: "docker exec quotepilot-db pg_isready -U postgres && echo OK || echo FAIL"
    expect: "OK"
    severity: critical
fix_actions:
  - trigger: "quotepilot_db"
    command: "docker restart quotepilot-db"
    verify: "sleep 10 && docker exec quotepilot-db pg_isready -U postgres && echo OK"
---
# PostgreSQL (Docker)

## Databases
| Container | Port | Database | User |
|-----------|------|----------|------|
| quotepilot-db | 5433 | quotepilot | quotepilot |
| quotepilot-db | 5433 | aitoolslab | quotepilot |

## Access
```bash
# psql 접속
docker exec -it quotepilot-db psql -U quotepilot -d aitoolslab

# 외부 접속
psql -h localhost -p 5433 -U quotepilot -d aitoolslab
```

## Common Queries
```sql
-- 테이블 목록
\dt

-- 테이블 구조
\d tablename

-- 데이터 확인
SELECT * FROM articles LIMIT 10;

-- 백업
pg_dump -h localhost -p 5433 -U quotepilot aitoolslab > backup.sql
```

## Backup
```bash
# Docker 내부 백업
docker exec quotepilot-db pg_dump -U quotepilot aitoolslab > ~/backups/db_$(date +%Y%m%d).sql
```
