---
name: self-diagnosis
description: REZE 자가 진단 — 성능, 에러율, 병목
type: self
triggers:
  - self-diagnosis
  - 자가진단
  - 진단
  - diagnosis
health_checks:
  - name: reze_health
    command: "curl -sf http://localhost:8300/health -o /dev/null && echo OK || echo FAIL"
    expect: "OK"
    severity: critical
fix_actions:
  - trigger: "reze_health"
    command: "pm2 restart reze"
    verify: "sleep 5 && curl -sf http://localhost:8300/health -o /dev/null && echo OK"
---
# Self-Diagnosis

## Metrics to Monitor
1. **Response Time**: API 응답 시간
2. **Error Rate**: 실패 태스크 비율
3. **Token Usage**: 일일 토큰 사용량
4. **LLM Latency**: 프로바이더별 지연
5. **Queue Depth**: 대기 중인 태스크

## Health Indicators
- Green: 모든 시스템 정상
- Yellow: 일부 경고 (높은 에러율, 느린 응답)
- Red: 장애 발생

## Diagnosis Queries
```sql
-- 최근 에러율
SELECT
  COUNT(CASE WHEN status = 'failed' THEN 1 END) * 100.0 / COUNT(*) as error_rate
FROM daemon_tasks
WHERE created_at > datetime('now', '-24 hours');

-- 프로바이더별 통계
SELECT provider, AVG(latency_ms), COUNT(*)
FROM traces
WHERE created_at > datetime('now', '-24 hours')
GROUP BY provider;
```
