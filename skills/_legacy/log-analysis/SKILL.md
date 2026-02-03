---
name: log-analysis
description: 로그 분석 — 에러 패턴, 디버깅
type: monitoring
triggers:
  - log
  - 로그
  - error
  - 에러
  - debug
health_checks: []
fix_actions: []
---
# Log Analysis

## Log Locations
| Service | Command |
|---------|---------|
| PM2 apps | pm2 logs {name} --lines 100 |
| Docker | docker logs {container} --tail 100 |
| Nginx | /var/log/nginx/error.log |
| System | journalctl -u {service} |

## Common Patterns
```bash
# 에러 찾기
pm2 logs postpilot-backend --lines 1000 | grep -i error

# 최근 에러
docker logs n8n --since 1h 2>&1 | grep -i error

# 특정 시간대
journalctl --since "2026-02-03 10:00" --until "2026-02-03 11:00"
```

## Error Categories
1. **Connection**: DB, API 연결 실패
2. **Timeout**: 응답 지연
3. **OOM**: 메모리 부족
4. **Permission**: 권한 문제

## Analysis Workflow
1. 에러 로그 수집
2. 패턴 분석 (반복 에러)
3. 근본 원인 파악
4. 수정 및 모니터링
