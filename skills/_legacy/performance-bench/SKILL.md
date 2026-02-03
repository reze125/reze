---
name: performance-bench
description: 성능 벤치마킹 — 응답시간, 처리량
type: monitoring
triggers:
  - performance
  - 성능
  - benchmark
  - latency
  - 지연
health_checks: []
fix_actions: []
---
# Performance Benchmarking

## Metrics
1. **Response Time**: API 응답 시간
2. **Throughput**: 초당 요청 수
3. **Error Rate**: 에러 비율
4. **Resource Usage**: CPU, Memory

## REZE Performance
```sql
-- 프로바이더별 평균 지연
SELECT provider, AVG(latency_ms) as avg_latency
FROM traces
WHERE span_type = 'llm_call'
GROUP BY provider;
```

## Benchmarking Tools
```bash
# HTTP 벤치마크
ab -n 100 -c 10 http://localhost:8300/health
wrk -t4 -c100 -d30s http://localhost:8300/health
```

## Targets
| Endpoint | Target |
|----------|--------|
| /health | < 50ms |
| /run (sync) | < 30s |
| LLM call | < 5s |
